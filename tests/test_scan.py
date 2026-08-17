"""Tests for pi-usage: pure stdlib (unittest + tempfile), no dependencies.

Creates synthetic JSONL sessions like ~/.pi/agent/sessions/<project>/<id>.jsonl
and checks the aggregation in pi_usage.scan() plus the --json endpoint via CLI.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "bin" / "pi-usage"

# bin/pi-usage has no .py extension -> explicit SourceFileLoader
_loader = importlib.machinery.SourceFileLoader("pi_usage", str(SRC))
_spec = importlib.util.spec_from_loader("pi_usage", _loader)
assert _spec is not None and _spec.loader is not None
pi_usage = importlib.util.module_from_spec(_spec)
_loader.exec_module(pi_usage)


def usage(**kw):
    base = {
        "input": 1000,
        "output": 500,
        "cacheRead": 100,
        "cacheWrite": 50,
        "reasoning": 0,
        "totalTokens": 1650,
        "cost": {
            "input": 0.01,
            "output": 0.005,
            "cacheRead": 0.001,
            "cacheWrite": 0.0005,
            "total": 0.0165,
        },
    }
    base.update(kw)
    return base


def line(ts, model="gpt-4o", provider="openai", role="assistant", usg=None):
    msg = {"role": role, "model": model, "provider": provider, "usage": usg or usage()}
    rec = {"type": "message", "message": msg}
    if isinstance(ts, str):
        rec["timestamp"] = ts
    else:
        rec["message"]["timestamp"] = ts  # ms-Epoch (Fallback-Zweig)
    return json.dumps(rec)


def iso(day, hh=12):
    dt = datetime(day.year, day.month, day.day, hh, 0, 0, tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def write_session(root, project, session_id, lines):
    d = root / project
    d.mkdir(parents=True, exist_ok=True)
    (d / (session_id + ".jsonl")).write_text("\n".join(lines) + "\n", encoding="utf-8")


def plain(x):
    """Convert nested defaultdicts/sets/date into plain values (deep) —
    allows comparing results regardless of the aggregate type."""
    if isinstance(x, dict):
        return {k: plain(v) for k, v in x.items()}
    if isinstance(x, (set, list, tuple)):
        return [plain(v) for v in sorted(x, key=str)]
    return x


class ScanTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.old_dir = pi_usage.SESSIONS_DIR
        self._old_xdg = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = str(self.root / "cache")   # Cache-Tests isolieren

    def tearDown(self):
        pi_usage.SESSIONS_DIR = self.old_dir
        if self._old_xdg is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self._old_xdg
        self._tmp.cleanup()

    def scan(self):
        pi_usage.SESSIONS_DIR = self.root
        return pi_usage.scan()

    def test_by_day_model_provider(self):
        d = date(2026, 8, 17)
        write_session(self.root, "proj-a", "s1", [
            line(iso(d, 9), model="claude-3.7", provider="anthropic"),
            line(iso(d, 10), model="claude-3.7", provider="anthropic"),
        ])
        max_day, by_day, by_model, by_provider, *_ = self.scan()
        self.assertEqual(max_day, d)
        k = d.isoformat()
        self.assertEqual(by_day[k]["requests"], 2)
        self.assertEqual(by_day[k]["tokens"], 2 * 1650)
        self.assertAlmostEqual(by_day[k]["cost"]["total"], 2 * 0.0165)
        self.assertEqual(by_model["claude-3.7"]["requests"], 2)
        self.assertEqual(by_provider["anthropic"]["requests"], 2)

    def test_project_and_session_keys(self):
        write_session(self.root, "proj-a", "s1", [line(iso(date(2026, 8, 17)))])
        write_session(self.root, "proj-b", "s2", [line(iso(date(2026, 8, 18)))])
        *_, by_project, by_session, _ = self.scan()
        self.assertEqual(by_project["proj-a"]["requests"], 1)
        self.assertEqual(by_project["proj-b"]["requests"], 1)
        self.assertEqual(set(by_session["s1"]["sessions"]), {"s1"})
        self.assertEqual(set(by_session["s2"]["sessions"]), {"s2"})

    def test_multiple_sessions_same_project(self):
        write_session(self.root, "proj-a", "s1", [line(iso(date(2026, 8, 17)))])
        write_session(self.root, "proj-a", "s2", [line(iso(date(2026, 8, 17)))])
        *_, by_project, _, _ = self.scan()
        # sessions are counted de-duplicated per day
        self.assertEqual(len(by_project["proj-a"]["sessions"]), 2)
        self.assertEqual(by_project["proj-a"]["requests"], 2)

    def test_distinct_days(self):
        d1, d2 = date(2026, 8, 17), date(2026, 8, 18)
        write_session(self.root, "proj-a", "s1", [line(iso(d1)), line(iso(d2))])
        by_day = self.scan()[1]
        self.assertIn(d1.isoformat(), by_day)
        self.assertIn(d2.isoformat(), by_day)
        self.assertEqual(by_day[d1.isoformat()]["requests"], 1)
        self.assertEqual(by_day[d2.isoformat()]["requests"], 1)

    def test_ignores_non_assistant_and_missing_usage(self):
        write_session(self.root, "proj-a", "s1", [
            line(iso(date(2026, 8, 17)), role="user"),          # role!=assistant
            json.dumps({"type": "message", "message": {"role": "assistant"}}),  # kein usage
            line(iso(date(2026, 8, 17))),
        ])
        by_day = self.scan()[1]
        self.assertEqual(by_day["2026-08-17"]["requests"], 1)

    def test_timestamp_integer_ms_fallback(self):
        # no rec["timestamp"], instead message.timestamp in ms
        ts = int(datetime(2026, 8, 17, 12, tzinfo=timezone.utc).timestamp() * 1000)
        write_session(self.root, "proj-a", "s1", [line(ts)])
        by_day = self.scan()[1]
        self.assertIn("2026-08-17", by_day)

    def test_undated_when_no_timestamp(self):
        write_session(self.root, "proj-a", "s1", [line(None)])
        by_day = self.scan()[1]
        self.assertIn("undated", by_day)

    def test_reasoning_and_cache(self):
        u = usage(cacheRead=999, cacheWrite=111, reasoning=777, totalTokens=2347)
        write_session(self.root, "proj-a", "s1", [line(iso(date(2026, 8, 17)), usg=u)])
        by_day = self.scan()[1]
        a = by_day["2026-08-17"]
        self.assertEqual(a["cacheRead"], 999)
        self.assertEqual(a["cacheWrite"], 111)
        self.assertEqual(a["reasoning"], 777)
        self.assertEqual(a["tokens"], 2347)

    def test_zero_cost(self):
        u = usage(cost={"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0})
        write_session(self.root, "proj-a", "s1", [line(iso(date(2026, 8, 17)), usg=u)])
        by_day = self.scan()[1]
        self.assertEqual(by_day["2026-08-17"]["cost"]["total"], 0.0)


class CacheTest(unittest.TestCase):
    """Behavior of the persistent mtime/size scan cache:
    warm scans re-parse nothing, changes trigger a re-parse,
    and the result is identical to a full fresh scan."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._old_dir = pi_usage.SESSIONS_DIR
        self._old_xdg = os.environ.get("XDG_CACHE_HOME")
        self._old_nc = os.environ.get("PI_USAGE_NO_CACHE")
        os.environ["XDG_CACHE_HOME"] = str(Path(self._tmp.name) / "cache")
        os.environ.pop("PI_USAGE_NO_CACHE", None)
        pi_usage.SESSIONS_DIR = self.root

    def tearDown(self):
        pi_usage.SESSIONS_DIR = self._old_dir
        if self._old_xdg is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self._old_xdg
        if self._old_nc is None:
            os.environ.pop("PI_USAGE_NO_CACHE", None)
        else:
            os.environ["PI_USAGE_NO_CACHE"] = self._old_nc
        self._tmp.cleanup()

    def cache_files(self):
        return sorted(pi_usage._cache_dir().glob("*.json"))

    def test_warm_scan_parses_nothing_new(self):
        d = date(2026, 8, 17)
        write_session(self.root, "proj-a", "s1", [line(iso(d))])
        write_session(self.root, "proj-b", "s2", [line(iso(d))])

        parsed = {"n": 0}
        orig = pi_usage._parse_file

        def counting(*a, **k):
            parsed["n"] += 1
            return orig(*a, **k)

        pi_usage._parse_file = counting
        try:
            r1 = pi_usage.scan()
            n_after_cold = parsed["n"]
            r2 = pi_usage.scan()
        finally:
            pi_usage._parse_file = orig

        self.assertEqual(n_after_cold, 2)                   # kalt: beide geparst
        self.assertEqual(parsed["n"] - n_after_cold, 0)    # warm: nichts neu
        self.assertEqual(plain(r1), plain(r2))              # Ergebnis identisch

    def test_modified_file_reparsed_and_updated(self):
        d = date(2026, 8, 17)
        write_session(self.root, "proj-a", "s1", [line(iso(d, 9))])
        pi_usage.scan()
        # append a second line -> mtime+size change -> re-parse
        write_session(self.root, "proj-a", "s1", [
            line(iso(d, 9)),
            line(iso(d, 10), model="gpt-4o-mini", provider="openai"),
        ])
        res = pi_usage.scan()
        self.assertEqual(res[1][d.isoformat()]["requests"], 2)
        self.assertEqual(res[2]["gpt-4o-mini"]["requests"], 1)

    def test_size_change_without_mtime_change_invalidates(self):
        d = date(2026, 8, 17)
        fp = self.root / "proj-a" / "s1.jsonl"
        write_session(self.root, "proj-a", "s1", [line(iso(d))])
        st1 = fp.stat()
        pi_usage.scan()
        # change the content but artificially reset mtime to the old value:
        # only the size reveals the change -> the (mtime_ns, size) signature catches it.
        write_session(self.root, "proj-a", "s1", [line(iso(d)), line(iso(d, 11))])
        os.utime(fp, ns=(st1.st_atime_ns, st1.st_mtime_ns))
        by_day = pi_usage.scan()[1]
        self.assertEqual(by_day[d.isoformat()]["requests"], 2)

    def test_deleted_file_removed_from_results(self):
        d = date(2026, 8, 17)
        write_session(self.root, "proj-a", "s1", [line(iso(d))])
        pi_usage.scan()
        (self.root / "proj-a" / "s1.jsonl").unlink()
        res = pi_usage.scan()
        self.assertNotIn(d.isoformat(), res[1])
        self.assertNotIn("proj-a", res[3])

    def test_renamed_file_reparsed_under_new_name(self):
        d = date(2026, 8, 17)
        write_session(self.root, "proj-a", "s1", [line(iso(d))])
        pi_usage.scan()
        (self.root / "proj-a" / "s1.jsonl").rename(self.root / "proj-a" / "s1-neu.jsonl")
        res = pi_usage.scan()
        self.assertIn("s1-neu", res[5])
        self.assertNotIn("s1", res[5])

    def test_cache_future_scan_equals_full_reparse(self):
        d1, d2 = date(2026, 8, 17), date(2026, 8, 18)
        write_session(self.root, "proj-a", "s1", [line(iso(d1), model="claude-3.7", provider="anthropic")])
        write_session(self.root, "proj-a", "s2", [line(iso(d1), model="gpt-4o-mini"), line(iso(d2))])
        write_session(self.root, "proj-b", "s3", [line(iso(d2), model="claude-3.7", provider="anthropic")])
        cached = pi_usage.scan()
        os.environ["PI_USAGE_NO_CACHE"] = "1"
        fresh = pi_usage.scan()
        os.environ.pop("PI_USAGE_NO_CACHE", None)
        self.assertEqual(plain(cached), plain(fresh))

    def test_cache_persists_to_disk(self):
        write_session(self.root, "proj-a", "s1", [line(iso(date(2026, 8, 17)))])
        pi_usage.scan()
        shards = self.cache_files()
        self.assertEqual(len(shards), 1)          # one shard per project dir
        data = json.loads(shards[0].read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["rel_dir"], "proj-a")
        self.assertIn("s1.jsonl", data["files"])

    def test_change_rewrites_only_its_own_shard(self):
        d = date(2026, 8, 17)
        write_session(self.root, "proj-a", "s1", [line(iso(d))])
        write_session(self.root, "proj-b", "s2", [line(iso(d))])
        pi_usage.scan()

        def mtimes():
            return {p.name: p.stat().st_mtime_ns for p in self.cache_files()}

        before = mtimes()
        write_session(self.root, "proj-a", "s1", [line(iso(d)), line(iso(d, 11))])
        pi_usage.scan()
        changed = [n for n, t in mtimes().items() if t != before.get(n)]
        self.assertEqual(len(changed), 1)  # only proj-a's shard, not proj-b's

    def test_no_cache_env_bypasses_and_writes_nothing(self):
        write_session(self.root, "proj-a", "s1", [line(iso(date(2026, 8, 17)))])
        os.environ["PI_USAGE_NO_CACHE"] = "1"
        by_day = pi_usage.scan()[1]
        self.assertEqual(by_day["2026-08-17"]["requests"], 1)
        self.assertEqual(self.cache_files(), [])

    def test_warm_scan_does_not_rewrite_shards(self):
        """A warm scan with nothing changed must not touch any shard on
        disk (no pointless full rewrite every cycle while watching)."""
        d = date(2026, 8, 17)
        write_session(self.root, "proj-a", "s1", [line(iso(d))])
        pi_usage.scan()                     # cold: writes the shards

        def mtimes():
            return [p.stat().st_mtime_ns for p in self.cache_files()]

        before = mtimes()
        pi_usage.scan()                     # warm: nothing changed
        self.assertEqual(mtimes(), before)

    def test_changed_file_rewrites_cache(self):
        """A change still persists to disk — the write is skipped only when
        nothing changed, never when something did."""
        d = date(2026, 8, 17)
        write_session(self.root, "proj-a", "s1", [line(iso(d))])
        pi_usage.scan()
        before = [p.stat().st_mtime_ns for p in self.cache_files()]
        write_session(self.root, "proj-a", "s1", [line(iso(d)), line(iso(d, 11))])
        pi_usage.scan()
        after = [p.stat().st_mtime_ns for p in self.cache_files()]
        self.assertNotEqual(before, after)


class CliJsonTest(unittest.TestCase):
    def test_json_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_session(root, "proj-a", "s1", [line(iso(date(2026, 8, 17)))])
            env = dict(os.environ)
            env["PI_USAGE_NO_CACHE"] = "1"   # CLI-Test nie auf den realen Cache zugreifen
            p = subprocess.run(
                [sys.executable, str(SRC), "--json", "-s", str(root)],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            data = json.loads(p.stdout)
            self.assertIn("by_project", data)
            self.assertIn("proj-a", data["by_project"])
            self.assertEqual(data["by_project"]["proj-a"]["requests"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

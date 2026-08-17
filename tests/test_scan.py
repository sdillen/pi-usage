"""Tests für pi-usage: rein stdlib (unittest + tempfile), keine Dependencies.

Legt synthetische JSONL-Sessions wie ~/.pi/agent/sessions/<projekt>/<id>.jsonl an
und prüft die Aggregation in pi_usage.scan() sowie den --json-Endpoint via CLI.
"""
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "bin" / "pi-usage"

# bin/pi-usage hat keine .py-Endung -> expliziter SourceFileLoader
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


class ScanTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.old_dir = pi_usage.SESSIONS_DIR

    def tearDown(self):
        pi_usage.SESSIONS_DIR = self.old_dir
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
        # Sessions werden pro Tag dedupliziert gezählt
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
        # kein rec["timestamp"], dafür message.timestamp in ms
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


class CliJsonTest(unittest.TestCase):
    def test_json_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_session(root, "proj-a", "s1", [line(iso(date(2026, 8, 17)))])
            p = subprocess.run(
                [sys.executable, str(SRC), "--json", "-s", str(root)],
                capture_output=True, text=True,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            data = json.loads(p.stdout)
            self.assertIn("by_project", data)
            self.assertIn("proj-a", data["by_project"])
            self.assertEqual(data["by_project"]["proj-a"]["requests"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

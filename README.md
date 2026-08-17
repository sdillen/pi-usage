# pi-usage

Token & cost analytics for the [pi coding agent](https://github.com) — reads the
JSONL session files under `~/.pi/agent/sessions/` and aggregates per **model,
provider, project, day and session**. Zero dependencies, no SQLite, no web UI.
Prices are taken directly from the session logs (pi writes `usage.cost.total`
per assistant reply).

Output is colored in pi's "vesper" style (peach/mint/teal) and shows a stacked
cost bar (input / output / cache).

## Requirements

- Python ≥ 3.8 (stdlib only — `argparse`, `json`, `pathlib`, …)
- Session logs written by pi under `~/.pi/agent/sessions/`

## Install

The scripts are plain executables; drop them anywhere on your `PATH` and symlink
them. With home-manager this is a one-liner (out-of-store symlink so edits take
effect immediately, no rebuild):

```nix
home.file = {
  ".bin/pi-usage" = {
    source = config.lib.file.mkOutOfStoreSymlink
      "<repo>/bin/pi-usage";
  };
  ".bin/pi-usage-herdr" = {
    source = config.lib.file.mkOutOfStoreSymlink
      "<repo>/bin/pi-usage-herdr";
  };
};
```

## Usage

```
pi-usage                # Compact overview (Today + 7 days + totals)
pi-usage today          # Today (with cost bar)
pi-usage week           # Last 7 days (per day + per model)
pi-usage stats          # Totals by model, provider, project
pi-usage sessions       # Per session, sorted by usage
pi-usage --extended     # additionally show reasoning/cache tokens
pi-usage --json         # raw aggregates as JSON
pi-usage --no-color     # disable ANSI colors (NO_COLOR is honored too)
pi-usage -s <dir>       # use a different sessions directory
pi-usage -w             # watch: re-render every 5 s (Ctrl+C to stop)
pi-usage -w -n 10       # watch with custom interval (e.g. 10 s)
pi-usage -w today       # watch works with any view
```

Environment:

| Variable        | Effect                                        |
|-----------------|-----------------------------------------------|
| `PI_SESSIONS_DIR` | Default sessions directory (default `~/.pi/agent/sessions`) |
| `NO_COLOR`        | Disable ANSI colors                          |

## herdr integration

`pi-usage-herdr` maps the aggregates onto [herdr](https://github.com) workspaces
(Spaces panel) and panes (Agents panel) and reports them as sidebar metadata
tokens (`pi-usage --json` under the hood):

```
pi-usage-herdr             Report once and exit
pi-usage-herdr --watch 60  Report every 60 s (for live tokens)
pi-usage-herdr --dry-run   Only show what would be reported (send nothing)
pi-usage-herdr --ttl-ms 300000  Token TTL (default 5 min)
```

Add `$cost` / `$tokens` to your herdr `config.toml` rows:

```toml
[ui.sidebar.spaces]
rows = [["state_icon", "workspace"], ["branch", "git_status", "$cost", "$tokens"]]
[ui.sidebar.agents]
rows = [["state_icon", "workspace", "tab"], ["agent", "$cost", "$tokens"]]
```

## Tests

Stdlib-only `unittest`; generates synthetic JSONL sessions (no live data):

```
python3 -m unittest discover -s tests -v
```

## Layout

```
pi-usage/
├── bin/
│   ├── pi-usage          # main aggregator CLI
│   └── pi-usage-herdr    # herdr sidebar metadata reporter
├── tests/                # unittest suite
└── README.md
```

## License

MIT — see [LICENSE](LICENSE).

# pi-usage

Token & cost analytics for the [pi coding agent](https://github.com/earendil-works/pi): what you've
spent per **model, provider, project, day and session** — straight from the
session logs under `~/.pi/agent/sessions/`. Zero dependencies, no setup.
`-w` keeps the numbers live without eating your CPU, and an optional companion
mirrors them into the herdr sidebar.

Works with any Python ≥ 3.8 (stdlib only).

## Install

The scripts are plain executables. Put them somewhere on your `PATH`:

```sh
mkdir -p ~/.local/bin
ln -s "$(pwd)/bin/pi-usage"       ~/.local/bin/pi-usage
ln -s "$(pwd)/bin/pi-usage-herdr" ~/.local/bin/pi-usage-herdr
```

Done.

## Usage

```
pi-usage                # Overview: today + last 7 days + totals
pi-usage today          # Today, with a cost bar (input / output / cache)
pi-usage week           # Last 7 days, per day and per model
pi-usage stats          # Totals by model, provider and project
pi-usage sessions       # Per session, sorted by usage
pi-usage -w             # Live view: re-render every 5 s (Ctrl+C to stop)
pi-usage -w -n 10       # Live view with a custom interval
pi-usage --json         # Raw aggregates as JSON
pi-usage -s <dir>       # Use a different sessions directory
pi-usage --extended     # Show reasoning / cache tokens too
pi-usage --no-color     # No ANSI colors (NO_COLOR is honored too)
```

Repeated runs are cached, so the live view stays cheap even with a large
history; `--no-cache` forces a full re-parse. The cache is sharded per
project, so a change rewrites only that project's shard instead of the
whole history.

## herdr sidebar

`pi-usage-herdr` mirrors usage into [herdr](https://github.com) sidebars — cost
and tokens per workspace (Spaces panel) and per pane (Agents panel):

```
pi-usage-herdr             Report once and exit
pi-usage-herdr --watch 60  Keep reporting every 60 s (live tokens)
pi-usage-herdr --dry-run   Show what would be reported, send nothing
```

Then add the `$cost` / `$tokens` tokens to your herdr `config.toml` rows:

```toml
[ui.sidebar.spaces]
rows = [["state_icon", "workspace"], ["branch", "git_status", "$cost", "$tokens"]]
[ui.sidebar.agents]
rows = [["state_icon", "workspace", "tab"], ["agent", "$cost", "$tokens"]]
```

## Development

Stdlib-only `unittest` with synthetic sessions (no live data):

```
python3 -m unittest discover -s tests -v
```

## License

MIT — see [LICENSE](LICENSE).

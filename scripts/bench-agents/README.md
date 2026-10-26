# bench-agents — agent task matrix with hidden graders

Runs each model through real agent clients (OpenCode `--agent gentleman` and
Hermes `--oneshot`) on small but complete coding tasks, then scores the result
with graders the model never sees. Results of the 2026-10-25 run are in
`docs/BENCHMARKS.md` → *Agent task matrix (4 rounds)*.

| Task | What the model must do | Hidden checks |
|---|---|---|
| `semver` | Write `parse_semver()` plus its own tests | 10 |
| `bugfix` | Fix `inventario.py` without touching the provided tests (sha256-checked) | 7 |
| `extraccion` | Turn a (fake) lead email into a JSON file with fixed fields | 10 |
| `cli` | Small notes CLI (`add`, `list`, `search`) persisting to JSON | 7 |
| `refactor` | Split `reporte.py` into functions with docstrings; same output as the original | 6 |

Layout: `tareas.py` (task texts and fixture names), `fixtures/`, `graders/`
(`grade_<task>.py <workdir>` prints one JSON line), `bench_chat.py` (plain chat
latency through the router), `rondas.sh` (the runner).

## Running

The local AI has a single slot: hold the `ia-local` lock for the whole run so no
other agent uses it in between.

```bash
LOCK="${XDG_RUNTIME_DIR:-/tmp}/ia-local.lock"
exec 9>"$LOCK"; flock -w 600 9 || { echo busy; exit 3; }
OUT=~/bench-out ./rondas.sh
```

Requirements: `opencode` and `hermes` configured for the router (provider
`ia-local` / `venator`), `ssh venator-ts` access for server timings
(`journalctl` in LXC 103), `IA_API_KEY` in `~/.config/ia/secrets.env`.
Each run is capped at 900 s. Edit `MODELOS` and the round `case` in
`rondas.sh` to change the matrix.

Score the *hidden* grader, not the model's own tests: most own-test failures
in the 2026-10-25 run were wrong tests, not wrong code. A file written outside
the work dir scores 0 even when the code is correct.

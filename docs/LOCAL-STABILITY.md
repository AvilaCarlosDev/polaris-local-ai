# Local agent stability

Text models use a 65,536-token context, q8 K/V cache and one slot. Let llama.cpp
fit layers to available device memory instead of forcing every layer onto the GPU.
The router stops both image backends before text inference, and releases image
weights before resuming text after image generation. Disable image services at boot;
the router starts the selected image service on demand.

Client input plus output must fit the context. Configure custom OpenCode models
with context 65536 and output 8192; restrict enabled providers to the local provider so auxiliary requests cannot
fall back to cloud services. Leave small_model unset to follow the selected model. Hermes requires at least 64000 context tokens: keep 65536, use the
local provider directly and keep compression on the same model. Do not resume an
uncompacted 123K-token transcript against a 64K server; preserve the original
session and begin a fresh one with a short handoff.

Validation: pytest -q and ruff check ., followed by sequential API, Hermes and
OpenCode tool-call checks. Measure GPU memory under load; idle power management
can move allocations to GTT and is not proof of CPU-only inference.

Rollback: restore the timestamped copies of router.py, llama-server.service and
client configurations; daemon-reload and restart the router and llama-server.
Re-enable only image services that were enabled before this change.

## Verified on 2026-10-22

- 38 pytest checks passed; ruff, ShellCheck and Bash syntax checks passed.
- All six text/vision model IDs answered sequential text requests; Ornith was left loaded.
  This does not validate image input or agent tool quality on every model.
- OpenCode session `ses_e9aa14f93ffe3zb9dgvSOFxuoy` executed `pwd` and returned
  PRUEBA_LOCAL_OK using ia-local/ornith. First call read 27,984 tokens; next
  call reused 28,036 cached tokens and processed 28 new input tokens.
- Hermes session `20261022_165353_496416` executed `pwd` and returned
  HERMES_LOCAL_OK using the local API. Wall time was 134.4 seconds including
  initial prompt processing; this is not an instantaneous cold-start workflow.
- Runtime safety update: user Python and Hermes Python 3.14.9, uv 0.13.5;
  Hermes certifi 2026.10.19. Hermes runtime checks: 26 tests and 11 project checks.
- Venator host and CT 103 certificates updated to Debian 20250419+deb13u1.
  Ossus certificate packages updated to ca-certificates-mozilla 3.132-1 and
  python-certifi 2026.10.19-1. Distribution Python packages remain managed by
  their distribution; user commands use the patched interpreter through mise.

Server backup: `/opt/ia/backups/stability-20261022-164558` inside CT 103.
Client backup: `~/.local/state/polaris-repair/20261022-164323` on Ossus.
Hermes runtime backup: `~/.hermes/backups/runtime-security-20261022`.
Old KV caches were renamed with a `.pre-20261022-164558` suffix, not deleted.

Controlled forced compaction on synthetic data passed: 49 → 25 messages,
27,131 → 16,447 estimated transcript tokens, 252.6 seconds, one accepted
compression and no summary error. The test exercises the real local summarizer;
it is not a long-duration endurance test or proof of every automatic threshold path.

Start a new client session after this repair. Existing transcripts above the new
window were preserved and were not silently truncated or rewritten. Server-side
cache is temporary; conversation files and durable agent memory remain separate.


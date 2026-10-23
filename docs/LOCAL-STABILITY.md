# Local agent stability

Text models use a 65,536-token context, q8 K/V cache and one slot. Let llama.cpp
fit layers to available device memory instead of forcing every layer onto the GPU.
The router stops both image backends before text inference, and releases image
weights before resuming text after image generation. Disable image services at boot;
the router starts the selected image service on demand.

Client input plus output must fit the context. Configure custom OpenCode models
with context 65536 and output 8192. Keep built-in and cloud providers available:
do not set an `enabled_providers` allowlist to restrict OpenCode to local models.
Users can select any available provider/model; these limits apply only to the
custom local models. Leave `small_model` unset rather than pinning it to a local
model; OpenCode retains its normal auxiliary-model selection.
Hermes requires at least 64000 context tokens: keep 65536, use the
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

- 40 pytest checks passed; ruff, ShellCheck and Bash syntax checks passed.
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

## Slot contention — 2026-10-23

The stack was reported as "slower than before" while no longer stalling. The
server was healthy; one client was occupying the only slot.

Evidence from `journalctl -u llama-server` on CT 103, one request:

```
prompt eval time = 403184 ms / 52378 tokens  (129.92 tok/s)   ← 403 s prefill
        eval time =  19651 ms /    32 tokens  ( 16.28 tok/s)
      total time = 444660 ms / 52410 tokens  ( 16.70 tok/s)
```

With `--parallel 1` there is a single slot. A long-lived OpenCode session was
holding a ~52 K-token context, so **every** turn of every other client waited
behind a 400-second prefill, and each of those turns re-prefilled the whole
context again. The fix was closing that client — not touching the server:

| Check | Before | After closing the client |
|---|---:|---:|
| Short chat request, wall time | behind a 52 K prefill | **2.17 s** (300-token-class reply, 27.9 tok/s decode) |
| Clients connected to `:8090` | 1 long-lived session | none |

Hermes, measured the same day with `hermes -z … --usage-file`, shows the same
two states from the agent's side:

| Hermes turn | Input tokens | Cache read | Wall |
|---|---:|---:|---:|
| Cold (no matching prefix in cache) | 19,927 | 0 | **138.65 s** |
| Warm (immediately after, same prefix) | 4 | **19,923** | **16.86 s** |

Prefill of ~20 K tokens at ~150 tok/s is the cold cost; the warm turn is CLI
boot plus decode. This matches the 20,109-token agent measurement in
[BENCHMARKS.md](BENCHMARKS.md#latency-through-an-agent--what-you-actually-feel).

Operational rules that follow from the measurement:

- **One heavy client at a time.** Opencode and Hermes share the slot; whoever
  talks second pays a full prefill, because their prefix is not the cached one.
- A slow turn with `prompt_n` in the tens of thousands is occupancy, not
  hardware: read the `print_timing` line before changing anything.
- The Hermes client got request ceilings so a stalled stream fails instead of
  hanging (`providers.<id>.request_timeout_seconds: 900`,
  `stale_timeout_seconds: 300`) and no cloud failover
  (`fallback_providers: []`) — see [HERMES.md](HERMES.md).

Throughput itself was re-measured after the OS/kernel maintenance of both hosts
(kernel `7.0.14-25-pve`) and is unchanged or marginally better on all six
models — see the [post-maintenance comparison](RELEASE-COMPARISON.md#post-maintenance-comparison--2026-10-23).
Nothing in this incident was caused by the GPU link: the card sits on a PCIe
root port directly off the root complex (`0000:10:00.0` under `0000:00:01.1`),
and decode at 16.7–28.5 tok/s is consistent with that, not with a USB-attached
device.


## Publication regression checks

An HTTP-level test found that a healthy, already-selected model bypassed
`ensure()`. That skipped deferred KV restoration after image generation and
image-backend cleanup. Every text request now runs `ensure()` under the load lock.
The test failed before the fix and passes afterwards.

A second HTTP check reproduced a client timeout on load failure: the 503 body
was shorter than its declared Content-Length. The response now uses the shared
JSON writer, which computes its actual length. Both success and failure paths
are covered by the real HTTP test. Same-day performance and transition results
are recorded separately so historical numbers are not overwritten.

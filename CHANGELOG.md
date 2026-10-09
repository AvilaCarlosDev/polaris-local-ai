# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`docs/PORTABLE.md`** — the second machine, **Ossus** (Ryzen 5 PRO 4650U,
  22 GB, no discrete GPU), where a text-only llama.cpp runs in **normal RAM**
  (`n-gpu-layers = 0`, systemd user unit on port 8091). Measured against the
  Vega iGPU with `scripts/bench-portable.py`: CPU 12.3 / 6.6 tok/s vs iGPU
  14.8 / 8.1 tok/s on the 1.5 B and 3 B models — the iGPU's ~20% does not beat
  sharing the desktop's RAM, so the preset stays CPU. Raw rows in
  `docs/evidence/2026-10-08-ossus-portable.jsonl`. `docs/HARDWARE.md` now
  names the machine it describes (Venator) and links there.

- **`scripts/bench-slots.py`** — reproducible A/B of the KV slot cache: same
  model, same 19,648-token prompt, same restart, with and without the saved
  slot file. Re-measured on 2026-10-08 (n=3): a swap goes from **165.8 s to
  5.8 s** and image → chat from **167.8 s to 7.8 s**. Section and raw rows in
  `docs/BENCHMARKS.md` and `docs/evidence/`.
- **`scripts/bench-images.py`** — stable-diffusion.cpp vs ComfyUI with the
  same prompt, seed, size, steps and sampler. On the RX 580, sd.cpp + Vulkan
  is ~5× faster than ComfyUI, which can only use the CPU on Polaris (SD 1.5:
  26.3 vs 126.5 s; SD 3.5 Medium: 55.0 vs 277.1 s). On the CPU alone ComfyUI
  is the faster engine — documented too.
- `scripts/repro-agent-stall.py` reproduces the three router behaviours
  behind the agent stall on the CT; `tests/test_forward.py` covers them in CI
  with a fake upstream.
- `scripts/bench-summary.py` times an agent's compression summary with the
  reasoning unbounded, bounded (`reasoning_budget_tokens`) or off. With
  ornith, a 1024-token budget keeps the summary as detailed as unbounded and
  cuts it from 328–856 s to 197–266 s; thinking off is faster but uneven.
- `repro-agent-stall.py --only agent`: the eviction check shaped like a real
  agent turn (reply without its reasoning plus a new question). 104 tokens
  re-read after a side request on a 34K-token conversation.

### Fixed

- **Agent context compression no longer stalls for 300 s.** Diagnosed from
  the llama-server log of a real Hermes session (five 300 s stalls in one
  evening) and fixed in the router:
  - `forward_live()` streams responses as they arrive and cancels the
    upstream request when the client hangs up. Before, an abandoned request
    kept llama-server generating — and the router lock held — for **124 s**
    (plain) / **104 s** (SSE) after the client left; now **0.5 s**.
  - Requests without any output cap get `max_tokens: 16384`
    (`IA_DEFAULT_MAX_TOKENS`, 0 disables). Ornith had written 9,898 tokens
    into a summary Hermes sent uncapped. A first cut used 4096: in the
    end-to-end Hermes run the summary came back in 4 min 20 s but ornith had
    spent the whole cap reasoning, the reply ended in `finish_reason=length`
    and Hermes discarded it. Hermes asks for summaries of up to 10K tokens,
    so the floor is 16384; abandoned requests are cut by `forward_live()`.
  - Every model runs with `--parallel 1`. Four slots split the 64K KV cells,
    and a side request evicted the conversation: **55,260 tokens re-read in
    448 s**; with one slot, **4 tokens in 0.2 s**.
- `docs/HERMES.md`: `compression.threshold` is raised to 75% by Hermes for
  small windows; use `threshold_tokens` (36000 here), and keep it above the
  post-compaction size or it fires every turn.
- `docs/HERMES.md`: the summary's reasoning is bounded with
  `auxiliary.compression.extra_body.reasoning_budget_tokens: 1024`, and
  Engram is documented as a local MCP server (it no longer runs on the CT).

## [0.3.0] - 2026-10-06

### Added

- **KV slot cache across restarts** (`router.py`): `llama-server` now runs
  with `--slot-save-path /var/lib/llama-slots/`. The router dumps every slot
  to disk before stopping the server (model swap, or freeing VRAM for SD) and
  restores them when the same model loads again. Measured on real hardware
  with a 19,845-token prompt on the `qwen2.5-7b`: a swap used to cost
  **166.8 s** of prefill and now answers in **4.5 s**
  (`cached_tokens: 19,844`); the full image → chat path went from **167.9 s
  to 9.5 s**. A save writes the whole 577 MB file in 0.2–1.3 s and a restore
  takes 0.2 s. Cold requests are unchanged — there is nothing to restore —
  and the process restart itself (~6–10 s) still happens: what disappears is
  the huge prefill.

### Fixed

- **Saves can no longer clobber the cache.** llama-server writes a header
  file even when the slot holds no KV (`n_saved: 0`, 36 bytes), so a save
  against a freshly started server would destroy the good 577 MB file. Saves
  now go to a temp file and are promoted with `os.replace()` only when
  `n_saved > 0`, and restores skip stubs smaller than 4 KB.
- **The router's state file survives restarts.** `STATE` moved from
  `/run/llama-router/model` to `/var/lib/llama-router/model` and
  `router.service` dropped `RuntimeDirectory=`. After a deploy or a router
  crash, `current()` returned `""`: the router forced one unnecessary reload
  and — with the new cache — silently skipped the save, losing the warm KV
  without a log line. `SETUP`, `TROUBLESHOOTING` and `EXPECTATIONS` now
  document the persistent path.

## [0.2.0] - 2026-10-05

### Added

- **Category selector**: every id in `GET /v1/models` now carries a `category`
  (`texto`, `vision`, `multitarea`, `imagen`, `audio`) and the list is sorted by
  it, so a client can group the models instead of guessing from the ids.
  `models_payload()` is separated from the HTTP handler so the contract is
  testable in CI without systemd or a running server.
- **`clients/ia-models`**: CLI that prints the router's models grouped by
  category (`-c <category>`), marks the one currently loaded, and falls back to
  the same `IA_API` / `IA_SECRETS` / `IA_KEY` conventions as `ia-imagen`.
- **Whisper, packaged**: `systemd/whisper-server.service`, a CPU-only
  `build_whisper()` in `setup.sh` and docs in `SETUP.md` / `MODELS.md`. The
  audio category is advertised only when the weight exists — without
  `ggml-medium.bin` the installer skips both the build and the unit, instead
  of shipping a crash loop.
- **Harmony tests** (`tests/test_units.py`): the units and the installer may
  not drift apart. They check that every unit can be enabled, that its
  dependencies are services this repo ships, that every `/opt` path it uses is
  a directory `setup.sh` provisions, that the Python entrypoints are deployed,
  and that `setup.sh --check` parses and reports every unit — all without root,
  systemd or a GPU. CI also shellchecks `clients/ia-imagen` now.
- **README hero video**: `scripts/hero-demo.sh` drives a real run — models by
  category, a chat completion, an SD 3.5 image — recorded with asciinema.
  The release carries the MP4; `docs/media/hero-preview.webp` is the clickable
  preview (26 KB).
- **Local evidence log** (`docs/evidence/`): every hero artifact must be
  produced on our own hardware. The baseline records the GPU (Radeon RX 580
  8 GB), the ports of each service, live measurements of the router, llama and
  whisper, and the first title candidates generated by the local `qwen2.5-7b`
  — prompt, tokens and timing included.
- **Voxel hero video**: `scripts/hero-scene.py` + `scripts/hero-scene.sh` render
  and encode the 29 s **FLOATING ISLAND MIRAGE** diorama (870 frames, 1600x900
  → 1280x720) entirely on the CT: Pillow renders, ffmpeg encodes, no network.
  Title generated by the local `qwen2.5-7b`; preview in
  `docs/media/hero-scene-preview.webp`. CI shellchecks the new script.

### Fixed

- `sd-server-sd15.service` had no `[Install]` section, so
  `systemctl enable --now sd-server-sd15` failed silently: the unit ran until
  the next reboot and then stayed off.
- `setup.sh` never copied `router.py` / `image-mcp.py` into `/opt/ia`, so a
  clean install produced units pointing at files that did not exist. There is
  an explicit `Application` step for them now.
- The 0.1.0 changelog claimed units (image bridge, Tailscale exposure) that
  were never part of this repository.

### Changed

- `engram-proxy.service` moved to `systemd/optional/`: it hardcodes a LAN IP
  and requires `engram.service`, neither of which belongs to a portable
  install, so `setup.sh` no longer installs it.

## [0.1.0] - 2026-10-04

First public release: a complete local AI stack on an AMD Radeon RX 580 2048SP (8 GB VRAM) with 32 GB of RAM.

### Added

- **OpenAI-compatible router** (`router.py`): one endpoint for six text/vision model ids plus image generation, with aliases (`fast`, `general`, `ornith`, `imagen`, …), Bearer auth via `IA_API_KEY`, SSE streaming and on-demand model swapping. The swap is serialised under a process lock so concurrent clients queue instead of restarting `llama-server` on top of each other.
- **Image generation**: SD 3.5 Medium and SD 1.5 behind the same endpoint, with `image-mcp.py` as an MCP bridge for agents and `clients/ia-imagen` as a CLI that saves the result locally.
- **Install script** (`setup.sh`): checks GPU, Vulkan driver, RAM and disk before touching anything, builds what is missing and installs the systemd units. It refuses to run on hardware that cannot run the stack.
- **Systemd units** (`systemd/`): `llama-server`, `router`, `sd-server`, `sd-server-sd15` and `engram-proxy`, each with its own health and ordering rules.
- **Measured docs** (`docs/`): BENCHMARKS (cold vs warm, agent latency, all measured on real hardware), EXPECTATIONS, HARDWARE, MODELS, SETUP, TROUBLESHOOTING and HERMES (using the stack as an agent engine).
- **CI**: `ruff` for Python lint, `pytest` for router contract tests (model table, aliases, image ids, unit wiring) and `shellcheck` for `setup.sh`, running on pushes and pull requests.
- **README hero capture**: a real transcript — one `curl` chat completion and one `ia-imagen` generation — composited with the generated image.

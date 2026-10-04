# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-04

First public release: a complete local AI stack on an AMD Radeon RX 580 2048SP (8 GB VRAM) with 32 GB of RAM.

### Added

- **OpenAI-compatible router** (`router.py`): one endpoint for six text/vision model ids plus image generation, with aliases (`fast`, `general`, `ornith`, `imagen`, …), Bearer auth via `IA_API_KEY`, SSE streaming and on-demand model swapping. The swap is serialised under a process lock so concurrent clients queue instead of restarting `llama-server` on top of each other.
- **Image generation**: SD 3.5 Medium and SD 1.5 behind the same endpoint, with `image-mcp.py` as an MCP bridge for agents and `clients/ia-imagen` as a CLI that saves the result locally.
- **Install script** (`setup.sh`): checks GPU, Vulkan driver, RAM and disk before touching anything, builds what is missing and installs the systemd units. It refuses to run on hardware that cannot run the stack.
- **Systemd units** (`systemd/`): router, image bridge, Tailscale exposure and Whisper, each with its own health and ordering rules.
- **Measured docs** (`docs/`): BENCHMARKS (cold vs warm, agent latency, all measured on real hardware), EXPECTATIONS, HARDWARE, MODELS, SETUP, TROUBLESHOOTING and HERMES (using the stack as an agent engine).
- **CI**: `ruff` for Python lint, `pytest` for router contract tests (model table, aliases, image ids, unit wiring) and `shellcheck` for `setup.sh`, running on pushes and pull requests.
- **README hero capture**: a real transcript — one `curl` chat completion and one `ia-imagen` generation — composited with the generated image.

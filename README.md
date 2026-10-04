# polaris-local-ai

**A full local AI stack — text, vision and image generation — on an AMD Radeon
RX 580 2048SP (8 GB VRAM) with 32 GB of RAM.** No cloud, no API bills. It also
serves as the inference engine for an AI coding/assistant agent (Hermes Agent).

> **Inspired by [Strata](https://github.com/Niko1221/Strata).**
> Strata proved that a serious local inference stack can be packaged so a normal
> person can run it on a normal PC. This repository follows that same idea —
> one install script, an OpenAI-compatible API on localhost, docs with real
> numbers — but for older hardware and with a different engine. No Strata code
> is included. Credits to its author for the concept and the bar it set.
> See [LICENSE](LICENSE) for the full notice.

---

## Why this exists

Strata targets 12 GB+ cards from the RX 6800 series upward, and its AMD path
requires ROCm 7, which dropped the Polaris architecture years ago. An RX 580 —
still a very common card — is out of scope for it.

This stack does not care. It runs over **Vulkan through Mesa's RADV driver**,
which supports Polaris perfectly, and leans on **32 GB of system RAM** for the
models that do not fit in 8 GB of VRAM. The result: seven text/vision models
and two image models, all reachable through a single OpenAI-compatible endpoint.

## What you get

| | |
|---|---|
| **Text** | 6 models, from a 1.5 B coder up to a 30 B MoE, swapped on demand |
| **Vision** | Qwen2.5-VL 3 B with its mmproj projector |
| **Images** | SD 3.5 Medium and SD 1.5 through stable-diffusion.cpp |
| **API** | One OpenAI-compatible endpoint, one API key, 7 model ids |
| **Agent** | Works as the backend engine for Hermes Agent, with MCP tools |
| **Footprint** | Runs in a Debian LXC on a Proxmox host, or on bare metal |

Measured numbers, the install steps, the model guide and everything that broke
along the way are in [`docs/`](docs/):

- [HARDWARE.md](docs/HARDWARE.md) — what runs on this card and what cannot
- [BENCHMARKS.md](docs/BENCHMARKS.md) — tokens/second, measured
- [MODELS.md](docs/MODELS.md) — which model for which job
- [SETUP.md](docs/SETUP.md) — install from scratch
- [HERMES.md](docs/HERMES.md) — using it as an agent engine
- [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — the bugs we hit

## Quick start

```bash
./setup.sh
```

The script checks your GPU, Vulkan driver, RAM and disk, builds what is
missing, installs the systemd units and starts the router. It refuses to
proceed if your hardware cannot run the stack — see
[HARDWARE.md](docs/HARDWARE.md) for the exact requirements.

Then:

```bash
export IA_API_KEY=your-key
curl http://127.0.0.1:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IA_API_KEY" \
  -d '{"model":"qwen2.5-7b-instruct-q4_k_m",
       "messages":[{"role":"user","content":"Hello"}]}'
```

## Repository layout

```
router.py              OpenAI-compatible router: swaps models on demand
image-mcp.py           Image generation bridge
clients/ia-imagen      CLI to generate an image and save it locally
systemd/               The units that run the stack
docs/                  Hardware notes, benchmarks, setup, gotchas
setup.sh               One-shot installer
```

## Credits and licence

- **[Strata](https://github.com/Niko1221/Strata)** — MIT, by its author. The
  inspiration for this project's scope and packaging. Not a fork; no Strata
  source code is present here.
- **[llama.cpp](https://github.com/ggml-org/llama.cpp)** — the text and vision
  inference engine.
- **[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)** —
  the image engine.
- **[Qwen](https://qwen.ai/)**, **Ornith**, **ISTA-DASLab** — model families
  used here; each carries its own licence.

This repository is MIT-licensed. Model weights are **not** included and keep
their own licences.

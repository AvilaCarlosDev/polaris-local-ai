# Hardware

What this stack needs, what it runs on, and — just as important — what it
**cannot** do. Every claim here was checked on the machine it describes.

This page describes **Venator**, the homelab box (the RX 580 + Proxmox LXC).
The second machine, **Ossus** (a laptop with no discrete GPU), runs a
portable subset in normal RAM — see [PORTABLE.md](PORTABLE.md).

## The machine

| Component | Value |
|---|---|
| CPU | AMD Ryzen 5 5600G (Zen 3, 6 cores / 12 threads, AVX2) |
| RAM | 32 GB (2 × 16 GB) |
| GPU | AMD Radeon RX 580 2048SP — Polaris 20 (`gfx803`), **8 GB VRAM** |
| Display driver | Mesa RADV, Vulkan 1.4 |
| OS | Debian 13 (trixie), running as an LXC on Proxmox |
| Engine | llama.cpp 0.5.0-dev + stable-diffusion.cpp `master-929-3f8527a` |

The second GPU in the machine (the Ryzen's integrated Vega) is unused.

## Why Vulkan and not ROCm

This is the single decision the whole stack hangs on.

AMD's ROCm is the path most local-AI tooling assumes. It does not work here:

- ROCm dropped `gfx803` (Polaris) from official support in **ROCm 4.0**,
  December 2020.
- ROCm 7 actively **rejects** the architecture: Polaris uses legacy 32-bit MMIO
  doorbells (`DoorbellType 1`) and the runtime no longer handles them.
- Restoring it means patching and rebuilding ROCR-Runtime from source, and it
  still would not solve the problem below.

**Mesa's RADV Vulkan driver has full Polaris support.** Both engines here build
with `-DGGML_VULKAN=ON` and run directly against the card. No ROCm, no HIP, no
vendor SDK, no root-level driver install.

## The VRAM ceiling

8 GB is the binding constraint, and it shapes everything:

- llama.cpp decides on its own how many layers fit in VRAM. The rest stay in
  system RAM. **Do not force `-ngl 99` on the large models** — see
  [BENCHMARKS.md](BENCHMARKS.md) for what that costs.
- The models that live almost entirely in VRAM (the 1.5 B and 3 B ones) are the
  fast ones. The 18.6 GB MoE spills into RAM and is slower for it.
- Image generation gets a **6 GB budget** (`--max-vram 6`) so it does not fight
  the text model for memory.

32 GB of RAM is what makes the 30 B MoE usable at all.

## What this hardware can run

Verified working — see [BENCHMARKS.md](BENCHMARKS.md) for numbers:

- Text: 1.5 B, 3 B, 7 B, 9 B dense and 30 B MoE models
- Vision: Qwen2.5-VL 3 B with its mmproj projector
- Images: SD 3.5 Medium and SD 1.5, generated at 512×512

## What it cannot run

**[Strata](https://github.com/Niko1221/Strata) will not run on this card**, and
it is worth being precise about why, because it is three separate reasons, not
one:

| Requirement | Strata | This card | |
|---|---|---|---|
| GPU architecture | RDNA2/3/4 (`gfx1030`+) via HIP | Polaris `gfx803` | ✗ not in its allow-list |
| ROCm version | 7.0 minimum | `gfx803` dropped in 4.0 | ✗ rejected at runtime |
| VRAM | 12 GB minimum | 8 GB | ✗ under the floor |
| Model | Qwen3.8-Flash-Next, 66–83 GB download | — | ✗ 31 GB free disk |

Strata's `setup.py` carries a hard-coded list — `AMD_ARCHS = ("gfx1100",
"gfx1101", "gfx1200", "gfx1201", "gfx1030", "gfx1031")` — and its documentation
states plainly that other AMD architectures are not supported. Its engine also
only knows the Qwen3.8-Flash-Next family, so there is no path to point it at a
different model either.

None of that is a criticism of Strata. It targets modern cards on purpose, and
does it well. It simply is not the tool for Polaris, which is exactly the gap
this repository fills.

## Minimum requirements for this stack

| | |
|---|---|
| GPU | Any AMD card RADV supports (Polaris → RDNA4), 4 GB+ VRAM |
| CPU | x86-64 with AVX2 |
| RAM | 16 GB minimum; 32 GB recommended for the larger models |
| Disk | 40 GB for engines and models |
| OS | Debian/Ubuntu or anything with systemd, cmake, g++ and mesa-vulkan-drivers |

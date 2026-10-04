# Benchmarks

All numbers below were measured on the machine described in
[HARDWARE.md](HARDWARE.md): Ryzen 5 5600G, 32 GB RAM, Radeon RX 580 2048SP
(8 GB), Mesa RADV, Debian 13.

Nothing here is quoted from a vendor or another project.

## Method

**Text.** `POST /v1/chat/completions`, `temperature: 0`, `max_tokens: 300`,
a fixed ~250-word prompt, best of two runs.

> **tok/s = `completion_tokens` / total request time**, so it includes the
> prompt prefill. This is the honest end-to-end number a client sees. It is
> *not* pure decode speed and will read lower than a streaming decode-only
> measurement.

**Load** is the time of the *first* request to a model after another model was
in use: it includes the router restarting llama-server with the new weights.
Subsequent requests to the same model do not pay it.

**Images** are end-to-end wall time for a 512×512 PNG, from CLI invocation to
file on disk.

## Text models

| Model | tok/s | Generation | Load / swap |
|---|---:|---:|---:|
| `qwen2.5-coder-1.5b-instruct-q4_k_m` | **96.24** | 2.6 s | 6.7 s |
| `qwen2.5-vl-3b-instruct-q4_k_m` | **65.85** | 4.6 s | 10.7 s |
| `qwen2.5-7b-instruct-q4_k_m` | **33.82** | 8.9 s | 16.0 s |
| `qwen2.5-coder-7b-instruct-q4_k_m` | **33.40** | 8.4 s | 15.8 s |
| `ornith-1.5-9b-q4_k_m` | **27.31** | 11.0 s | 16.4 s |
| `qwen3-30b-a3b-instruct-2507-q4_k_m` | **21.77** | 13.8 s | 35.3 s |

What the table says:

- **The 1.5 B coder is the speed model.** 96 tok/s is well past the point where
  text appears faster than you can read it.
- **The 30 B MoE works, and 21.77 tok/s is usable**, but it is the slowest of
  the set. With 18.6 GB of weights against 8 GB of VRAM, most of it is being
  served from system RAM. That is the trade-off for running a 30 B model on
  this card at all — and 32 GB of RAM is what makes the trade possible.
- **Model swaps are the real latency.** Asking for a model nobody has used
  recently costs 7–35 s before a single token is produced. If a workflow needs
  to hop between models constantly, pin one.

## Why the large model must not be forced into VRAM

llama.cpp's default template pins `-ngl 99 --threads 4`. On the 18.6 GB MoE
that fills VRAM to roughly 99.4% and the card thrashes. Measured while tuning
the router:

| Configuration | tok/s |
|---|---:|
| `-ngl 99` (forced, VRAM 99.4% full) | **8.12** |
| default layer auto-fit (leaves ~1 GiB for the KV cache) | **22.26** |

Nearly a 3× difference. The router's `MODEL_ARGS` therefore sets **no `-ngl`
at all** for the MoE and lets llama.cpp decide. It also uses a 64 K context,
`q8_0` K/V cache and 6 threads.

Forcing `-ngl 99` is the single most common mistake on an 8 GB card.

## Image generation

| Model | Warm | With unit swap | Output |
|---|---:|---:|---|
| SD 1.5 (`sd15`) | **27.5 s** | 33.6 s | 512×512, 390 KB |
| SD 3.5 Medium (`imagen`) | **53.3 s** | 70.9 s | 512×512, 374 KB |

Both run through stable-diffusion.cpp on the same Vulkan device, with a 6 GB
VRAM budget.

The two models **share port 8082 and cannot run simultaneously** — the router
stops one and starts the other per request. That swap is the "with unit swap"
column. For repeated generation in one model, stay on it.

## Verified end-to-end

Beyond raw speed, the following was confirmed working in one session:

- All 6 text models answered correctly through the router (6/6).
- Both image models produced valid PNGs (2/2).
- An agent client (Hermes Agent) selected a model, invoked an MCP memory tool
  and returned a correct answer with no human intervention.

## Reproducing

```bash
# text
python3 - <<'PY'
import json, time, urllib.request
# ... see docs/SETUP.md for the endpoint and key
PY

# image
ia-imagen "your prompt" output-name
```

Re-run on your own hardware and add your numbers — a benchmark nobody can
reproduce is a marketing claim.

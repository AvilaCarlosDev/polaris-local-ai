# The portable stack — Ossus

This page is about the **second machine**: a laptop-class box
with no discrete GPU that runs a text-only subset of this stack. The main
stack — RX 580, image generation, the full feature set — lives on **Venator**
and is described in [HARDWARE.md](HARDWARE.md).

## The machine

| Component | Value |
|---|---|
| CPU | AMD Ryzen 5 PRO 4650U (Zen 2, 6 cores / 12 threads) |
| RAM | 22 GB shared |
| GPU | Radeon Vega integrated — **also drives the display** |
| Discrete GPU | none |
| OS | Omarchy (kernel 7.2.5) |
| Engine | llama.cpp build `b11514` (prebuilt binaries + `SHA256SUMS`) |

There is no RX 580 here and no ROCm. The whole point of this install is that
it must work **without a Vulkan device being usable for compute** — the model
runs in normal system RAM.

## What is installed

```
~/.local/share/polaris-portable/
├── llama-b11514/          # llama-server + libs, checksummed (SHA256SUMS)
├── models/                # two small GGUFs + checksums
├── models.ini             # preset file llama-server reads
└── test.log               # session log of a router-mode run

~/.config/systemd/user/polaris-portable.service   # the unit (systemd --user)
~/.config/polaris-portable/api-key                # Bearer key, mode 600
```

The unit runs llama-server directly in **router mode** — no `router.py`, no
`systemctl` root unit, no image engine:

```ini
ExecStart=%h/.local/share/polaris-portable/llama-b11514/llama-server \
  --host 127.0.0.1 --port 8091 \
  --models-preset %h/.local/share/polaris-portable/models.ini \
  --models-max 1 --api-key-file %h/.config/polaris-portable/api-key
```

- `--models-max 1`: one resident model at a time (22 GB of shared RAM), so
  swapping models costs a reload — same trade-off as the main stack.
- `--port 8091`: the portable stack never collides with Venator's 8090.
- Presets: `qwen2.5-coder-1.5b-instruct-q4_k_m` and
  `qwen2.5-vl-3b-instruct-q4_k_m`. No `ornith-1.5-9b`, no SD — those are
  Venator's job (ornith decodes at 28 tok/s there; see
  [BENCHMARKS.md](BENCHMARKS.md)).

## RAM normal, not the integrated GPU

`models.ini` runs with `n-gpu-layers = 0`: **CPU decode from system RAM**.
The Vega iGPU shares that same 22 GB and is what draws the desktop, so
offloading to it competes with the display — and it is not faster by enough
to matter:

| Model | **RAM normal (CPU, 6 threads)** | Vega iGPU (`n-gpu-layers 99`) |
|---|---:|---:|
| `qwen2.5-coder-1.5b-instruct-q4_k_m` | **12.3 tok/s** | 14.8 tok/s |
| `qwen2.5-vl-3b-instruct-q4_k_m` | **6.6 tok/s** | 8.1 tok/s |

Warm medians, n=3, same prompt and `max_tokens`. The iGPU leads by ~20%, but
it pays for that out of the same RAM the desktop uses. The measured rows
(both configurations) are in
[`evidence/2026-10-08-ossus-portable.jsonl`](evidence/2026-10-08-ossus-portable.jsonl).

Reproduce — first with `n-gpu-layers = 99`, then with `0`, restarting
between runs:

```bash
systemctl --user restart polaris-portable
python3 scripts/bench-portable.py cpu-ram-normal \
    qwen2.5-coder-1.5b-instruct-q4_k_m qwen2.5-vl-3b-instruct-q4_k_m
```

The label goes into the JSONL rows, so both configurations can share one
evidence file.

## What to expect

- A 1.5 B model answering a short prompt in ~7 s wall; a 3 B vision model in
  ~18 s. Fine for quick local calls, not for Venator-sized work.
- `sleep-idle-seconds = 900`: the server releases its memory after 15 idle
  minutes, so an unused laptop is not holding a model in RAM.
- Context stays at 64 K with a `q8_0` KV cache — same recipe as Venator, so
  agent configs behave identically against either endpoint.

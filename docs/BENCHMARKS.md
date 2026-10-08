# Benchmarks

All numbers below were measured on the machine described in
[HARDWARE.md](HARDWARE.md): Ryzen 5 5600G, 32 GB RAM, Radeon RX 580 2048SP
(8 GB), Mesa RADV, Debian 13.

Nothing here is quoted from a vendor or another project.

> **Just trying it out?** Read [EXPECTATIONS.md](EXPECTATIONS.md) first — it
> turns these tables into plain expectations for your first hour of use.

## Method

**Text.** `POST /v1/chat/completions`, `temperature: 0`, `max_tokens: 300`,
one fixed prompt (~60 tokens in, ≈300 tokens generated).

Every model is measured in **two states**, with an identical request in each:

- **Cold** — first request after a different model was in use. The router
  restarts llama-server with the new weights, so wall time includes the swap.
- **Warm** — the same request while the model is still resident.

`tok/s` is decode throughput from llama-server's own `print_timing` —
generation only. Wall time additionally includes prompt pre-fill, the model
swap and network.

> These are **raw API** numbers, not what a person experiences through an
> agent — see
> [Latency through an agent](#latency-through-an-agent-what-you-actually-feel),
> where the prompt is 20,109 tokens.

**Agent end-to-end.** `hermes chat -Q -m <model> -q "..."`, wall clock from
process start to final line. This measures the whole chain: Hermes CLI boot,
prompt assembly, router, model and reply.

**Images** are end-to-end wall time for a 512×512 PNG, from CLI invocation to
file on disk.

## Text models

Measured with the cold/warm method below: **warm** is a request while the model
is already resident, **cold** is the same request right after a swap.

| Model | tok/s | Warm (loaded) | Cold (after swap) | Swap cost |
|---|---:|---:|---:|---:|
| `qwen2.5-coder-1.5b-instruct-q4_k_m` | **99.2** | **3.1 s** | 11.0 s | 7.9 s |
| `qwen2.5-vl-3b-instruct-q4_k_m` | **66.4** | **4.4 s** | 14.9 s | 10.2 s |
| `qwen2.5-7b-instruct-q4_k_m` | **34.2** | **8.8 s** | 24.3 s | 15.2 s |
| `qwen2.5-coder-7b-instruct-q4_k_m` | **34.3** | **8.8 s** | 24.4 s | 15.4 s |
| `ornith-1.5-9b-q4_k_m` | **28.0** | **10.9 s** | 26.3 s | 15.2 s |
| `qwen3-30b-a3b-instruct-2507-q4_k_m` | **21.3** | **14.1 s** | 55.0 s | 38.5 s |

What the table says:

- **The 1.5 B coder is the speed model.** 99 tok/s is well past the point where
  text appears faster than you can read it — 300 tokens in 3.1 s.
- **The 30 B MoE works, and 21.3 tok/s is usable**, but it is the slowest of
  the set. With 18.6 GB of weights against 8 GB of VRAM, most of it is being
  served from system RAM. That is the trade-off for running a 30 B model on
  this card at all — and 32 GB of RAM is what makes the trade possible. Its
  **38.5 s swap is also the worst in the set**; pin it if you use it often.
- **Swapping costs 7.9–38.5 s, i.e. it doubles or triples the answer time.**
  If a workflow hops between models constantly, it pays that on every hop.
- **None of this is the agent's bottleneck.** Through Hermes the first message
  costs ~161 s because of a 20 K-token prompt, and later turns still cost
  ~21–25 s of fixed CLI overhead. See
  [Latency through an agent](#latency-through-an-agent-what-you-actually-feel).

## Cold vs warm — the same model, two states

The table above mixes two different situations, so here is how each number was
produced. For every model: one request **immediately after a swap**, then an
**identical** request while it was still resident. Same prompt,
`temperature: 0`, `max_tokens: 300` (≈300 tokens generated in both cases).

Decomposition of one row (`qwen2.5-7b`) — the pattern holds for all six:

```
COLD    wall 24.3s = swap 15.2s + prefill 0.36s (63 tok) + decode 8.72s (300 tok @ 34.3 tps)
WARM    wall  8.8s = swap  0.0s + prefill 0.04s ( 1 tok) + decode 8.73s (300 tok @ 34.2 tps)
```

Three facts fall out of this:

1. **The swap is the entire difference.** Every row's cold/warm gap equals the
   swap cost to within a few tenths of a second. Each cold run logged
   `llama_server: model loaded`; each warm run did not.
2. **Generation speed is identical in both states** — 99.1 vs 99.2, 65.8 vs
   66.4, 34.3 vs 34.3 tok/s. A cold model is not slower to generate; it is slow
   to *arrive*.
3. **The KV cache does its job.** Warm prefill drops from 42–63 tokens to
   **1 token** (4 for `ornith`), i.e. the prompt prefix is fully reused. Only
   the new input is evaluated.

Practical consequence: **a model that is already loaded answers 2.4–3.9×
faster than the same model after a swap** (11.0 → 3.1 s for the 1.5 B coder,
55.0 → 14.1 s for the MoE). Stay on one model per session.

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

## Why stable-diffusion.cpp and not ComfyUI

Asked on r/ROCm. The short answer is the backend, not the engine: ComfyUI runs
on PyTorch, PyTorch has no Vulkan backend, and ROCm does not support Polaris
(this CT does not even have `/dev/kfd`). On this card ComfyUI can only use the
CPU. stable-diffusion.cpp is built on ggml, which has a Vulkan backend, so it
runs on the RX 580 through RADV.

**Method.** `scripts/bench-images.py`, stack stopped, same prompt and seed,
512×512, 20 steps, `euler`, CFG 7 (SD 1.5) / 4.5 (SD 3.5). sd.cpp runs
`sd-cli` once per image, so every sd.cpp number is a **cold** start. ComfyUI
(commit `d91ed5f`, PyTorch 2.14.1+cpu) is started once with `--cpu`; its first
image is cold and the rest are warm. Weights: the Comfy-Org checkpoints for
ComfyUI; for sd.cpp both the production GGUFs and, for SD 1.5, the *same*
fp16 safetensors ComfyUI loads.

| Model | Engine | Device | Weights | Wall per image | Peak RAM |
|---|---|---|---|---:|---:|
| SD 1.5 | **sd.cpp** | **RX 580 (Vulkan)** | Q5_1 GGUF | **26.2 – 26.3 s** (cold) | 0.3 GB |
| SD 1.5 | sd.cpp | RX 580 (Vulkan) | fp16 safetensors | 27.1 – 29.2 s (cold) | 0.3 GB |
| SD 1.5 | ComfyUI | CPU, 6 threads | fp16 safetensors | 126.5 – 126.7 s warm, 139.8 s cold | 6.6 GB |
| SD 1.5 | sd.cpp | CPU, 6 threads | fp16 safetensors | 321.7 – 322.5 s (cold) | 3.7 GB |
| SD 3.5 Medium | **sd.cpp** | **RX 580 (Vulkan)** | Q5_1 + Q4_0 encoders | **55.0 – 67.1 s** (cold) | 1.5 GB |
| SD 3.5 Medium | ComfyUI | CPU, 6 threads | fp8 all-in-one | 277.1 s warm, 313.7 s cold | 23.9 GB |
| SD 3.5 Medium | sd.cpp | CPU, 6 threads | Q5_1 + Q4_0 encoders | 816.5 s (cold, n=1) | 7.5 GB |

What it says:

- **On this card sd.cpp + Vulkan is ~5× faster than ComfyUI**, and that is
  comparing sd.cpp *cold* with ComfyUI *warm*: 26.3 vs 126.5 s on SD 1.5,
  55.0 vs 277.1 s on SD 3.5.
- **It is not that sd.cpp is a faster engine.** On the CPU, ComfyUI wins
  clearly — 126.5 vs 321.7 s on SD 1.5, 277 vs 817 s on SD 3.5. PyTorch's CPU
  kernels are better than ggml's. The advantage is that sd.cpp can use the GPU
  at all.
- **Quantisation is not the trick either.** The same fp16 weights ComfyUI
  loads run in 27–29 s on Vulkan, 1–3 s behind the Q5_1 GGUF.
- **Memory decides whether it fits next to the LLMs.** ComfyUI on the CPU
  computes in fp32: SD 3.5 peaked at 23.9 GB of RAM in a 24 GB CT. sd.cpp
  keeps the weights in VRAM and stays at 1.5 GB of RAM, which is what lets
  the router run SD and a 30 B MoE on the same box.
- **What ComfyUI gives that sd.cpp does not:** the node graph, a huge
  custom-node ecosystem and faster support for new models. On a card with
  working ROCm or CUDA that is the better tool. On Polaris it is a 5× tax.

Raw rows: [`evidence/2026-10-08-sdcpp-vs-comfyui.jsonl`](evidence/2026-10-08-sdcpp-vs-comfyui.jsonl).

## Latency through an agent — what you actually feel

The tables above measure the **API**. Nobody talks to an API directly: an agent
client wraps every call in its own prompt, tools and process. Measured with
Hermes Agent on this machine, there are three layers, and only the first one is
what the previous tables show.

| Layer | Prompt size | Model time | Wall time |
|---|---:|---:|---:|
| **1. Raw API, warm** (curl, model resident) | ~60 tok | 3.0 – 14.1 s | **3.1 – 14.1 s** |
| **2. First message in an agent session** | **20,109 tok** | **~126 s** | **161.3 s** |
| **3. Later turns, same model (cached)** | 25 – 71 tok | **3.7 – 4.8 s** | **21 – 25 s** |

Row 3's *model* time is lower than row 1's only because those replies were
46–60 tokens rather than 300 — the point of the table is the **wall** column:
the agent's model does *less* work than a raw API call and still takes longer,
because prefill and CLI overhead dominate.

### Why the first message costs two minutes

Hermes sends its full system prompt on every call:

```
stable (identity/guidance/skills) :  9,018 B
Tool schemas                     : 46,828 B  (27 tools)
                                   ─────────
                                   ≈ 55 KB ≈ 20,100 tokens
```

Measured on `ornith-1.5-9b`, first turn of a session:

```
prompt eval time = 123,566 ms / 20,109 tokens  (162.74 tok/s)   ← 123.6 s
        eval time =   2,506 ms /     57 tokens  ( 22.34 tok/s)   ←   2.5 s
```

The model answers in 2.5 seconds. It takes **124 seconds to read the question**.
Add a cold model swap (15.2 s measured for `ornith`) and Hermes CLI boot
(11.7 s) and the session opens at **161 s**.

### Prompt caching makes turns 2+ cheap

llama.cpp reuses the KV cache for the shared prefix. Same session, same model,
measured over three consecutive turns:

| Turn | Prompt eval | Decode | Model total | Wall |
|---|---:|---:|---:|---:|
| 1 (cold) | 123.6 s / 20,109 tok | 2.5 s / 57 tok | **126.1 s** | **161.3 s** |
| 2 (cached) | **1.7 s / 25 tok** | 2.0 s / 46 tok | **3.7 s** | **23.4 s** |
| 3 (cached) | **2.2 s / 71 tok** | 2.6 s / 60 tok | **4.8 s** | **24.6 s** |

Turn 2 re-reads **25 tokens instead of 20,109** — a 495× reduction in prefill.
Caching works; the cold-start cost is paid once per session.

### The agent itself costs ~17–20 s per turn

Cache hit or not, wall time never drops below ~21 s. Attribution measured:

- `hermes doctor` (no model call at all): **11.7 s** — pure CLI/process boot.
- Trivial `hermes chat -Q -q "hola"` with a warm cache: **21.5 s** wall for
  ~4 s of model work.

Hermes relaunches its process, spawns MCP servers and writes session state on
**every invocation**. That fixed cost, not the model, sets the floor for
interactive use.

### Six models, each once, through the agent

Each row is a different model, so every row is a cold start (swap + 20 K
prefill), not a warm turn:

| Model requested | Wall | Router actually loaded | Answer |
|---|---:|---|---|
| `qwen2.5-vl-3b-instruct-q4_k_m` | 35.4 s | ✓ correct | correct |
| `qwen2.5-coder-1.5b-instruct-q4_k_m` | 77.3 s | ✓ correct | **wrong** ("Tashkent") |
| `ornith-1.5-9b-q4_k_m` | 144.2 s | ✓ correct | correct |
| `qwen2.5-coder-7b-instruct-q4_k_m` | 202.4 s | ✓ correct | **tool-call JSON, not prose** |
| `qwen2.5-7b-instruct-q4_k_m` | 203.2 s | ✓ correct | correct |
| `qwen3-30b-a3b-instruct-2507-q4_k_m` | 339.9 s | ✓ correct | correct |

**Routing was 6/6 correct** — the router served exactly the model requested
every time. **Content was 4/6**: the two failures are small coder models asked
a factual question under a 27-tool agent prompt. They are not routing bugs,
they are what a 1.5 B coder does with general knowledge. Pick a model for the
job, not for the speed column — see [MODELS.md](MODELS.md).

## KV cache across restarts — slot save/restore A/B

Prompt caching only lives as long as the llama-server process. Every model
swap restarts it, and so does every image generation (SD needs the VRAM).
Since 0.3.0 the router runs llama-server with `--slot-save-path`, dumps each
slot to disk right before the stop and restores it once the same model is
healthy again. Suggested by a reader on r/ROCm; this is the measurement.

**Method.** `scripts/bench-slots.py`, run on the CT against the router.
Same model (`qwen2.5-7b-instruct-q4_k_m`), same 19,648-token prompt (the
repo's own docs plus `router.py`), `temperature: 0`, `max_tokens: 32`. Both
arms go through the *same* restart; the only difference is whether the saved
slot file is deleted before the model comes back. 3 repetitions per cell.

| Path | Slot file | Wall (median, n=3) | Range | Prefilled | Cached |
|---|---|---:|---:|---:|---:|
| swap away → back + request | deleted | 165.8 s | 165.7 – 167.1 s | 19,648 tok | 0 |
| swap away → back + request | **kept** | **5.8 s** | 5.8 – 7.4 s | **1 tok** | 19,647 |
| image (SD 1.5) → chat | deleted | 167.8 s | 167.6 – 167.8 s | 19,648 tok | 0 |
| image (SD 1.5) → chat | **kept** | **7.8 s** | 7.8 – 7.9 s | **1 tok** | 19,647 |

- **28× on a swap, 21× after an image.** What disappears is the prefill:
  160.0 s at ~123 tok/s in every "deleted" run, 0.06 s in every "kept" run.
- **Save and restore are not the cost.** 19,679 tokens → a 572 MB file,
  0.2 s to save and 0.2 s to restore (router log). The rest of the 5.8 s is
  the process restart and 1.4–2.0 s of decode.
- **The first request of a model is unchanged** — 178.7 s here, there is
  nothing on disk yet. The cache pays off from the second visit on.
- **Same model only.** llama-server validates the file against the loaded
  model and context, so the router keys files by model id
  (`<model>-<slot>.bin`). Each warm model costs ~0.6 GB of disk.

Raw rows: [`evidence/2026-10-08-slot-ab.jsonl`](evidence/2026-10-08-slot-ab.jsonl).
Reproduce on your own box (needs root: the "deleted" arm removes files in
`/var/lib/llama-slots/`):

```bash
sudo python3 scripts/bench-slots.py --corpus docs/*.md router.py setup.sh \
  --chars 64500 --reps 3
```

## Verified end-to-end

Confirmed working in one session:

- All 6 text models answered correctly **through the router** (6/6, direct API).
- Both image models produced valid PNGs (2/2).
- The agent selected each requested model correctly (6/6 routing).
- An agent client selected a model, invoked an MCP memory tool and returned a
  correct answer with no human intervention.
- Model swaps happen automatically under the agent — no config edit needed.

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

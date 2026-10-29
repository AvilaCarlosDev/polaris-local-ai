# Models

Five text/vision models (seven ids) and two image models, all behind one endpoint. The
router picks whichever `model` id you send and swaps the engine if needed.

## Categories

Every id carries one of five categories, and `ia-models` prints them grouped:

```bash
ia-models                # everything
ia-models -c multitarea  # one category
```

| Category | Ids |
|---|---|
| `texto` | coder 1.5 B, ornith 9 B, ornith 9 B `-nothink` |
| `vision` | Qwen2.5-VL 3 B |
| `multitarea` | Ornith 1.5 35B-A3B, Qwen3.6-35B-A3B, Qwen3.6 `-ngram` |
| `imagen` | `sd35` (`imagen` alias), `sd15` |
| `audio` | `whisper-medium` — only listed when whisper is installed |

`GET /v1/models` is the source of truth: the category comes from the endpoint,
not from a table in this file, so scripts and the CLI always agree with what
the router is actually running.

## Text and vision

| Id | Size | Type | Best for |
|---|---|---|---|
| `qwen2.5-coder-1.5b-instruct-q4_k_m` | 1.5 B | dense | speed: autocomplete, short rewrites, classification |
| `qwen2.5-vl-3b-instruct-q4_k_m` | 3 B | dense + vision | reading images and screenshots |
| `ornith-1.5-9b-q4_k_m` | 9 B | hybrid (`qwen35`), reasons | general assistant use; Hermes' default |
| `ornith-1.5-9b-nothink` | 9 B | same GGUF, `--reasoning-budget 0` | direct answers; fine in OpenCode, loses points in Hermes |
| `qwen3.6-35b-a3b-ud-iq4_xs` | 35 B | **MoE (3 B active)**, no reasoning | fast agent work and long prompts |
| `qwen3.6-35b-a3b-ud-iq4_xs-ngram` | 35 B | same + `ngram-mod` speculative decoding | editing existing files (17.0 → 27.4 tok/s) |
| `ornith-1.5-35b-a3b-ad-iq4_xs` | 35 B | **MoE (3 B active)**, reasons | best agent score (39/40); OpenCode's default |

Aliases accepted by the router: `fast` → coder 1.5 B, `code` → Qwen3.6,
`general` → ornith 9 B, `vision` → VL 3 B, `ornith` → ornith 9 B. `code` and
`general` used to point at the Qwen2.5 7 B models, removed on 2026-10-26; the
names stay so old clients keep working.

### Picking one

- **Agent work (OpenCode):** `ornith-1.5-35b-a3b-ad-iq4_xs`. 39/40 in the
  hidden-grader task matrix in both OpenCode and Hermes. It reasons, so a short
  chat takes ~39 s.
- **Agent work, faster:** `qwen3.6-35b-a3b-ud-iq4_xs`. 38/40, no reasoning,
  short chat 7.6 s, prefill ~240 tok/s. Use the `-ngram` id when the agent
  mostly edits files.
- **Hermes / everyday assistant:** `ornith-1.5-9b-q4_k_m`. Fits entirely on
  the GPU; 37/40 in Hermes. Keep reasoning on for Hermes.
- **Need it now:** `qwen2.5-coder-1.5b`. At ~96 tok/s it feels instant.
- **Looking at an image:** `qwen2.5-vl-3b`. The only model that accepts images;
  it needs the mmproj projector loaded alongside it.

Numbers and raw rows: [BENCHMARKS.md](BENCHMARKS.md) → *Agent task matrix* and
*Ornith 1.5 35B-A3B in the agent matrix*.

### The MoE, in one paragraph

A mixture-of-experts model stores many small "expert" sub-networks and routes
each token through only a few of them. Qwen3.6-35B-A3B and Ornith 1.5 35B-A3B
carry 35 B parameters total but activate about 3 B per token — the quality of a
large model at close to the compute cost of a small one. The catch on an 8 GB
card is memory: ~16.5 GB of weights. The router keeps attention and part of the
experts on the GPU (`-ngl 99 --n-cpu-moe 30`, ~7.2–7.4 GB VRAM at a 64 K
context) and the rest of the experts in the 32 GB of system RAM. Both are hybrid
linear-attention models, so the KV cache stays small and long prompts hold up.

## Image models

| Id | Engine | Notes |
|---|---|---|
| `imagen` (a.k.a. `sd35`) | SD 3.5 Medium | default; better prompt adherence, slower |
| `sd15` | SD 1.5 | faster, benefits from a negative prompt |

They **share port 8082** and cannot run at once. The router starts the requested
backend on demand and unloads it before text resumes, so every image request pays
the backend load (SD 1.5 ≈ 34 s, SD 3.5 ≈ 72 s per 512×512 image including load,
measured in [RELEASE-COMPARISON.md](RELEASE-COMPARISON.md)).

Generate from the CLI:

```bash
ia-imagen "a red fox figurine, studio lighting" my-fox        # SD 3.5
ia-imagen -m sd15 "a red fox figurine, studio lighting" my-fox  # SD 1.5
```

Files land in `~/Imagens-IA/` and are also served from
`http://<host>:8090/img/<name>.png`.

## Audio (optional)

Whisper does **not** go through the router — it is a separate service on its
own port, and the router only advertises it when that service is installed:

| | |
|---|---|
| Id | `whisper-medium` |
| Endpoint | `http://<host>:8081/inference` |
| Category | `audio` |

The path is `/inference`, not the OpenAI-style `/v1/audio/transcriptions` —
that one returns 404. See [SETUP.md](SETUP.md) for the service itself.

## Getting the weights

Weights are **not** in this repository. Point `MODELS_DIR` in `setup.sh` at
your gguf files, or download from the projects that publish them:

| Model | Origin |
|---|---|
| Qwen2.5 Coder 1.5 B, Qwen2.5-VL 3 B | [Qwen](https://github.com/QwenLM) / GGUF conversions |
| Qwen3.6-35B-A3B (`UD-IQ4_XS`) | [Qwen](https://github.com/QwenLM), GGUF by unsloth |
| Ornith 1.5 9 B | its upstream publisher |
| Ornith 1.5 35B-A3B (`AD-IQ4_XS-IQ3_S`) | its upstream publisher, GGUF by AtomicChat |
| SD 3.5 Medium / SD 1.5 | [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) compatible GGUF |

Each model carries its own licence. Check it before you redistribute.

## Model files on disk

```
/opt/ia/models/                              /var/cache/ai/models/
  qwen2.5-vl-3b-instruct-q4_k_m.gguf 1.8G     Ornith-1.5-9B-Q4_K_M.gguf                5.4G
  qwen2.5-coder-1.5b-…gguf           1.1G     Qwen3.6-35B-A3B-UD-IQ4_XS.gguf          16.5G
  mmproj-Qwen2.5-VL-3B-…gguf         806M     Ornith-1.5-35B-A3B-AD-IQ4_XS-IQ3_S.gguf 16.4G
  sd15-Q5_1.gguf                     1.6G
  sd3.5_medium-Q5_1.gguf             2.4G
  t5xxl-Q4_0.gguf                    2.6G
  clip_g-Q4_0.gguf / clip_l-Q4_0.gguf 374M / 67M
```

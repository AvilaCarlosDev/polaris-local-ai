# Models

Six text/vision models and two image models, all behind one endpoint. The
router picks whichever `model` id you send and swaps the engine if needed.

## Categories

Every id carries one of five categories, and `ia-models` prints them grouped:

```bash
ia-models                # everything
ia-models -c multitarea  # one category
```

| Category | Ids |
|---|---|
| `texto` | coder 1.5 B, 7 B, coder 7 B, ornith 9 B |
| `vision` | Qwen2.5-VL 3 B |
| `multitarea` | Qwen3-30B-A3B |
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
| `qwen2.5-7b-instruct-q4_k_m` | 7 B | dense | general chat, summaries, everyday Q&A |
| `qwen2.5-coder-7b-instruct-q4_k_m` | 7 B | dense | code generation and review |
| `ornith-1.5-9b-q4_k_m` | 9 B | dense | general assistant use — the default |
| `qwen3-30b-a3b-instruct-2507-q4_k_m` | 30 B | **MoE (3 B active)** | hardest questions, long reasoning, agentic work |

Aliases accepted by the router: `fast` → coder 1.5 B, `code` → coder 7 B,
`general` → 7 B, `vision` → VL 3 B, `ornith` → ornith 9 B.

### Picking one

- **Default:** `ornith-1.5-9b-q4_k_m`. Balanced, fast enough, and it is what
  the agent is configured to use.
- **Need it now:** `qwen2.5-coder-1.5b`. At ~96 tok/s it feels instant.
- **Looking at an image:** `qwen2.5-vl-3b`. The only model that accepts images;
  it needs the mmproj projector loaded alongside it.
- **Writing code for real:** `qwen2.5-coder-7b`.
- **Stuck on something hard:** `qwen3-30b-a3b`. The MoE activates only ~3 B
  parameters per token, so it reasons like a much larger model without paying
  the full cost — but on this card most weights live in RAM, so expect ~22
  tok/s and a ~35 s swap the first time.

### The MoE, in one paragraph

A mixture-of-experts model stores many small "expert" sub-networks and routes
each token through only a few of them. Qwen3-30B-A3B carries 30 B parameters
total but activates about 3 B per token — the reasoning quality of a large
model at close to the compute cost of a small one. The catch on an 8 GB card
is memory, not compute: 18.6 GB of weights have to sit somewhere, and the
somewhere is your 32 GB of system RAM.

## Image models

| Id | Engine | Notes |
|---|---|---|
| `imagen` (a.k.a. `sd35`) | SD 3.5 Medium | default; better prompt adherence, slower |
| `sd15` | SD 1.5 | faster, benefits from a negative prompt |

They **share port 8082** and cannot run at once. The router switches between
them automatically; the switch costs ~5–17 s.

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
| Qwen 2.5 family (7 B, coder, VL) | [Qwen](https://github.com/QwenLM) / GGUF conversions |
| Qwen3-30B-A3B-Instruct | [Qwen](https://github.com/QwenLM) |
| Ornith 1.5 9 B | its upstream publisher |
| SD 3.5 Medium / SD 1.5 | [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) compatible GGUF |

Each model carries its own licence. Check it before you redistribute.

## Model files on disk

```
/opt/ia/models/                              /var/cache/ai/models/
  qwen2.5-7b-instruct-q4_k_m.gguf    4.4G     Ornith-1.5-9B-Q4_K_M.gguf      5.4G
  qwen2.5-coder-7b-instruct-…gguf    4.4G     Qwen_Qwen3-30B-A3B-…gguf      18G
  qwen2.5-vl-3b-instruct-q4_k_m.gguf 1.8G
  qwen2.5-coder-1.5b-…gguf           1.1G
  mmproj-Qwen2.5-VL-3B-…gguf         806M
  sd15-Q5_1.gguf                     1.6G
  sd3.5_medium-Q5_1.gguf             2.4G
  t5xxl-Q4_0.gguf                    2.6G
  clip_g-Q4_0.gguf / clip_l-Q4_0.gguf 374M / 67M
```

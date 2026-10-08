# Troubleshooting

Everything here is a bug we actually hit, with the root cause. The numbers and
log lines are from the machine in [HARDWARE.md](HARDWARE.md).

## Generated images come out completely blank

**Symptom.** A valid PNG is returned and saved, but it is pure white — a few KB,
one colour, `identify` reports `Colors: 1`. The *second* request to the same
model works fine.

**Cause.** Lazy weight loading racing the first generation.

`sd-server` bound port 8082 and answered `/` **before** its tensors were in
memory, and the router only ever waited for the TCP socket:

```python
def sd_up():
    with socket.create_connection(("127.0.0.1", 8082), timeout=5):
        return True
```

So the sequence on a cold start was:

```
16:42:45  listening on http://127.0.0.1:8082   ← router sees the port, fires
16:42:45  generate_image 512x512               ← sampling starts immediately
16:43:05  loading tensors completed, 6.66s     ← weights arrive mid-sampling
16:43:57  generate_image completed             → white image
```

SD 1.5 never showed it because it is small enough to load before sampling
reaches it. SD 3.5 Medium (2.4 GB model + 2.6 GB T5) is not.

**Fix.** Add `--eager-load` to the `ExecStart` of `sd-server.service`:

```
ExecStart=/opt/stable-diffusion.cpp/build/bin/sd-server \
  … \
  --max-vram 6 \
  --eager-load
```

The flag already exists in the binary: *"load all params into the params
backend at model-load time instead of lazily."* Afterwards the order is right:

```
16:56:21  loading tensors completed, 10.00s    ← weights first
16:56:21  listening on http://127.0.0.1:8082
16:56:21  generate_image 512x512               ← arrives warm
16:57:14  generate_image completed             → real image
```

Verified 2/2 cold starts producing real images after the change.

**Detection worth automating:** a successful generation that comes back under
~20 KB for 512×512 is almost certainly blank. The router could retry once
instead of returning it.

> Editing note: the `--max-vram 6` line is indented with **two** spaces, not
> four. A `sed` pattern expecting four silently matches nothing and reports
> success — check with `grep -n eager /etc/systemd/system/sd-server.service`.

---

## Model replies with nothing at all

**Symptom.** `content` is an empty string, but the request "succeeded".

**Cause.** Some models emit `reasoning_content` before `content`. With a small
`max_tokens` the budget is spent on reasoning and nothing is left for the
answer. Measured: `max_tokens: 40` → empty; `max_tokens: 600` → correct answer.

**Fix.** Use `max_tokens >= 300` when talking to a reasoning model, or read
`reasoning_content` as well.

---

## The big model is 3× slower than it should be

**Symptom.** The 30 B MoE gives ~8 tok/s instead of ~22.

**Cause.** Forcing every layer into VRAM:

| Configuration | tok/s |
|---|---:|
| `-ngl 99` — VRAM at 99.4% | **8.12** |
| default auto-fit — ~1 GiB headroom for KV cache | **22.26** |

**Fix.** Do **not** set `-ngl` for models larger than your VRAM. Let llama.cpp
compute the split. `router.py::MODEL_ARGS` deliberately omits it for this
model.

---

## Both image models must not run at once

`sd-server.service` (SD 3.5) and `sd-server-sd15.service` (SD 1.5) both bind
**port 8082**. They are mutually exclusive by design — they would also fight
over the 6 GB VRAM budget.

The router switches them per request, which costs 5–17 s. If you keep getting
swaps, stay on one model: `ia-imagen -m sd15 …` or `ia-imagen …`.

Never `systemctl start` both. One will fail to bind.

---

## Every request pays the model swap

**Cause.** `/var/lib/llama-router/model` is missing or empty, so the router
thinks nothing is loaded and reloads the model on every request.

**Fix.** Nothing, usually: the next request reloads once and rewrites the
file. If it keeps happening, check `journalctl -u router` — the disk is
probably read-only or full.

---

## A model swap takes 7–35 seconds

Not a bug — the router restarts llama-server with different weights. Check with
`journalctl -u router -f`; you will see
`cargando <model> (estaba <previous>)`.

If a workflow needs to alternate between two models constantly, it will pay
that cost on every other request. Pick one and stay on it.

---

## The agent stalls for 300 s while compressing context

**Symptom.** In a long Hermes session, `agent.log` shows:

```
Compression summary call dispatched: model=ornith-1.5-9b-q4_k_m prompt_chars=30,844
Context compression made no progress for 300.0s ... continuing without compression
```

Five times on 2026-10-07 — 25 minutes of waiting — and afterwards the
session dropped to `APIConnectionError` with ~60K tokens uncompressed. Disk,
RAM and the network were not involved; the llama-server log for the same
minutes tells the whole story, and it is four separate problems.

**1. The summary never stopped.** The summary prompt was small — 9,191
tokens, read in 51.6 s. Then Ornith generated **9,898 tokens over 552 s**
for a summary budgeted at ~3K. Hermes sends the summary call without
`max_tokens` on purpose, so nothing bounded it.

**2. Nobody told llama-server the client had left.** Hermes gave up at
300 s; the server kept generating until 604 s, holding the router's lock, so
every other request queued behind a reply nobody would read. `forward()`
read the whole upstream response before writing a byte, so it could not
notice the hang-up — and for streamed calls the client saw no tokens at all
until the end, which is exactly what Hermes reads as "no progress".

**3. The side request evicted the conversation.** With the default four
slots, the 65,536 KV cells are shared. The summary took a second slot, and
when the conversation came back:

```
E state_read_meta: failed to find 55298 available cells in kv cache
W slot  prompt_load: id  0 | task -1 | failed to load prompt from cache
```

— 55K tokens re-read from scratch, several minutes, then the connection error.

**4. The threshold in the config was ignored.** See
[HERMES.md](HERMES.md#context-compression-on-a-64k-local-model): with a 64K
window `threshold: 0.35` still fires at 55,705 tokens, where everything above
is slowest.

**Fix** (router):

- `forward_live()` streams upstream bytes as they arrive and watches the
  client socket; when the client closes, it shuts the upstream connection and
  llama-server cancels the task. Plain and SSE requests alike — Hermes'
  summary call is not streamed.
- `DEFAULT_MAX_TOKENS = 16384` is added only to requests that carry no output
  cap (`IA_DEFAULT_MAX_TOKENS=0` disables it). An explicit `max_tokens`
  always wins. Do not go lower: Hermes discards a summary that stops on
  `finish_reason=length`, and with 4096 ornith used the whole cap on
  reasoning — `Failed to generate context summary: ... truncated
  (finish_reason=length)` in `~/.hermes/logs/agent.log`.
- Every model runs with `--parallel 1`. The router already serialised chats
  under `_load_lock`, so the extra slots never bought real concurrency — they
  only split the KV. With one slot, a side request parks the conversation in
  llama-server's RAM prompt cache and it comes back intact.
- Hermes: `compression.threshold_tokens: 36000`, `protect_last_n: 10`, and
  `auxiliary.compression.extra_body.reasoning_budget_tokens: 1024` — the
  summary drops from 5–14 min to 3–4.5 min with the same detail. See
  [HERMES.md](HERMES.md#context-compression-on-a-64k-local-model).

**Measured before and after** with `scripts/repro-agent-stall.py` on the CT
(client gives up after 8 s; side request of 18K tokens):

| Check | Before | After |
|---|---:|---:|
| Server still busy after a plain request is abandoned | **124.2 s** | **0.5 s** |
| Server still busy after a streamed request is abandoned | **103.6 s** | **0.5 s** |
| 55,260-token conversation re-read after a side request | **55,260 tok / 448.4 s** | **4 tok / 0.2 s** |
| 34K-token agent turn (reply without reasoning + new question) after a side request | — | **104 tok / 1.5 s** |

At 20K tokens of conversation the eviction does not happen with either
setting (19.6K + 7.4K fit in 64K cells) — it bites near the window limit,
which is where an agent's compression runs. Raw rows:
[`evidence/2026-10-08-agent-stall.jsonl`](evidence/2026-10-08-agent-stall.jsonl).
CI covers the router side without a GPU: `tests/test_forward.py` puts a fake
llama-server behind `forward_live()` and asserts it is hung up on within 3 s.

**One saved KV per model now lives in slot 0.** Files saved with the old
4-slot layout carry the slot id in their name (`<model>-2.bin`); rename one
to `<model>-0.bin` to keep it, or let the next swap write a fresh one.

---

## The agent takes two minutes to answer the first question

**Symptom.** `hermes chat -q "anything"` blocks for 130–160 s, while the same
question through curl returns in seconds. It looks like a hang.

**Cause.** Prompt size, not the GPU. Hermes sends its full system prompt on
every call — measured at **20,109 tokens** (~55 KB: 9 KB identity + 45.7 KB of
27 tool schemas):

```
prompt eval time = 123,566 ms / 20,109 tokens  (162.74 tok/s)   ← 123.6 s
        eval time =   2,506 ms /     57 tokens  ( 22.34 tok/s)   ←   2.5 s
```

The model composes its answer in 2.5 seconds. It spends 124 seconds *reading*
the prompt. Add a cold swap (16.4 s) and Hermes CLI boot (11.7 s) and you get
the observed 161 s.

**Fix.** Nothing to fix — llama.cpp's KV cache already handles it. Turns 2+ in
the same session re-read only **25–71 tokens** (1.7–2.2 s) instead of 20,109.
The two-minute cost is paid **once per session**.

Measured over three consecutive turns in one session:

| Turn | Prompt eval | Model total | Wall |
|---|---:|---:|---:|
| 1 (cold) | 123.6 s / 20,109 tok | 126.1 s | 161.3 s |
| 2 (cached) | **1.7 s / 25 tok** | 3.7 s | 23.4 s |
| 3 (cached) | **2.2 s / 71 tok** | 4.8 s | 24.6 s |

**The ~21 s floor on later turns is the agent, not the model.** `hermes doctor`
alone takes **11.7 s** with no model call — the CLI relaunches its process and
spawns MCP servers on every invocation. A turn where the model answers in 3.7 s
still shows ~23 s of wall clock.

### About the `cache_reuse` warning

```
W load_model: cache_reuse is not supported by this context, it will be disabled
W load_model: cache_reuse is not supported by multimodal, it will be disabled
```

**Benign.** `--cache-reuse` is the optional *KV-shifting* fast path; disabling
it does not disable prompt caching. `--cache-prompt` defaults to enabled and is
what produces the 25-token cached prefill above. Confirmed by measurement, not
by reading the flag docs: turn 2 re-read 25 tokens instead of 20,109.

---

## The agent answered with nonsense or a tool call

**Symptom.** Routing is correct (the right model loads), but the content is
wrong: a small coder model invents a fact, or emits a raw tool-call JSON
instead of prose.

**Cause.** Model choice, not infrastructure. Measured through the agent with a
27-tool system prompt:

| Model | Result |
|---|---|
| `qwen2.5-coder-1.5b` | `"La capital de Mongolia es Tashkent."` — wrong |
| `qwen2.5-coder-7b` | `{"name": "text_to_speech", …}` — a tool call, not an answer |

**Fix.** A coder model is not a general-knowledge model. For open questions use
`ornith-1.5-9b`, `qwen2.5-7b` or the MoE, and see
[MODELS.md](MODELS.md). There is no routing bug to hunt — verify with
`cat /run/llama-router/model`, which reports what actually loaded.

---

## `cliente desconectado: upstream cancelado` in the router log

```
[router] cliente desconectado: upstream cancelado (/v1/chat/completions)
```

The client hung up before the reply finished — usually a CLI or agent
timeout during a long generation. Since the compression fix this is handled:
`forward_live()` closes the upstream connection and llama-server cancels the
task within ~0.5 s, so nothing keeps generating for nobody. If it shows up on
every long request, the client's timeout is too short for this card: raise
it, or stream.

Older routers, and the image endpoints today, log the same event as a
`BrokenPipeError` traceback in `do_POST`. Harmless to the server.

---

## Vulkan device not found

```bash
vulkaninfo --summary
```

If this fails, install `mesa-vulkan-drivers` and `vulkan-tools`. On a card RADV
does not support you will get no device — check
[HARDWARE.md](HARDWARE.md). Do not try to substitute ROCm on Polaris; it was
dropped in ROCm 4.0 and actively rejected by ROCm 7.

---

## Secrets

The API key must never be in a tracked file. `systemd/llama-server.service` in
this repository contains the placeholder `__IA_API_KEY__`, substituted from
`/etc/ia/api-key` at install time.

Before committing anything, scan for anything shaped like a credential —
substitute your key's own prefix for `<KEY_PREFIX>`:

```bash
grep -rniE '<KEY_PREFIX>|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9_-]{30,}' \
  --exclude-dir=.git .
```

If it prints anything, stop and redact it. Run this *after* writing docs too:
a detection snippet that quotes a real prefix will trip its own scanner.

---

## The router does not see a model you added

Model paths live in the `MODELS` dict at the top of `router.py`. Add the id and
path, then:

```bash
sudo systemctl restart router
curl -s http://127.0.0.1:8090/v1/models -H "Authorization: Bearer $IA_API_KEY"
```

The id must appear there before any client can use it.

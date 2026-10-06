# What to expect and how to use it

Everything in this file was measured on the machine in
[HARDWARE.md](HARDWARE.md). Nothing is estimated. If you are trying this stack
for the first time, read this before you conclude something is broken.

## The four states

The same stack, four different experiences. Which one you get depends on what
you did a minute ago — not on how powerful your hardware is.

| State | What dominates | Wall time |
|---|---|---:|
| **Warm API** — model already loaded | decoding tokens | **3.1 – 14.1 s** |
| **Cold API** — right after a model swap | loading weights | **11.0 – 55.0 s** |
| **Agent, first message of a session** | 20,109-token prompt | **~161 s** |
| **Agent, every message after that** | agent CLI restart | **~21 – 25 s** |

Read it as a chain: each row adds a cost that the row above does not have.

```
warm API        ─ decode only ────────────────────────── 3–14 s
cold API        ─ + model swap (7.9–38.5 s) ──────────── 11–55 s
agent #1        ─ + 20,109-token prefill (~124 s) ────── ~161 s
agent #2+       ─ prefill cached, + CLI restart (~11.7 s) ─ ~21–25 s
```

## Rule 1 — pick one model and stay on it

This is the single most impactful thing you can do.

Measured with an identical request in both states:

| Model | Warm | Cold | Cold is slower by |
|---|---:|---:|---:|
| `qwen2.5-coder-1.5b` | **3.1 s** | 11.0 s | 3.5× |
| `qwen2.5-vl-3b` | **4.4 s** | 14.9 s | 3.4× |
| `qwen2.5-7b` | **8.8 s** | 24.3 s | 2.8× |
| `qwen2.5-coder-7b` | **8.8 s** | 24.4 s | 2.8× |
| `ornith-1.5-9b` | **10.9 s** | 26.3 s | 2.4× |
| `qwen3-30b-a3b` | **14.1 s** | 55.0 s | 3.9× |

The gap is *entirely* the swap: the router restarts llama-server with different
weights. Generation speed is identical in both states — 99.2 vs 99.1 tok/s,
34.3 vs 34.3 tok/s. **A cold model is never slower to generate; it is slow to
arrive.**

So: one model per session, one model per workflow. Every hop you make is
another 7.9–38.5 s of waiting for weights to load.

## Rule 2 — know what is loaded

```bash
cat /var/lib/llama-router/model
```

If you are about to make a request and this file says something else, you are
about to pay the swap. Check it before blaming the model.

## Rule 3 — the agent's first message is slow, once

If you open a fresh agent session, expect **~161 s** for the first reply. It is
not hung. The breakdown from llama-server's own log:

```
prompt eval time = 123,566 ms / 20,109 tokens  (162.74 tok/s)   ← reading
        eval time =   2,506 ms /     57 tokens  ( 22.34 tok/s)   ← answering
```

The model composes its answer in **2.5 seconds**. It spends **124 seconds
reading** the prompt, because the agent sends ~55 KB of identity plus 27 tool
schemas on every call.

You pay that **once per session**. Prompt caching collapses the shared prefix
to **25–71 tokens** on later turns:

| Turn | Prefill | Model total | Wall |
|---|---:|---:|---:|
| 1 (cold) | 123.6 s / 20,109 tok | 126.1 s | 161.3 s |
| 2 (cached) | **1.7 s / 25 tok** | 3.7 s | 23.4 s |
| 3 (cached) | **2.2 s / 71 tok** | 4.8 s | 24.6 s |

After that, wall time sits at **~21–25 s** and stops improving. That floor is
the agent CLI relaunching its process, spawning MCP servers and writing session
state on every invocation — `hermes doctor` alone takes **11.7 s** with no
model call at all.

## Rule 4 — choose the model for the job, not the speed column

Speed and correctness are different axes. Measured through the agent with a
27-tool prompt, routing was correct 6/6 times but content was correct 4/6:

| Model | Result |
|---|---|
| `qwen2.5-coder-1.5b` | `"La capital de Mongolia es Tashkent."` — wrong |
| `qwen2.5-coder-7b` | `{"name": "text_to_speech", …}` — a tool call, not an answer |
| the other four | correct |

The 1.5 B coder is the fastest model here at 99 tok/s. It is also the one most
likely to be confidently wrong. See [MODELS.md](MODELS.md) for which model fits
which task.

## Rule 5 — the fast model will not feel fast inside an agent

Through the raw API, `qwen2.5-coder-1.5b` answers in 3.1 s. Through the agent
the floor is ~21 s, set by CLI overhead, not by decode speed. If you are
evaluating "how fast is this stack", test with `curl` against
`/v1/chat/completions` — that measures the stack. Testing with an agent
measures the agent too.

## Correct usage, in short

1. **One model per session.** Switching costs 7.9–38.5 s every time.
2. **Check `/var/lib/llama-router/model`** before wondering why a request is slow.
3. **Give the agent's first message ~2.5 minutes**, then expect ~21–25 s.
4. **Do not force `-ngl`** on the 30 B MoE — it halves throughput
   ([TROUBLESHOOTING.md](TROUBLESHOOTING.md)).
5. **Pick models by task.** Fast ≠ correct for factual questions.
6. **Judge the stack with `curl`, the agent with `hermes`.** Different
   numbers, different things being measured.

## Measure it yourself

```bash
# what is loaded right now
cat /var/lib/llama-router/model

# cold: ask for a model that is not loaded, time the whole request
time curl -s http://192.168.10.126:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IA_API_KEY" \
  -d '{"model":"qwen2.5-7b-instruct-q4_k_m","temperature":0,"max_tokens":300,
       "messages":[{"role":"user","content":"Explica que es una red neuronal. 250 palabras."}]}'

# warm: run the exact same command again immediately — that is the difference
```

Compare the two `time` outputs. The difference is the swap. The generation
speed in both is the same, which you can confirm in the server log:

```bash
journalctl -u llama-server.service --since "-5min" \
  | grep -E "prompt eval time|eval time"
```

If your numbers differ from the ones here, your hardware differs — add yours.
A benchmark nobody can reproduce is a marketing claim.

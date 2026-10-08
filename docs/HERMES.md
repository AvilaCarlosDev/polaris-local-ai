# Using it as an agent engine

The stack exposes a standard OpenAI-compatible API, so anything that speaks
that protocol can use it. The setup below is the one actually running: **Hermes
Agent** driving every model in this repository as its reasoning engine, with
its own memory served over MCP.

## 1. Point the agent at the router

`~/.hermes/config.yaml`:

```yaml
model:
  default: ornith-1.5-9b-q4_k_m
  provider: custom
  api_key: ${IA_API_KEY}
  base_url: http://192.168.10.126:8090/v1   # your router
  api_mode: chat_completions
  context_length: 65536
```

`provider: custom` is what makes the agent use your endpoint instead of a
cloud provider. `context_length` must not exceed the router's `-c` value.

## 2. Keep the key out of the config

`api_key: ${IA_API_KEY}` expands from the environment, so the real value lives
in `~/.hermes/.env` — never in `config.yaml`, which is the file most likely to
be copied, diffed or committed:

```bash
echo 'IA_API_KEY=the-key-from-/etc/ia/api-key' >> ~/.hermes/.env
chmod 600 ~/.hermes/.env
```

The router accepts the same key from `/etc/ia/api-key` or
`$IA_API_KEY`; see `router.py::_load_api_key`.

## 3. Give the agent memory over MCP

An agent that cannot remember yesterday is a demo, not a tool. Memory is
[Engram](https://github.com/Gentleman-Programming/engram), run **on the
machine where the agent runs**, as a local MCP server over stdio:

```yaml
mcp_servers:
  engram:
    command: env
    args:
      - ENGRAM_DATA_DIR=/home/you/.local/share/engram/data
      - /home/you/.local/bin/engram
      - mcp
      - --tools=agent
    enabled: true
```

It used to run on the CT and be reached over SSH. Local is better on every
axis that matters here: no network hop on every memory call, it keeps working
when the GPU box is off, and the memories stay on the disk of the machine you
work on. Moving it is a copy of `engram.db`; compare the observation titles in
both databases before deleting the old one.

`systemd/optional/engram-proxy.service` is still in the repo for a setup that
wants Engram on the server and shared over the LAN; `setup.sh` does not
install it.

Verify it registered:

```bash
hermes mcp list
# Name      Transport                      Tools   Status
# engram    env ENGRAM_DATA_DIR=/home...   all     ✓ enabled
```

## 4. Give it a voice

`~/.hermes/SOUL.md` holds the persona — how it answers, how long replies
should be, what it must never do. Keep it separate from `config.yaml` so
changing tone never risks breaking configuration.

## 5. Confirm the whole chain

Ask something that requires *both* the local model and a tool call:

```bash
hermes chat -q "¿Qué IP tiene la LXC ia? Úsala de la herramienta de memoria."
```

A correct answer means the agent selected your model, reached the endpoint,
invoked the MCP tool and composed a reply — the full loop, with no cloud
involved.

## Switching engines mid-conversation

Because the router serves every model behind one URL, changing the agent's
model is a one-line edit — or, for an ad-hoc run:

```bash
hermes chat -m qwen3-30b-a3b-instruct-2507-q4_k_m -q "your hard question"
```

Expect a swap pause on the first request to a model that is not already
loaded; see [BENCHMARKS.md](BENCHMARKS.md).

## What to expect on screen

Real measurements from this machine. Worth knowing before you conclude
something is broken:

| | Wall time |
|---|---:|
| First message of a session (cold model) | **~161 s** |
| First message of a session (model already loaded) | **~130 s** |
| Any later message in the same session | **~21–25 s** |
| `hermes doctor`, no model call at all | **11.7 s** |

Three separate costs stack up:

1. **A ~20,100-token prompt.** Hermes sends ~55 KB of identity plus 27 tool
   schemas on every call. At ~160 tok/s that is ~124 s of prefill the model
   pays before it reads your sentence. llama.cpp's KV cache collapses this to
   **25–71 tokens** on turns 2+, so the two-minute cost is paid **once per
   session** — not per message.
2. **CLI relaunch per invocation.** `hermes chat` is a fresh process each time:
   boot, MCP spawn, session write. That is the ~11.7 s floor visible even when
   the model answers in under 4 s.
3. **Model swaps**, 7–35 s, only when the requested model is not loaded.

A consequence worth acting on: **the fast model in [BENCHMARKS.md](BENCHMARKS.md)
will not feel fast inside the agent.** `qwen2.5-coder-1.5b` generates at 96
tok/s, but through Hermes the floor is set by prompt and CLI overhead, not by
decode speed. For interactive use, favour models that stay loaded.

Full breakdown with per-turn prefill/decode numbers:
[BENCHMARKS.md → Latency through an agent](BENCHMARKS.md#latency-through-an-agent-what-you-actually-feel).

## Context compression on a 64K local model

Long sessions eventually hit Hermes' context compression: it asks the model
for a summary of the middle of the conversation and replaces it. On this
stack that used to stall for 300 s and give up — five times in one evening,
25 minutes of dead waiting. The router-side causes and their fixes are in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#the-agent-stalls-for-300-s-while-compressing-context).
The Hermes side is one setting:

```yaml
compression:
  threshold_tokens: 36000   # the cap Hermes actually honours
  protect_last_n: 10        # a shorter verbatim tail frees more per compaction
```

**`threshold` alone does nothing here.** Hermes raises any `threshold` below
75% to 75% for windows under 512K tokens, then caps the result at 85%: with
`context_length: 65536`, `threshold: 0.35` still fires at **55,705 tokens**
(`"effective_threshold":55705` in `agent.log`). By then the summary is
expensive and decode has dropped to ~8.7 tok/s (measured at 54K of context,
against ~28 tok/s on a short one). `threshold_tokens` is an absolute cap that
bypasses that floor.

**Do not set it too low either.** After a compaction Hermes keeps its base
prompt (identity plus tool schemas: the first turn of a session arrives with
22,952 tokens, ~21K of them fixed), the protected tail and the summary
(~2–3K). If the threshold sits below that sum, compression can never get
under it and fires on every turn. With `protect_last_n: 20` the
post-compaction size measured 27–31K, so a 20K threshold is unreachable;
36K with a 10-message tail is the working value here.

**Limit the summary's reasoning, do not switch it off.** Ornith thinks
before it writes. Hermes sends the summary without `max_tokens` on purpose and
throws away any reply that ends in `finish_reason=length`, so the output must
never be capped below a full summary (the router's default is 16384 for that
reason). What can be bounded is the thinking:

```yaml
auxiliary:
  compression:
    extra_body:
      reasoning_budget_tokens: 1024
```

Measured on a 26,546-token summary prompt with `scripts/bench-summary.py`
(n=2 per mode; raw rows in
[`evidence/2026-10-08-summary-reasoning.jsonl`](evidence/2026-10-08-summary-reasoning.jsonl)):

| Reasoning | Wall | Output tokens | Summary |
|---|---:|---:|---|
| unbounded (default) | 328 – 856 s | 4,247 – 8,488 | detailed, correct |
| `reasoning_budget_tokens: 2048` | 284 – 362 s | 3,684 – 4,661 | detailed, correct |
| **`reasoning_budget_tokens: 1024`** | **197 – 266 s** | 2,592 – 3,456 | **detailed, correct** |
| `enable_thinking: false` | 46 – 100 s | 617 – 1,332 | uneven: one run summarised its own instructions |

The 856 s run includes reading the prompt cold (168 s); the others reuse it.
Thinking off is the fastest, but one of its two summaries kept almost nothing
of the conversation, and a bad summary is worse than a slow one: Hermes
replaces the middle of the session with it.

**End to end, with both fixes** (router cap 16384, reasoning budget 1024),
15 Hermes turns of ~2K tokens each: compression fired at 39,530 tokens, the
summary call went out at 17:36:47 and was committed at 17:40:54 — **4 min 7 s,
complete, no stall** (13 → 9 messages). Timeline:
[`evidence/2026-10-08-hermes-compression-e2e.log`](evidence/2026-10-08-hermes-compression-e2e.log).

**Leave headroom above the post-compaction floor.** Hermes keeps a verbatim
tail of at least ~10K tokens on top of its ~21K fixed prompt, so a compaction
here lands at ~34–36K. With turns as large as the test's, the first attempt had
nothing worth summarising (refused: the summary would have grown the
transcript) and the second only went from ~37.6K to ~35.6K. Two weak
compactions latch Hermes' anti-thrash breaker and automatic compression stops
for that session. A real session with many small messages (2026-10-07:
115 → 37 messages) does not hit it; if yours does, raise `threshold_tokens`
rather than lowering the tail.

**The next turn re-reads the summary and the tail.** At each compaction
Hermes rebuilds its system prompt and swaps the middle of the conversation for
the summary, so the turn after it re-reads from there — 19,976 of 39,283
tokens were reused in the run above. Expect one slow turn (~1–2 min) after
each compaction; the router keeps the conversation cached across the summary
call itself (`scripts/repro-agent-stall.py --only agent`: 104 tokens re-read
after a side request on a 34K-token conversation).

## Other consumers

Anything OpenAI-compatible works unchanged:

- **opencode** — add a `provider` with `baseURL` set to the router
- **Ollama/Cline/LiteLLM-style clients** — same, via their custom-endpoint option
- **Anything with `OPENAI_BASE_URL`** — export it and go:

```bash
export OPENAI_BASE_URL=http://192.168.10.126:8090/v1
export OPENAI_API_KEY="$IA_API_KEY"
```

## What this buys you

- No tokens billed, no request limits, no data leaving the machine.
- The agent can be given a *big* model for hard steps and a *fast* one for
  routine steps without changing a line of agent code.
- The memory layer is on your disk too — the whole stack is yours.

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

An agent that cannot remember yesterday is a demo, not a tool. The router
ships the HTTP bridge (`systemd/engram-proxy.service`) that exposes the memory
service on the LAN; the agent reaches it over SSH:

```yaml
mcp_servers:
  engram:
    command: ssh
    args:
      - -o
      - BatchMode=yes
      - -p
      - '2222'
      - root@192.168.10.126
      - env
      - HOME=/root
      - ENGRAM_DATA_DIR=/opt/ia/engram-data
      - /usr/local/bin/engram
      - mcp
      - --tools=agent
    enabled: true
```

Verify it registered:

```bash
hermes mcp list
# Name      Transport        Tools   Status
# engram    ssh -o Batch…    all     ✓ enabled
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

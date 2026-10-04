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

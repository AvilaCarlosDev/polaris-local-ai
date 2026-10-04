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

## Every request dies with "Empty reply from server"

**Cause.** `router.service` lost its state directory. `/run` is tmpfs, so the
file is gone after every reboot unless systemd recreates it.

**Fix.** The unit must declare:

```ini
[Service]
RuntimeDirectory=llama-router
RuntimeDirectoryMode=0755
```

---

## A model swap takes 7–35 seconds

Not a bug — the router restarts llama-server with different weights. Check with
`journalctl -u router -f`; you will see
`cargando <model> (estaba <previous>)`.

If a workflow needs to alternate between two models constantly, it will pay
that cost on every other request. Pick one and stay on it.

---

## `BrokenPipeError` in the router log

```
File "/opt/ia/router.py", line 546, in do_POST
    self.wfile.write(data)
BrokenPipeError: [Errno 32] Broken pipe
```

The client disconnected before the response finished — usually a CLI or browser
timeout during a long generation. Harmless to the server. Raise the client's
timeout, or generate asynchronously.

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

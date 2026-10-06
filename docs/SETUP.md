# Setup

Install from a clean Debian/Ubuntu host. The short version is `sudo ./setup.sh`;
this page is what it does, so you can do it by hand or debug why it stopped.

## Requirements

See [HARDWARE.md](HARDWARE.md). In short: an AMD card RADV supports, x86-64
with AVX2, 16 GB RAM (32 GB recommended), 40 GB disk, systemd.

## 1. Dependencies

```bash
sudo apt update
sudo apt install -y git cmake g++ python3 curl vulkan-tools mesa-vulkan-drivers
```

Check the card is visible to Vulkan before anything else — if this fails, no
amount of building will help:

```bash
vulkaninfo --summary | grep deviceName
# should list your AMD card
```

## 2. Engines

```bash
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /opt/llama.cpp
cmake -S /opt/llama.cpp -B /opt/llama.cpp/build -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON
cmake --build /opt/llama.cpp/build -j"$(nproc)"

git clone --depth 1 https://github.com/leejet/stable-diffusion.cpp.git /opt/stable-diffusion.cpp
cmake -S /opt/stable-diffusion.cpp -B /opt/stable-diffusion.cpp/build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build /opt/stable-diffusion.cpp/build -j"$(nproc)"

git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git /opt/whisper.cpp
cmake -S /opt/whisper.cpp -B /opt/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release \
  -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=OFF
cmake --build /opt/whisper.cpp/build -j"$(nproc)"
```

llama.cpp and stable-diffusion.cpp **must** be built with `GGML_VULKAN=ON` —
a CPU-only build will start and then crawl. whisper.cpp is the opposite: it
runs on the CPU, so it gets no Vulkan flag at all.

`setup.sh` skips whisper.cpp entirely when `ggml-medium.bin` (below) is not
present. No weights, no engine, no audio category.

## 3. Weights

Put the gguf files where `router.py` expects them:

```
/opt/ia/models/        qwen2.5-*, mmproj-*, sd15-*, sd3.5_medium-*, t5xxl-*, clip_*
/opt/ia/models/        ggml-medium.bin  (audio — optional, see below)
/var/cache/ai/models/  Ornith-1.5-9B-*, Qwen_Qwen3-30B-A3B-*
```

Or edit the `MODELS` table at the top of `router.py`. Source links are in
[MODELS.md](MODELS.md).

## 4. API key

```bash
sudo install -d -m 0755 /etc/ia
head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40 | sudo tee /etc/ia/api-key >/dev/null
sudo chmod 600 /etc/ia/api-key
```

Never hardcode this in a unit file or commit it. The unit shipped here uses
the placeholder `__IA_API_KEY__`, substituted at install time.

## 5. Units

```bash
sudo sed "s|__IA_API_KEY__|$(sudo cat /etc/ia/api-key)|g" \
  systemd/llama-server.service | sudo tee /etc/systemd/system/llama-server.service >/dev/null
sudo cp systemd/router.service systemd/sd-server.service systemd/sd-server-sd15.service \
         systemd/whisper-server.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Skip `whisper-server.service` if you did not put `ggml-medium.bin` in place —
installing it without weights only produces a crash loop. `setup.sh` makes
that decision for you.

What each one does:

| Unit | Role |
|---|---|
| `llama-server.service` | llama.cpp, one model at a time, port 8080 |
| `router.service` | OpenAI-compatible router on 8090; swaps models |
| `sd-server-sd15.service` | SD 1.5, port 8082 |
| `sd-server.service` | SD 3.5, **also** port 8082 — mutually exclusive |
| `whisper-server.service` | transcription on port 8081, CPU only, optional |

The router keeps its state file at `/var/lib/llama-router/model` (persistent:
it survives reboots and router restarts). `state_dir()` creates the directory
on first write, so there is no systemd `RuntimeDirectory` involved.

`systemd/optional/` holds units that are **not** installed by `setup.sh` —
they carry site-specific settings (a LAN IP, a service this repo does not
ship) and would fail on any other host. Copy them by hand if you know you
want them.

## 6. Start

```bash
sudo systemctl enable --now llama-server router sd-server-sd15
sudo systemctl enable sd-server        # enabled, but NOT running alongside sd15
sudo systemctl enable --now whisper-server   # only if you installed the audio weight
```

Verify:

```bash
curl -s http://127.0.0.1:8090/v1/models \
  -H "Authorization: Bearer $(sudo cat /etc/ia/api-key)" | python3 -m json.tool
```

You should get the list of model ids, each with a `category`
(`texto`, `vision`, `multitarea`, `imagen`, and `audio` when whisper is
installed). The same list drives `clients/ia-models`.

## 7. First request

```bash
export IA_API_KEY="$(sudo cat /etc/ia/api-key)"
curl http://127.0.0.1:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IA_API_KEY" \
  -d '{"model":"qwen2.5-7b-instruct-q4_k_m",
       "messages":[{"role":"user","content":"Say hello"}]}'
```

## 8. The agent

Continue with [HERMES.md](HERMES.md).

## Day-to-day

```bash
sudo systemctl status router llama-server      # health
journalctl -u router -f                       # swap log
sudo systemctl restart router                  # clean restart
```

The router starts llama-server on demand and stops it when a different model
is requested. Nothing to do manually.

## Upgrading

```bash
cd /opt/llama.cpp && git pull && cmake --build build -j"$(nproc)"
sudo systemctl restart router
```

Same for `/opt/stable-diffusion.cpp`. After rebuilding sd-server, re-check that
`--eager-load` is still on the unit — see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

# Local hero baseline — 2026-10-05

Evidence that every hero artifact can be produced on our own hardware: no
cloud model, no external API. Runs on the `ia` container (CT 103).

## Hardware

| Item | Value | Source |
| --- | --- | --- |
| Host | `ia`, Linux 7.0.2-6-pve | `uname -sr` |
| CPU / RAM | 6 vCPU, 24 GiB (619 MiB used) | `nproc`, `free -h` |
| GPU 0 | 8589934592 B = **8 GiB**, 5.4 MiB used at idle | `/sys/class/drm/card0/device/mem_info_vram_*` |
| GPU 1 | 512 MiB (virtual display) | `/sys/class/drm/card1/device/mem_info_vram_total` |
| GPU model | AMD Radeon RX 580 8 GB | reported by owner (`lspci` is absent in the CT) |

## Stack

| Service | Port | State | Check |
| --- | --- | --- | --- |
| llama-server | 127.0.0.1:8080 | active | upstream of the router |
| router | 0.0.0.0:8090 | active | pid of `/opt/ia/router.py` |
| whisper-server | 127.0.0.1:8081 | active | `GET /health` → `{"status":"ok"}` |
| sd-server (sd35) | 127.0.0.1:8082 | active | `/v1/models` → `sd-cpp-local` |
| sd-server-sd15 | — | inactive | not started |
| image-mcp | — | inactive | not started |

## Measurements

| Check | Result |
| --- | --- |
| `GET :8090/v1/models` | 200, 10 ids, 5 categories, 7.4 ms |
| `POST :8090/v1/completions` (4 tokens) | 200, 1.16 s |
| `POST :8090/v1/chat/completions` (74 tokens) | 200, 4.03 s ≈ 18 tok/s |

Selector output (`id`, `category`, `loaded`):

```
ornith-1.5-9b-q4_k_m                texto      False
qwen2.5-7b-instruct-q4_k_m          texto      True
qwen2.5-coder-1.5b-instruct-q4_k_m  texto      False
qwen2.5-coder-7b-instruct-q4_k_m    texto      False
qwen2.5-vl-3b-instruct-q4_k_m       vision     False
qwen3-30b-a3b-instruct-2507-q4_k_m  multitarea False
imagen                              imagen     True
sd15                                imagen     False
sd35                                imagen     True
whisper-medium                      audio      True
```

## Local generation #1 — hero title

Produced by `qwen2.5-7b-instruct-q4_k_m` on the RX 580, served by the router.

- Prompt: name 4 candidates (uppercase, max 20 chars) plus a subtitle for an
  original voxel-diorama hero of `polaris-local-ai`, inspired by another
  project but never copied; reply only JSON.
- Timing: `http=200 t=4.029s`, `completion_tokens: 74`, `prompt_tokens: 139`.
- Output:

```json
[{"title":"LOCAL AI WONDERS","sub":"VOXEL DIORAMA"},
 {"title":"FLOATING ISLAND MIRAGE","sub":"LOCAL AI ART"},
 {"title":"STRAW HAT VILLAGE","sub":"LOCAL AI SCULPTURE"},
 {"title":"SAILBOAT OASIS","sub":"LOCAL AI LANDSCAPE"}]
```

## Hero video — rendered on the CT

Title chosen by the owner: **FLOATING ISLAND MIRAGE** / *Local AI art*, picked
from the local candidates above.

| Step | Where | Result |
| --- | --- | --- |
| Render 870 frames, 1600x900 | CT 103, `python3-pil` 11.1.0 | 0.12 s/frame, 102.5 s total |
| Encode master | CT 103, ffmpeg 7.1.5 | 1600x900, 30 fps, 29.0 s, 13.2 MB |
| Encode embed | CT 103, ffmpeg 7.1.5 | 1280x720, crf 27, 4.5 MB |
| Preview still | CT 103 | 720p webp, 27.9 KB |
| Fonts | CT has DejaVu, no Noto | `hero-scene.py` falls back Noto → DejaVu → Liberation |

Artifacts live in `/opt/ia/hero/` on the CT and in `docs/media/` in the repo.
Reproduce with `scripts/hero-scene.sh` (Pillow + ffmpeg, no network).

Honest split: the title came from the local `qwen2.5-7b`; the scene script was
authored with AI assistance and then rendered and encoded on the CT — every
pixel of the video was produced by our own hardware.

## Findings

- Session notes had ports inverted: **8080 is llama-server, 8090 is the
  router**. `README.md`, `docs/SETUP.md` and `docs/TROUBLESHOOTING.md` already
  use 8090 correctly — only the notes were wrong.
- `/usr/bin/time` does not exist in the CT; use `curl -w '%{time_total}'`.
- `lspci` does not exist in the CT; read `/sys/class/drm/*/device/` instead.
- A 4-token completion reports 1.16 s while a 74-token chat reports 4.03 s:
  the first measurement includes warm-up, so use chat runs for throughput.

## Next

- Embed the scene video in the READMEs (release asset) and decide whether it
  replaces or accompanies the terminal hero.
- Have the local model iterate on the scene spec (labels, palette, layout) so
  more of the design comes from it.
- Time an sd35 image from the CLI and attach the frame as hero evidence.

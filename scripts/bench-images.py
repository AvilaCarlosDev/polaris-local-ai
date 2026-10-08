#!/usr/bin/env python3
"""Same image, two engines: stable-diffusion.cpp vs ComfyUI.

Written to answer "does sd.cpp bring any advantage over ComfyUI?" on this
card with numbers instead of opinions. Every run uses one prompt, one seed,
512x512, 20 steps, euler — only the engine, backend and weights change.

  sd.cpp   runs sd-cli once per image, so each run is a cold start (load +
           sample + decode). The sampling time is parsed from its own log.
  ComfyUI  is started once (--cpu: PyTorch has no Vulkan backend and ROCm
           does not support Polaris), then sent the same workflow N times
           with a new seed each time, so run 1 is cold and the rest are warm.

    python3 scripts/bench-images.py sdcpp --backend vulkan0 -m sd15-Q5_1.gguf
    python3 scripts/bench-images.py sdcpp --backend cpu -m v1-5-fp16.safetensors
    python3 scripts/bench-images.py comfyui --comfy /path/ComfyUI \\
        --python /path/venv/bin/python --ckpt v1-5-pruned-emaonly-fp16.safetensors

Prints one JSON line per image. Stop llama-server and sd-server first: they
hold VRAM and RAM that both engines need.
"""
import argparse
import json
import os
import re
import subprocess
import threading
import time
import urllib.request

PROMPT = "a red fox figurine on a wooden desk, soft studio lighting, 35mm photo"
NEGATIVE = "blurry, lowres"
SDCPP = "/opt/stable-diffusion.cpp/build/bin/sd-cli"


def peak_rss_mb(pid, stop, out):
    """Sample VmRSS of a process tree root; /usr/bin/time is not in the CT."""
    peak = 0
    while not stop.is_set():
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        peak = max(peak, int(line.split()[1]))
        except OSError:
            break
        time.sleep(0.2)
    out.append(round(peak / 1024))


def run_sdcpp(args, seed):
    cmd = [SDCPP, "--backend", args.backend, "-p", PROMPT, "-n", NEGATIVE,
           "-W", "512", "-H", "512", "--steps", "20", "--sampling-method", "euler",
           "--cfg-scale", str(args.cfg), "-s", str(seed), "-o", args.output]
    cmd += ["-m", args.model]
    for flag in ("clip_l", "clip_g", "t5xxl"):
        val = getattr(args, flag)
        if val:
            cmd += [f"--{flag}", val]
    if args.backend != "cpu":
        cmd += ["--max-vram", "6"]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    stop, rss = threading.Event(), []
    watcher = threading.Thread(target=peak_rss_mb, args=(proc.pid, stop, rss))
    watcher.start()
    log = proc.communicate()[0]
    wall = time.monotonic() - t0
    stop.set()
    watcher.join()
    if proc.returncode != 0:
        raise SystemExit(f"sd-cli failed ({proc.returncode}):\n{log[-2000:]}")

    def grab(pattern):
        m = re.search(pattern, log)
        return float(m.group(1)) if m else None

    return {"engine": "sd.cpp", "backend": args.backend,
            "weights": os.path.basename(args.model), "seed": seed,
            "wall_s": round(wall, 1),
            "load_s": grab(r"loading tensors completed, taking ([\d.]+)s"),
            "sampling_s": grab(r"sampling completed, taking ([\d.]+)s"),
            "decode_s": grab(r"decode_first_stage completed, taking ([\d.]+)s"),
            "peak_rss_mb": rss[0] if rss else None}


def comfy_workflow(ckpt, seed, cfg):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage" if "3.5" not in ckpt else "EmptySD3LatentImage",
              "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
            "latent_image": ["4", 0], "seed": seed, "steps": 20, "cfg": cfg,
            "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0],
                                                    "filename_prefix": "bench"}},
    }


def comfy_call(port, path, payload=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(payload).encode() if payload else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def run_comfyui(args):
    log_path = os.path.join(args.comfy, "bench-server.log")
    log = open(log_path, "w")
    t_boot = time.monotonic()
    server = subprocess.Popen([args.python, "main.py", "--cpu", "--listen", "127.0.0.1",
                               "--port", str(args.port), "--disable-auto-launch"],
                              cwd=args.comfy, stdout=log, stderr=subprocess.STDOUT)
    stop, rss = threading.Event(), []
    watcher = threading.Thread(target=peak_rss_mb, args=(server.pid, stop, rss))
    watcher.start()
    try:
        for _ in range(300):
            try:
                comfy_call(args.port, "/system_stats")
                break
            except OSError:
                time.sleep(1)
        boot = time.monotonic() - t_boot
        for i in range(args.runs):
            seed = args.seed + i
            t0 = time.monotonic()
            pid = comfy_call(args.port, "/prompt",
                             {"prompt": comfy_workflow(args.ckpt, seed, args.cfg)})["prompt_id"]
            while True:
                hist = comfy_call(args.port, f"/history/{pid}")
                if pid in hist and hist[pid].get("status", {}).get("completed"):
                    break
                if pid in hist and hist[pid].get("status", {}).get("status_str") == "error":
                    raise SystemExit(json.dumps(hist[pid]["status"])[:2000])
                time.sleep(0.5)
            wall = time.monotonic() - t0
            with open(log_path) as f:
                executed = re.findall(r"Prompt executed in ([\d.:]+)", f.read())
            print(json.dumps({"engine": "ComfyUI", "backend": "cpu", "weights": args.ckpt,
                              "seed": seed, "run": i + 1, "state": "cold" if i == 0 else "warm",
                              "wall_s": round(wall, 1), "server_boot_s": round(boot, 1),
                              "comfy_reported": executed[-1] if executed else None}),
                  flush=True)
    finally:
        server.terminate()
        server.wait(timeout=60)
        stop.set()
        watcher.join()
        log.close()
    print(json.dumps({"engine": "ComfyUI", "weights": args.ckpt, "peak_rss_mb": rss[0]}))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="engine", required=True)
    s = sub.add_parser("sdcpp")
    s.add_argument("--backend", default="vulkan0")
    s.add_argument("-m", "--model", required=True)
    s.add_argument("--clip_l")
    s.add_argument("--clip_g")
    s.add_argument("--t5xxl")
    s.add_argument("--cfg", type=float, default=7.0)
    s.add_argument("--runs", type=int, default=2)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--output", default="/tmp/bench-sdcpp.png")
    c = sub.add_parser("comfyui")
    c.add_argument("--comfy", required=True, help="ComfyUI checkout")
    c.add_argument("--python", required=True, help="python of ComfyUI's venv")
    c.add_argument("--ckpt", required=True, help="file name under models/checkpoints")
    c.add_argument("--cfg", type=float, default=7.0)
    c.add_argument("--runs", type=int, default=3)
    c.add_argument("--seed", type=int, default=42)
    c.add_argument("--port", type=int, default=8188)
    args = p.parse_args()

    if args.engine == "sdcpp":
        for i in range(args.runs):
            print(json.dumps(run_sdcpp(args, args.seed + i)), flush=True)
    else:
        run_comfyui(args)


if __name__ == "__main__":
    main()

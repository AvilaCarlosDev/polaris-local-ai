#!/usr/bin/env python3
"""Run on CT 103: identical 300-token cold/warm requests and image→text checks.

The historical exact prompt was not preserved. This freezes a new prompt for
same-day router A/B; historical tables are contextual references, not paired data.
Only one request runs at a time. Results contain no API key or full server command.
"""
import argparse
import hashlib
import json
import pathlib
import re
import struct
import subprocess
import threading
import time
import urllib.request

MODELS = ["qwen2.5-coder-1.5b-instruct-q4_k_m", "qwen2.5-vl-3b-instruct-q4_k_m",
          "qwen2.5-7b-instruct-q4_k_m", "qwen2.5-coder-7b-instruct-q4_k_m",
          "ornith-1.5-9b-q4_k_m", "qwen3-30b-a3b-instruct-2507-q4_k_m"]
PROMPT = ("Write a detailed technical explanation of how a local language model serves requests: "
          "model loading, prompt processing, KV caching, token generation, and memory limits. "
          "Continue for at least one thousand words, using paragraphs rather than lists.")
API = "http://127.0.0.1:8090"


def request(path, key, payload=None):
    req = urllib.request.Request(API + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as response:
        return json.load(response)


def read_number(path):
    try:
        return int(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return None


def measure(path, key, payload):
    samples, done = [], threading.Event()

    def sample():
        while not done.is_set():
            samples.append({"vram": read_number("/sys/class/drm/card0/device/mem_info_vram_used"),
                            "gtt": read_number("/sys/class/drm/card0/device/mem_info_gtt_used"),
                            "llama_cgroup": read_number("/sys/fs/cgroup/system.slice/llama-server.service/memory.current")})
            done.wait(0.25)

    watcher = threading.Thread(target=sample, daemon=True)
    watcher.start()
    start = time.monotonic()
    try:
        body = request(path, key, payload)
    finally:
        done.set()
        watcher.join()
    row = {"wall_s": round(time.monotonic() - start, 3), "usage": body.get("usage"),
           "timings": body.get("timings"), "finish_reason": body.get("choices", [{}])[0].get("finish_reason")}
    for field in ("vram", "gtt", "llama_cgroup"):
        values = [s[field] for s in samples if s[field] is not None]
        row["peak_" + field + "_bytes"] = max(values) if values else None
    return row, body


def chat(model, messages, cap=300):
    return {"model": model, "temperature": 0, "max_tokens": cap, "messages": messages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=["text", "image"], default="text")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--models", nargs="+", choices=MODELS, default=MODELS)
    parser.add_argument("--corpus", help="frozen text file for long-prompt image→text checks")
    args = parser.parse_args()
    key = pathlib.Path("/etc/ia/api-key").read_text().strip()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(90):
        try:
            request("/v1/models", key)
            if request("/health", key).get("status") == "ok":
                break
        except OSError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("Router/upstream did not become ready before benchmark")

    def emit(row):
        row.update({"label": args.label, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        text = json.dumps(row, ensure_ascii=False)
        with out.open("a") as stream:
            stream.write(text + "\n")
        print(text, flush=True)

    emit({"kind": "metadata", "prompt": PROMPT, "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
          "router_sha256": hashlib.sha256(pathlib.Path("/opt/ia/router.py").read_bytes()).hexdigest(),
          "kernel": subprocess.check_output(["uname", "-sr"], text=True).strip(), "reps": args.reps})
    if args.mode == "text":
        for rep in range(1, args.reps + 1):
            for model in args.models:
                loaded = request("/v1/models", key)["data"]
                if any(row["id"] == model and row.get("loaded") for row in loaded):
                    away = next(name for name in MODELS if name != model)
                    request("/v1/chat/completions", key, chat(away, [{"role": "user", "content": "hi"}], 1))
                # Preserve old saved state, but do not let a saved prefix contaminate cold prefill.
                for slot in pathlib.Path("/var/lib/llama-slots").glob(model + "-*.bin"):
                    slot.rename(out.parent / f"{args.label}-{rep}-{slot.name}")
                for state in ("cold", "warm"):
                    row, _ = measure("/v1/chat/completions", key, chat(model, [{"role": "user", "content": PROMPT}]))
                    row.update({"kind": "text", "model": model, "rep": rep, "state": state})
                    emit(row)
    else:
        if not args.corpus:
            parser.error("--corpus is required for image checks")
        corpus = pathlib.Path(args.corpus).read_text()
        corpus = (corpus * (70000 // max(1, len(corpus)) + 1))[:70000]
        messages = [{"role": "user", "content": "Read this reference, then acknowledge briefly.\n" + corpus}]
        model = "qwen2.5-7b-instruct-q4_k_m"
        emit({"kind": "corpus", "sha256": hashlib.sha256(corpus.encode()).hexdigest(), "chars": len(corpus)})
        for image in ("sd15", "sd35"):
            row, _ = measure("/v1/chat/completions", key, chat(model, messages, 32))
            emit({**row, "kind": "prime", "image_model": image})
            row, body = measure("/v1/chat/completions", key, {"model": image, "steps": 20,
                                "messages": [{"role": "user", "content": "a red fox figurine on a wooden desk, soft studio lighting, 35mm photo"}]})
            url = re.search(r"!\[.*?\]\((.*?)\)", body["choices"][0]["message"]["content"]).group(1)
            with urllib.request.urlopen(url, timeout=20) as response:
                png = response.read()
            assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (512, 512)
            emit({**row, "kind": "image", "model": image, "png_bytes": len(png),
                  "png_sha256": hashlib.sha256(png).hexdigest()})
            # Wait until the restarted server is healthy: exercise deferred cache restoration too.
            for _ in range(90):
                try:
                    if request("/health", key).get("status") == "ok":
                        break
                except OSError:
                    pass
                time.sleep(1)
            row, _ = measure("/v1/chat/completions", key, chat(model, messages, 32))
            status = subprocess.run(["systemctl", "is-active", "sd-server", "sd-server-sd15"],
                                    capture_output=True, text=True, check=False).stdout.split()
            emit({**row, "kind": "after_image", "image_model": image, "image_units": status})


if __name__ == "__main__":
    main()

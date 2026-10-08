#!/usr/bin/env python3
"""A/B of the KV slot cache across llama-server restarts.

Runs ON the CT, against the router on localhost. It needs root because the
"without" arm deletes the saved slot files — that is the whole A/B: same
prompt, same model, same restart, with and without the file on disk.

Two paths, each measured both ways:

  swap   7b loaded → request another model (router saves 7b and stops the
         server) → request 7b again with the long prompt
  image  7b loaded → generate an image (router saves 7b and stops the server
         to free VRAM) → request 7b again with the long prompt

    sudo python3 scripts/bench-slots.py --corpus docs/*.md router.py
    sudo python3 scripts/bench-slots.py --reps 3 --out /root/bench-slots.jsonl

Every request is printed as one JSON line, then a summary table.
"""
import argparse
import glob
import json
import os
import statistics
import time
import urllib.request

API = "http://127.0.0.1:8090"
SLOT_DIR = "/var/lib/llama-slots/"
MODEL = "qwen2.5-7b-instruct-q4_k_m"
AWAY = "qwen2.5-coder-1.5b-instruct-q4_k_m"
IMAGE_MODEL = "sd15"


def api_key():
    env = os.environ.get("IA_API_KEY")
    if env:
        return env
    with open("/etc/ia/api-key") as f:
        return f.read().strip()


def post(path, payload, key, timeout=1800):
    req = urllib.request.Request(
        API + path, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.load(r)
    return time.monotonic() - t0, body


def chat(model, messages, key, max_tokens=32):
    wall, body = post("/v1/chat/completions", {
        "model": model, "messages": messages,
        "temperature": 0, "max_tokens": max_tokens}, key)
    usage = body.get("usage", {})
    timings = body.get("timings", {})
    return {
        "wall_s": round(wall, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        "prompt_n": timings.get("prompt_n"),
        "prompt_s": round(timings.get("prompt_ms", 0) / 1000, 2),
        "decode_s": round(timings.get("predicted_ms", 0) / 1000, 2),
    }


def drop_slot_files(model):
    """The "without" arm: whatever the router saved for `model` is gone."""
    removed = 0
    for path in glob.glob(f"{SLOT_DIR}{model}-*.bin"):
        os.remove(path)
        removed += 1
    return removed


def slot_bytes(model):
    return sum(os.path.getsize(p) for p in glob.glob(f"{SLOT_DIR}{model}-*.bin"))


def build_messages(corpus, chars):
    text = ""
    for path in corpus:
        with open(path, encoding="utf-8", errors="replace") as f:
            text += f"\n\n=== {os.path.basename(path)} ===\n" + f.read()
    while len(text) < chars:  # a short corpus is repeated, never padded with noise
        text += text
    return [
        {"role": "system", "content": "You are a code reviewer. Reference material:\n"
                                      + text[:chars]},
        {"role": "user", "content": "In one sentence: what does router.py do?"},
    ]


def run_arm(path, keep, messages, key, rep):
    """One measurement. The model must already be loaded and warm."""
    if path == "swap":
        chat(AWAY, [{"role": "user", "content": "hi"}], key, max_tokens=4)
    else:
        # Unique prompt: the router caches images by prompt for 5 min, and a
        # cache hit never stops llama-server.
        post("/v1/chat/completions", {
            "model": IMAGE_MODEL, "steps": 4,
            "messages": [{"role": "user", "content": f"a red cube #{time.time_ns()}"}]},
            key)
    saved = slot_bytes(MODEL)
    dropped = 0 if keep else drop_slot_files(MODEL)
    row = chat(MODEL, messages, key)
    row.update({"path": path, "slot_file": "kept" if keep else "deleted",
                "rep": rep, "saved_mb": round(saved / 2**20), "files_dropped": dropped})
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--corpus", nargs="+", required=True,
                   help="text files that make up the long prompt")
    p.add_argument("--chars", type=int, default=70000,
                   help="prompt size in characters (~20k tokens at the default)")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--paths", nargs="+", default=["swap", "image"],
                   choices=["swap", "image"])
    p.add_argument("--out", help="also append every row to this JSONL file")
    args = p.parse_args()

    key = api_key()
    messages = build_messages(args.corpus, args.chars)
    rows = []

    def emit(row):
        rows.append(row)
        line = json.dumps(row)
        print(line, flush=True)
        if args.out:
            with open(args.out, "a") as f:
                f.write(line + "\n")

    # Load the model and pay the long prefill once, so every arm starts warm.
    drop_slot_files(MODEL)
    first = chat(MODEL, messages, key)
    first.update({"path": "first-request", "slot_file": "none", "rep": 0})
    emit(first)

    for rep in range(1, args.reps + 1):
        for path in args.paths:
            # "deleted" first: its full prefill leaves the KV warm again, which
            # is exactly the state the "kept" arm needs to start from.
            for keep in (False, True):
                emit(run_arm(path, keep, messages, key, rep))

    print()
    print(f"{'path':<6} {'slot file':<8} {'n':>2} {'wall s (median)':>16} "
          f"{'prefill tok':>12} {'cached tok':>11}")
    for path in args.paths:
        for label in ("deleted", "kept"):
            sel = [r for r in rows if r["path"] == path and r["slot_file"] == label]
            if not sel:
                continue
            print(f"{path:<6} {label:<8} {len(sel):>2} "
                  f"{statistics.median(r['wall_s'] for r in sel):>16.1f} "
                  f"{statistics.median(r['prompt_n'] or 0 for r in sel):>12.0f} "
                  f"{statistics.median(r['cached_tokens'] or 0 for r in sel):>11.0f}")


if __name__ == "__main__":
    main()

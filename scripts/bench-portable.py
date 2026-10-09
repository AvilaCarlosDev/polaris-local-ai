#!/usr/bin/env python3
"""Warm decode benchmark for the portable stack (llama-server on localhost).

Runs against the portable router (default 127.0.0.1:8091), one warm-up
request per model followed by N timed requests. Prints one JSON object per
line, ready to append to docs/evidence/.

    python3 scripts/bench-portable.py cpu-ram-normal \
        qwen2.5-coder-1.5b-instruct-q4_k_m qwen2.5-vl-3b-instruct-q4_k_m
"""
import argparse
import json
import pathlib
import time
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8091/v1/chat/completions"
KEY_PATH = pathlib.Path.home() / ".config/polaris-portable/api-key"
PROMPT = "Escribe un párrafo corto sobre por qué la memoria local importa."


def ask(base, key, model, max_tokens):
    """One chat completion; returns (wall seconds, llama-server timings)."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(base, data=body, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read())
    return time.monotonic() - start, data.get("timings", {})


def main():
    """Parse args, warm up each model, then print the timed rows."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label", help="configuration label, e.g. cpu-ram-normal")
    parser.add_argument("models", nargs="+", help="model preset names to measure")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=150)
    args = parser.parse_args()

    key = KEY_PATH.read_text().strip()
    for model in args.models:
        wall, _ = ask(args.base, key, model, 8)
        print(json.dumps({
            "etiqueta": args.label, "modelo": model,
            "fase": "carga", "wall_s": round(wall, 2),
        }), flush=True)
        for rep in range(args.reps):
            wall, timings = ask(args.base, key, model, args.max_tokens)
            print(json.dumps({
                "etiqueta": args.label,
                "modelo": model,
                "fase": "warm",
                "rep": rep,
                "wall_s": round(wall, 2),
                "prompt_n": timings.get("prompt_n"),
                "predicted_n": timings.get("predicted_n"),
                "tok_s": timings.get("predicted_per_second"),
            }), flush=True)


if __name__ == "__main__":
    main()

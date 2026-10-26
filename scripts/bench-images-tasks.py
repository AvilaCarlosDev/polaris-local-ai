#!/usr/bin/env python3
"""Image models on everyday tasks: SD 3.5 Medium vs SD 1.5, default vs tuned.

Goes through the router (model "sd35" / "sd15" on /v1/chat/completions), the
same path clients use, so the router keeps doing the VRAM hand-off with the
LLM. Extra generation params travel in <sd_cpp_extra_args>, which the router
passes through untouched. Fixed seed per task so variants are comparable.

    python3 scripts/bench-images-tasks.py --out DIR [--only sd35]

Hold the ia-local lock while it runs. Prints one JSON line per image and
downloads every PNG to DIR for review.
"""

import argparse
import json
import os
import re
import time
import urllib.request

ROUTER = os.environ.get("IA_ROUTER", "http://100.97.88.59:8090")

TASKS = {
    "producto": "product photo of a white ceramic coffee mug on a wooden table, "
    "morning window light, shallow depth of field",
    "retrato": "portrait of a smiling female doctor in a white coat in a bright "
    "modern clinic, professional photo",
    "texto": "minimalist flat logo, the word POLARIS in bold sans-serif letters, "
    "white background",
    "ilustracion": "flat vector illustration of a laptop with growth charts and a "
    "rocket, pastel colors, social media banner",
    "paisaje": "caribbean beach at sunset with palm trees, golden hour, wide shot",
}

NEG_SD15 = "blurry, lowres, deformed, bad anatomy, extra fingers, watermark, text"
NEG_SD35 = "blurry, lowres, deformed, watermark"

# (model, variant) -> extra args. "base" is what clients get today.
VARIANTS = {
    ("sd15", "base"): {},
    ("sd15", "mejora"): {"negative_prompt": NEG_SD15, "steps": 30},
    ("sd35", "base"): {},
    ("sd35", "mejora"): {
        "negative_prompt": NEG_SD35,
        "steps": 28,
        "width": 768,
        "height": 768,
    },
}
SEED = 42


def key():
    for line in open(os.path.expanduser("~/.config/ia/secrets.env")):
        if line.startswith("IA_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("IA_API_KEY missing")


def run(model, task, extra, api_key):
    args = {"seed": SEED, **extra}
    prompt = (
        TASKS[task] + " <sd_cpp_extra_args>" + json.dumps(args) + "</sd_cpp_extra_args>"
    )
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "steps": extra.get("steps", 20),
            "name": f"bench-{task}",
        }
    ).encode()
    req = urllib.request.Request(
        f"{ROUTER}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1200) as r:
        text = json.load(r)["choices"][0]["message"]["content"]
    secs = time.time() - t0
    m = re.search(r"/img/([^\s)]+\.png)", text)
    return secs, (m.group(1) if m else None), text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    api_key = key()
    for (model, variant), extra in VARIANTS.items():
        if a.only and model != a.only:
            continue
        for task in TASKS:
            row = {"modelo": model, "variante": variant, "tarea": task, **extra}
            row.pop("negative_prompt", None)
            try:
                secs, fn, text = run(model, task, extra, api_key)
                row.update(s=round(secs, 1), archivo=fn)
                if fn:
                    dst = os.path.join(a.out, f"{model}-{variant}-{task}.png")
                    urllib.request.urlretrieve(f"{ROUTER}/img/{fn}", dst)
                else:
                    row["respuesta"] = text[:200]
            except Exception as e:
                row["error"] = repr(e)[:200]
            print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

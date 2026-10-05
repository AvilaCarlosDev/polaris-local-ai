#!/usr/bin/env bash
# Hero demo for the README. Every command here hits the live stack — no faked
# output, no canned answers. Recording: asciinema rec -c ./demo.sh
set -euo pipefail

REPO="${IA_REPO:-$HOME/polaris-local-ai}"
export PATH="$REPO/clients:$PATH"
API="${IA_API:-http://100.97.88.59:8090}"
SECRETS="${IA_SECRETS:-$HOME/.config/ia/secrets.env}"
# shellcheck disable=SC1090
. "$SECRETS"
KEY="${IA_KEY:-$IA_API_KEY}"

BOLD=$'\033[1m'; CYAN=$'\033[36m'; GREEN=$'\033[32m'; DIM=$'\033[2m'; OFF=$'\033[0m'

step() { printf '\n%s▶%s %s\n' "$CYAN" "$OFF" "$*"; }
done_in() {
  python3 -c "import sys; print(f'  ${DIM}({(int(sys.argv[2])-int(sys.argv[1]))/1e9:.1f} s)${OFF}')" "$1" "$2"
}

printf '%spolaris-local-ai — live demo%s\n' "$BOLD" "$OFF"
printf '%sone endpoint, local models, no cloud%s\n' "$DIM" "$OFF"

step "what the router serves, grouped by category"
ia-models

step "chat completion (warm model)"
t0=$(date +%s%N)
curl -sS --max-time 120 "$API/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"qwen2.5-7b-instruct-q4_k_m",
       "messages":[{"role":"user","content":"In one sentence: what is the trade-off of running an LLM locally instead of calling a cloud API?"}]}' \
  -o /tmp/hero-chat.json
t1=$(date +%s%N)
python3 -c 'import json; d = json.load(open("/tmp/hero-chat.json"))["choices"][0]["message"]["content"]; print("  " + d)'
done_in "$t0" "$t1"

step "image generation (SD 3.5 Medium, 20 steps)"
# Unique name: the router caches by name, and a repeated one would answer in
# milliseconds instead of actually generating.
name="fox-hero-$(date +%H%M%S)"
prompt="a red fox figurine on a brass mechanical keyboard, soft studio lighting, 35mm"
# Heartbeat so the ~70 s of GPU work is visible instead of a frozen screen.
( s=0; while :; do sleep 3; s=$((s + 3)); printf '  waiting… %ss\n' "$s"; done ) &
HB=$!
t0=$(date +%s%N)
url=$(ia-imagen "$prompt" "$name")
t1=$(date +%s%N)
kill "$HB" 2>/dev/null || true
wait "$HB" 2>/dev/null || true
done_in "$t0" "$t1"
# ia-imagen appends -sd35-<time> to the name, so list what it actually wrote.
ls -la "${IA_IMG_DIR:-$HOME/Imagens-IA}/${url##*/}"

printf '\n%s✓ everything above ran on this machine%s\n' "$GREEN" "$OFF"

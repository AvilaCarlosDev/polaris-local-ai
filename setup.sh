#!/usr/bin/env bash
# polaris-local-ai installer.
#
# Reproduces the stack on a Debian/Ubuntu host with an AMD card that RADV
# supports (Polaris through RDNA) and enough RAM to hold the models.
#
#   ./setup.sh            install everything that is missing, start the stack
#   ./setup.sh --check    report only; change nothing
#   ./setup.sh --no-start install but do not enable/start the units
#
# It never downloads model weights. See docs/MODELS.md for where they come from.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="/opt/ia/models"
IA_DIR="/opt/ia"
LLAMA_DIR="/opt/llama.cpp"
SD_DIR="/opt/stable-diffusion.cpp"
WHISPER_DIR="/opt/whisper.cpp"
WHISPER_MODEL="$MODELS_DIR/ggml-medium.bin"
KEY_FILE="/etc/ia/api-key"
UNIT_DIR="/etc/systemd/system"
# Python entrypoints deployed to $IA_DIR. The units run them from there, so
# this list and systemd/ have to stay in sync (see tests/test_units.py).
ENTRYPOINTS=(router.py image-mcp.py)
MIN_RAM_GB=16
MIN_DISK_GB=40

CHECK_ONLY=0
DO_START=1
for arg in "$@"; do
  case "$arg" in
    --check)    CHECK_ONLY=1 ;;
    --no-start) DO_START=0 ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 && $CHECK_ONLY -eq 0 ]]; then
  echo "run as root (sudo ./setup.sh), or use --check" >&2
  exit 1
fi

GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; R=$'\033[0m'
PASS=0; FAIL=0; WARN=0
ok()   { echo "  ${GREEN}✓${R} $*"; PASS=$((PASS+1)); }
bad()  { echo "  ${RED}✗${R} $*"; FAIL=$((FAIL+1)); }
warn() { echo "  ${YELLOW}⚠${R} $*"; WARN=$((WARN+1)); }
hdr()  { echo; echo "${BOLD}$*${R}"; }

echo "${BOLD}polaris-local-ai — preflight${R}"

# ── 1. OS and build tools ──────────────────────────────────────────────────
hdr "System"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  ok "$PRETTY_NAME"
else
  warn "cannot read /etc/os-release"
fi

for t in git cmake g++ python3 curl; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t found"; else
    if [[ $CHECK_ONLY -eq 1 ]]; then bad "$t missing"; else
      warn "$t missing — installing"
      apt-get update -qq && apt-get install -y -qq git cmake g++ python3 curl
      ok "$t installed"
    fi
  fi
done

# ── 2. GPU: must be a card RADV supports ───────────────────────────────────
hdr "Graphics"
GPU_NAME=""
if command -v lspci >/dev/null 2>&1; then
  GPU_NAME="$(lspci 2>/dev/null | grep -i 'vga\|3d controller' | head -1 | sed 's/.*: //')"
  [[ -n "$GPU_NAME" ]] && ok "GPU: $GPU_NAME"
fi

if command -v vulkaninfo >/dev/null 2>&1 && vulkaninfo --summary >/dev/null 2>&1; then
  DEV="$(vulkaninfo --summary 2>/dev/null | grep -m1 'deviceName' | sed 's/.*= *//')"
  ok "Vulkan device: ${DEV:-unknown}"
else
  if [[ $CHECK_ONLY -eq 1 ]]; then
    bad "vulkaninfo unavailable — install vulkan-tools to verify the driver"
  else
    warn "installing vulkan-tools"
    apt-get install -y -qq vulkan-tools mesa-vulkan-drivers >/dev/null 2>&1 || true
    if vulkaninfo --summary >/dev/null 2>&1; then
      ok "Vulkan available"
    else
      bad "no usable Vulkan device — this stack needs RADV (mesa-vulkan-drivers)"
    fi
  fi
fi

case "${GPU_NAME,,}" in
  *"polaris"*|*"rx 5[5-9]0"*|*"rx 4[7-8]0"*|*"radeon"*|*"amd/ati"*)
    ok "AMD card detected — RADV path applies" ;;
  *"nvidia"*|*"geforce"*)
    warn "NVIDIA card: llama.cpp will use CUDA, not the RADV path documented here" ;;
  *)
    warn "unrecognised GPU — check docs/HARDWARE.md before continuing" ;;
esac

# ── 3. RAM and disk ────────────────────────────────────────────────────────
hdr "Memory and storage"
RAM_GB="$(awk '/^MemTotal:/{printf "%d", $2/1024/1024}' /proc/meminfo)"
if (( RAM_GB >= MIN_RAM_GB )); then
  ok "RAM ${RAM_GB} GB (minimum ${MIN_RAM_GB} GB)"
else
  bad "RAM ${RAM_GB} GB < ${MIN_RAM_GB} GB — models will not fit"
fi

AVAIL_GB="$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -dc '0-9')"
if [[ -n "$AVAIL_GB" ]] && (( AVAIL_GB >= MIN_DISK_GB )); then
  ok "disk ${AVAIL_GB} GB free (minimum ${MIN_DISK_GB} GB for models)"
else
  warn "only ${AVAIL_GB:-?} GB free — you may not have room for every model"
fi

# ── 4. Engines ─────────────────────────────────────────────────────────────
hdr "Engines"
build_llama() {
  if [[ $CHECK_ONLY -eq 1 ]]; then bad "llama.cpp not built at $LLAMA_DIR"; return; fi
  warn "cloning and building llama.cpp (this takes a while)"
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
  cmake -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" -DCMAKE_BUILD_TYPE=Release \
        -DGGML_VULKAN=ON >/dev/null
  cmake --build "$LLAMA_DIR/build" --config Release -j "$(nproc)" >/dev/null
  ok "llama.cpp built with Vulkan"
}
build_sd() {
  if [[ $CHECK_ONLY -eq 1 ]]; then bad "stable-diffusion.cpp not built at $SD_DIR"; return; fi
  warn "cloning and building stable-diffusion.cpp"
  git clone --depth 1 https://github.com/leejet/stable-diffusion.cpp.git "$SD_DIR"
  cmake -S "$SD_DIR" -B "$SD_DIR/build" -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release >/dev/null
  cmake --build "$SD_DIR/build" -j "$(nproc)" >/dev/null
  ok "stable-diffusion.cpp built with Vulkan"
}
build_whisper() {
  # Audio runs on the CPU: no Vulkan here, and no point building it on a host
  # that does not have the .bin weights.
  if [[ $CHECK_ONLY -eq 1 ]]; then bad "whisper.cpp not built at $WHISPER_DIR"; return; fi
  warn "cloning and building whisper.cpp (CPU)"
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$WHISPER_DIR"
  cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build" -DCMAKE_BUILD_TYPE=Release \
        -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=OFF >/dev/null
  cmake --build "$WHISPER_DIR/build" -j "$(nproc)" >/dev/null
  ok "whisper.cpp built"
}

if [[ -x "$LLAMA_DIR/build/bin/llama-server" ]]; then
  ok "llama-server present"
else
  build_llama
fi
if [[ -x "$SD_DIR/build/bin/sd-server" ]]; then
  ok "sd-server present"
else
  build_sd
fi
# whisper is tied to its weights: without ggml-medium.bin the unit would be
# installed into a crash loop, and the router would advertise an audio id with
# nothing behind it. No model, no audio category.
if [[ -f "$WHISPER_MODEL" ]]; then
  if [[ -x "$WHISPER_DIR/build/bin/whisper-server" ]]; then
    ok "whisper-server present"
  else
    build_whisper
  fi
else
  warn "no $WHISPER_MODEL — skipping whisper.cpp and the audio category"
fi

# ── 5. Model weights ───────────────────────────────────────────────────────
hdr "Model weights"
if [[ -d "$MODELS_DIR" ]] && compgen -G "$MODELS_DIR/*.gguf" >/dev/null; then
  ok "$(find "$MODELS_DIR" -name '*.gguf' | wc -l) gguf file(s) in $MODELS_DIR"
else
  warn "no weights in $MODELS_DIR — download them yourself, see docs/MODELS.md"
fi
if [[ -f "$WHISPER_MODEL" ]]; then
  ok "audio weight present: ggml-medium.bin"
else
  warn "no ggml-medium.bin in $MODELS_DIR — audio stays disabled (see docs/MODELS.md)"
fi

# ── 6. API key ─────────────────────────────────────────────────────────────
hdr "API key"
if [[ -s "$KEY_FILE" ]]; then
  ok "key already present at $KEY_FILE"
else
  if [[ $CHECK_ONLY -eq 1 ]]; then
    warn "no key yet — a random one will be generated at install time"
  else
    install -d -m 0755 "$(dirname "$KEY_FILE")"
    head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40 > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    ok "generated key at $KEY_FILE"
  fi
fi

# ── 7. Units ───────────────────────────────────────────────────────────────
hdr "Systemd units"
if [[ $CHECK_ONLY -eq 1 ]]; then
  for u in "$ROOT"/systemd/*.service; do
    name="$(basename "$u")"
    if [[ "$name" == "whisper-server.service" && ! -f "$WHISPER_MODEL" ]]; then
      warn "$name skipped — no $WHISPER_MODEL"
    elif [[ -e "$UNIT_DIR/$name" ]]; then
      ok "$name installed"
    else
      warn "$name not installed"
    fi
  done
else
  for u in "$ROOT"/systemd/*.service; do
    name="$(basename "$u")"
    # Same rule as the engine above: no weight, no unit. Installing it would
    # only produce a crash loop and an audio id with no backend.
    if [[ "$name" == "whisper-server.service" && ! -f "$WHISPER_MODEL" ]]; then
      warn "$name skipped — no $WHISPER_MODEL"
      continue
    fi
    # The key placeholder keeps secrets out of the repository. Substitute it
    # from the real key file at install time — never commit the real value.
    sed "s|__IA_API_KEY__|$(cat "$KEY_FILE")|g" "$u" > "$UNIT_DIR/$name"
    ok "$name installed"
  done
  systemctl daemon-reload
fi

# ── 8. Python entrypoints ───────────────────────────────────────────────────
# The units run these from /opt/ia, which does not exist on a clean host —
# without this step nothing ever listens on 8090.
hdr "Application"
for script in "${ENTRYPOINTS[@]}"; do
  if [[ $CHECK_ONLY -eq 1 ]]; then
    if [[ -e "$IA_DIR/$script" ]]; then ok "$script installed"; else
      warn "$script not installed yet"
    fi
  else
    install -D -m 0755 "$ROOT/$script" "$IA_DIR/$script"
    ok "$script installed to $IA_DIR"
  fi
done

# ── 8. Start ───────────────────────────────────────────────────────────────
if [[ $CHECK_ONLY -eq 0 && $DO_START -eq 1 ]]; then
  hdr "Starting"
  START_UNITS=(llama-server router sd-server-sd15)
  if [[ -f "$WHISPER_MODEL" ]]; then START_UNITS+=(whisper-server); fi
  for s in "${START_UNITS[@]}"; do
    systemctl enable --now "$s.service" >/dev/null 2>&1 || true
    if systemctl is-active --quiet "$s.service"; then ok "$s running"; else
      warn "$s did not start — see docs/TROUBLESHOOTING.md"
    fi
  done
  # sd-server (SD 3.5) shares port 8082 with sd-server-sd15; the router starts
  # whichever one the request needs. Leave both enabled, not both running.
  systemctl enable sd-server.service >/dev/null 2>&1 || true
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo
echo "${BOLD}────────────────────────────────────────${R}"
echo "  ${GREEN}passed${R} $PASS   ${YELLOW}warnings${R} $WARN   ${RED}failed${R} $FAIL"
if (( FAIL > 0 )); then
  echo "  fix the failures above before starting the stack."
  exit 1
fi
if (( CHECK_ONLY == 1 )); then
  echo "  everything checks out. Run sudo ./setup.sh to install."
else
  echo "  router: http://127.0.0.1:8090/v1  (key: $KEY_FILE)"
  echo "  next:   docs/MODELS.md for the model list, docs/HERMES.md for the agent"
fi
echo "${BOLD}────────────────────────────────────────${R}"

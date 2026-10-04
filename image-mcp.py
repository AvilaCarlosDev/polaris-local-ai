#!/usr/bin/env python3
"""MCP stdio server: genera imagenes con stable-diffusion.cpp en la RX 580.

Existe porque la VRAM no alcanza para LLM e imagen simultaneamente: este tool
para llama-server, genera, y lo restaura. El router (puerto 8090) se
autorrepara en el proximo request porque su ensure() valida /health.

Corre DENTRO del LXC (necesita systemctl para la VRAM). opencode lo invoca por
ssh, igual que el MCP de Engram.
"""
import base64, json, os, pathlib, socket, subprocess, sys, time, urllib.request

SD = "http://127.0.0.1:8082"
OUT = pathlib.Path("/opt/ia/images")
PROTO = "2024-11-05"

TOOLS = [{
    "name": "generate_image",
    "description": (
        "Genera una imagen a partir de un prompt usando stable-diffusion.cpp en la "
        "GPU local (SD 1.5, 512x512 por defecto). Libera la VRAM del LLM mientras "
        "genera y lo restaura despues, así que puede tardar ~30s. Para ver la imagen "
        "despues de generarla, el usuario debe estar usando el modelo de vision "
        "(qwen2.5-vl-3b)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Descripcion de la imagen a generar"},
            "steps": {"type": "integer", "description": "Pasos de difusion (default 20, max 40)",
                      "default": 20, "minimum": 1, "maximum": 40},
            "width": {"type": "integer", "description": "Ancho en px (default 512)",
                      "default": 512},
            "height": {"type": "integer", "description": "Alto en px (default 512)",
                       "default": 512},
            "name": {"type": "string", "description": "Nombre del archivo, sin extension"},
            "return_image": {
                "type": "boolean",
                "description": "Si es true, adjunta la imagen al resultado (solo util "
                               "si el modelo activo tiene vision). Default false.",
                "default": False,
            },
        },
        "required": ["prompt"],
    },
}]


def log(msg):
    sys.stderr.write(f"[image-mcp] {msg}\n")
    sys.stderr.flush()


def sd_up():
    try:
        with socket.create_connection(("127.0.0.1", 8082), timeout=5):
            return True
    except OSError:
        return False


def generate(prompt, steps, width, height, name, return_image):
    was_up = subprocess.run(["systemctl", "is-active", "llama-server"],
                            capture_output=True, text=True).stdout.strip()
    if was_up == "active":
        log("liberando VRAM")
        subprocess.run(["systemctl", "stop", "llama-server"], capture_output=True)
        time.sleep(2)
    try:
        if not sd_up():
            subprocess.run(["systemctl", "start", "sd-server"], capture_output=True)
            for _ in range(60):
                if sd_up():
                    break
                time.sleep(1)
            if not sd_up():
                return {"content": [{"type": "text", "text": "ERROR: sd-server no levanto"}]}, True

        payload = json.dumps({"prompt": prompt, "steps": steps,
                              "width": width, "height": height}).encode()
        req = urllib.request.Request(f"{SD}/v1/images/generations", data=payload,
                                     headers={"Content-Type": "application/json"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=900) as r:
            d = json.load(r)
        img = d["data"][0]
        raw = base64.b64decode(img["b64_json"]) if "b64_json" in img else \
            urllib.request.urlopen(img["url"], timeout=60).read()
        secs = time.time() - t0

        OUT.mkdir(parents=True, exist_ok=True)
        fname = name or f"img-{time.strftime('%Y%m%d-%H%M%S')}"
        path = OUT / f"{fname}.png"
        path.write_bytes(raw)

        text = (f"Imagen generada: {path} ({len(raw)//1024} KB, {secs:.1f}s, "
                f"{steps} steps, {width}x{height})\n"
                f"Para verla, cambia al modelo de vision: /models -> "
                f"qwen2.5-vl-3b-instruct-q4_k_m")
        content = [{"type": "text", "text": text}]
        if return_image:
            content.append({"type": "image",
                            "data": base64.b64encode(raw).decode(),
                            "mimeType": "image/png"})
        return {"content": content}, False
    except Exception as e:
        return {"content": [{"type": "text", "text": f"ERROR generando imagen: {e}"}]}, True
    finally:
        if was_up == "active":
            log("restaurando LLM")
            subprocess.run(["systemctl", "start", "llama-server"], capture_output=True)


def respond(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        mid = msg.get("id")

        if method == "initialize":
            respond({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": PROTO,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ia-image", "version": "1.0.0"},
                "instructions": "Tool de generacion de imagenes local (stable-diffusion.cpp, Vulkan).",
            }})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            respond({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            args = (msg.get("params") or {}).get("arguments") or {}
            prompt = (args.get("prompt") or "").strip()
            if not prompt:
                respond({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": "Falta el prompt"}]}, "isError": True})
                continue
            log(f"generando: {prompt[:60]}")
            result, is_err = generate(
                prompt,
                int(args.get("steps", 20)),
                int(args.get("width", 512)),
                int(args.get("height", 512)),
                args.get("name"),
                bool(args.get("return_image", False)),
            )
            respond({"jsonrpc": "2.0", "id": mid, "result": result, "isError": is_err})
        elif method == "ping":
            respond({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            respond({"jsonrpc": "2.0", "id": mid,
                     "error": {"code": -32601, "message": f"method {method} no soportada"}})


if __name__ == "__main__":
    main()

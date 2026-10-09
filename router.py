#!/usr/bin/env python3
"""Router HTTP single-binary para llama-server con VRAM limitada.

Lee el campo "model" de cada request; si no es el que ya esta cargado, recarga
el server con el pedido y recien entonces reenvia. Si ya esta cargado, reenvia
directo (overhead ~0).
"""
import http.client
import json
import os
import re
import select
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

UPSTREAM = "http://127.0.0.1:8080"
UPSTREAM_ADDR = ("127.0.0.1", 8080)
# Techo de salida para requests que no traen max_tokens. Hermes manda el
# resumen de compresion SIN tope a proposito, y ornith llego a generar 9.898
# tokens (552 s) en un resumen que debia ocupar ~3.000: el slot y el lock del
# router quedaron tomados 10 min. 0 lo desactiva.
# No bajarlo de 16384: Hermes pide resumenes de hasta 10K tokens y descarta
# el que termina en finish_reason=length. Con 4096 ornith se gasto el tope
# razonando (15K caracteres) y la compresion fallo. Lo que corta un pedido
# abandonado es forward_live(), no este tope.
DEFAULT_MAX_TOKENS = int(os.environ.get("IA_DEFAULT_MAX_TOKENS", "16384"))
# Headers hop-by-hop: los maneja cada conexion, no se reenvian.
HOP_HEADERS = {"host", "content-length", "connection", "accept-encoding",
               "transfer-encoding", "keep-alive"}


def _load_api_key():
    """La key NO va hardcodeada: leerla de un archivo 600 evita que al desplegar
    el codigo del router se pise una key ya rotada (me paso, genero 401)."""
    env = os.environ.get("IA_API_KEY")
    if env:
        return env
    for path in ("/root/.ia-secrets", "/etc/ia/api-key"):
        try:
            with open(path) as f:
                val = f.read().strip()
            if val:
                return val
        except OSError:
            continue
    return "ia-local-2026"


API_KEY = _load_api_key()
M = "/opt/ia/models"
MMPROJ = f"{M}/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"
CTX = "65536"
BIN = "/opt/llama.cpp/build/bin/llama-server"
# Estado persistente en /var/lib y no en /run: si el router se reinicia
# (deploy, crash) con llama-server corriendo, /run quedo vacio y current()
# devolvia "" — slots_save() se saltaba el save y se perdia el KV caliente.
STATE = "/var/lib/llama-router/model"
# --slot-save-path: el KV cache de cada slot se vuelca a disco antes de cada
# reinicio del server (swap de modelo o liberar VRAM para SD) y se restaura al
# volver. /var/lib y no /run: /run es tmpfs y se pierde en cada reboot del LXC.
SLOT_DIR = "/var/lib/llama-slots/"
# Marca cuando llama-server se reinicio fuera de load() (generate_image): recien
# ahi hay un server sano donde restaurar. threading.Event en vez de `global`
# porque ruff PLW0603 prohíbe la sentencia global.
_restore_pending = threading.Event()

MODELS = {
    "qwen2.5-7b-instruct-q4_k_m":        f"{M}/qwen2.5-7b-instruct-q4_k_m.gguf",
    "qwen2.5-coder-7b-instruct-q4_k_m":  f"{M}/qwen2.5-coder-7b-instruct-q4_k_m.gguf",
    "qwen2.5-coder-1.5b-instruct-q4_k_m": f"{M}/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
    "qwen2.5-vl-3b-instruct-q4_k_m":     f"{M}/qwen2.5-vl-3b-instruct-q4_k_m.gguf",
    "ornith-1.5-9b-q4_k_m":                "/var/cache/ai/models/Ornith-1.5-9B-Q4_K_M.gguf",
    "qwen3-30b-a3b-instruct-2507-q4_k_m": "/var/cache/ai/models/Qwen_Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf",
}
ALIASES = {"fast": "qwen2.5-coder-1.5b-instruct-q4_k_m",
           "code": "qwen2.5-coder-7b-instruct-q4_k_m",
           "vision": "qwen2.5-vl-3b-instruct-q4_k_m",
           "general": "qwen2.5-7b-instruct-q4_k_m",
           "ornith": "ornith-1.5-9b-q4_k_m"}

# Selector por categoria. Un modelo cae en UNA sola: es lo que el usuario ve
# primero, asi que la categoria no puede ser ambigua. Orden = orden de salida.
CATEGORY_ORDER = ("texto", "vision", "multitarea", "imagen", "audio")
CATEGORY_OF = {
    "qwen2.5-coder-1.5b-instruct-q4_k_m": "texto",
    "qwen2.5-7b-instruct-q4_k_m": "texto",
    "qwen2.5-coder-7b-instruct-q4_k_m": "texto",
    "ornith-1.5-9b-q4_k_m": "texto",
    "qwen2.5-vl-3b-instruct-q4_k_m": "vision",
    "qwen3-30b-a3b-instruct-2507-q4_k_m": "multitarea",
}
# Audio no pasa por el router: whisper-server vive en su propio puerto y expone
# /inference (no la ruta OpenAI /v1/audio/transcriptions, que da 404 en esta
# build). Se anuncia igual para que el selector muestre las cinco categorias.
AUDIO_ID = "whisper-medium"
AUDIO_INFO = {"port": 8081, "path": "/inference"}

# Flags por modelo. El template por defecto fija "-ngl 99 --threads 4", que con
# el MoE de 18.6 GB llena la VRAM al 99.4% y hace thrashing (medido: 8.12 tok/s
# con -ngl 99 contra 22.26 con auto-fit). Sin -ngl, llama.cpp calcula sola cuantas
# capas caben y deja ~1 GiB de headroom para el KV cache.
MODEL_ARGS = {
    "qwen3-30b-a3b-instruct-2507-q4_k_m": (
        "--host 0.0.0.0 --port 8080 -ub 512 "
        "-c 65536 --parallel 1 --threads 6 "
        "--cache-type-k q8_0 --cache-type-v q8_0 --cache-reuse 4096 "
    ),
}

# Modelo de imagen: el usuario lo elige a mano en el selector, no lo invoca un LLM.
# Se implementa acá y no como tool MCP porque el cliente MCP de opencode tiene un
# timeout duro de 60s para ejecutar tools (y el `timeout` de la config solo
# aplica al descubrimiento). Por HTTP el techo es el del provider: 300s.
IMG_IDS = {"imagen", "image", "sd", "stable-diffusion", "stable_diffusion",
           "sd15", "sd1.5", "sd35", "sd3.5"}
IMG_DEFAULT = "sd35"
IMG_DIR = "/opt/ia/images"
SD = "http://127.0.0.1:8082"

# opencode dispara el request dos veces con ~1s de diferencia (title + mensaje).
# Sin esto genera dos imagenes identicas y wastea 25s de GPU. Con lock + cache
# la segunda peticion sale instantanea devolviendo el mismo archivo.
_img_lock = threading.Lock()
_load_lock = threading.RLock()
_img_cache = {}
IMG_CACHE_TTL = 300

# Negative prompt por defecto: este checkpoint (sd15-Q5_1) sesga fuerte a
# rojo/violeta si no se lo frena. Si el prompt ya trae sd_cpp_extra_args,
# se respeta el del usuario y NO se agrega este.
DEFAULT_NEGATIVE = "red, magenta, pink, violet, purple, neon, oversaturated, warm colors"

# Dos checkpoints vivos: el usuario elige con el campo "model" del request.
# Solo uno puede correr a la vez (ambos bindean 8082 y se pelean por la VRAM),
# por eso hay dos unit files y sd_ensure() arma el cambio.
IMG_MODELS = {
    "sd15": {"unit": "sd-server-sd15.service", "neg": DEFAULT_NEGATIVE},
    "sd35": {"unit": "sd-server.service",     "neg": ""},
}


def img_model(name):
    """Normaliza el model del request a un id de IMG_MODELS. Los ids genericos
    ("imagen", "sd", ...) caen en el default para no romper clientes viejos."""
    if not name:
        return IMG_DEFAULT
    k = name.strip().lower()
    if k in ("sd15", "sd1.5", "sd-15", "sd 1.5", "imagen-sd15"):
        return "sd15"
    if k in ("sd35", "sd3.5", "sd-35", "sd 3.5", "imagen-sd35"):
        return "sd35"
    return IMG_DEFAULT


def is_image(name):
    if not name:
        return False
    return name.strip().lower() in IMG_IDS


def resolve(name):
    if not name:
        return "qwen2.5-7b-instruct-q4_k_m"
    base = os.path.basename(name)
    base = re.sub(r"^/.*/", "", base)
    if base in MODELS:
        return base
    stem = base.removesuffix(".gguf")
    if stem in MODELS:
        return stem
    return ALIASES.get(base) or ALIASES.get(stem) or "qwen2.5-7b-instruct-q4_k_m"


def sd_up():
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 8082), timeout=5):
            return True
    except OSError:
        return False


def sd_ensure(want):
    """Deja corriendo el sd-server del modelo pedido. No se puede mutar el unit
    en caliente: hay que apagar el otro antes, porque comparten puerto."""
    for key, cfg in IMG_MODELS.items():
        active = subprocess.run(["systemctl", "is-active", cfg["unit"]],
                                capture_output=True, text=True,
                                check=False).stdout.strip() == "active"
        if key == want:
            if not active:
                subprocess.run(["systemctl", "start", cfg["unit"]],
                               capture_output=True, check=False)
        elif active:
            subprocess.run(["systemctl", "stop", cfg["unit"]],
                           capture_output=True, check=False)
    for _ in range(90):
        if sd_up():
            return True
        time.sleep(1)
    return False


def generate_image(prompt, steps=20, width=512, height=512, name=None,
                   model=None):
    """Libera VRAM, genera con SD, y deja que el router recargue el LLM solo
    en el proximo request (ensure() valida /health, asi que se autorepara)."""
    want = img_model(model)
    was_up = subprocess.run(["systemctl", "is-active", "llama-server"],
                            capture_output=True, text=True,
                            check=False).stdout.strip() == "active"
    if was_up:
        slots_save(current())
        subprocess.run(["systemctl", "stop", "llama-server"],
                       capture_output=True, check=False)
        time.sleep(2)
    try:
        if not sd_ensure(want):
            raise RuntimeError(f"sd-server ({want}) no levanto")
        neg = IMG_MODELS[want]["neg"]
        if "<sd_cpp_extra_args>" not in prompt and neg:
            prompt = (prompt + " <sd_cpp_extra_args>{\"negative_prompt\": \""
                      + neg + "\"}</sd_cpp_extra_args>")
        payload = json.dumps({"prompt": prompt, "steps": steps,
                              "width": width, "height": height}).encode()
        req = urllib.request.Request(f"{SD}/v1/images/generations", data=payload,
                                     headers={"Content-Type": "application/json"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=900) as r:
            d = json.load(r)
        img = d["data"][0]
        import base64
        raw = base64.b64decode(img["b64_json"]) if "b64_json" in img else \
            urllib.request.urlopen(img["url"], timeout=60).read()
        os.makedirs(IMG_DIR, exist_ok=True)
        fname = re.sub(r"[^A-Za-z0-9_-]", "-", name or "img")[:60] or "img"
        tag = "" if want in fname else f"-{want}"
        base = f"{fname}{tag}-{time.strftime('%H%M%S')}"
        path = os.path.join(IMG_DIR, f"{base}.png")
        with open(path, "wb") as f:
            f.write(raw)
        return path, time.time() - t0, len(raw)
    finally:
        if was_up:
            subprocess.run(["systemctl", "start", "llama-server"],
                           capture_output=True, check=False)
            # El server vuelve con el MISMO modelo pero KV vacio: quien
            # restaura es ensure() cuando confirme que quedo sano.
            _restore_pending.set()


def current():
    try:
        return open(STATE).read().strip()
    except OSError:
        return ""


def healthy():
    try:
        r = urllib.request.Request(f"{UPSTREAM}/health",
                                   headers={"Authorization": f"Bearer {API_KEY}"})
        urllib.request.urlopen(r, timeout=5)
        return True
    except Exception:
        return False


def _slots_list():
    """GET /slots del upstream con reintento: recien levantado, /health puede
    responder antes que el resto de los endpoints. Devuelve [] solo al final."""
    for attempt in range(3):
        req = urllib.request.Request(f"{UPSTREAM}/slots",
                                     headers={"Authorization": f"Bearer {API_KEY}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.load(r)
            slots = data if isinstance(data, list) else data.get("slots", [])
            if slots:
                return slots
        except Exception:
            pass
        if attempt < 2:
            time.sleep(2)
    return []


def _slot_action(action, slot_id, filename):
    body = json.dumps({"filename": filename}).encode()
    req = urllib.request.Request(
        f"{UPSTREAM}/slots/{slot_id}?action={action}", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def slot_file(model, slot_id):
    """Un archivo por modelo y por slot: llama_state_seq solo sirve con el mismo
    modelo y los mismos flags de contexto con los que se guardo."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", model) or "model"
    return f"{safe}-{slot_id}.bin"


def slots_save(model):
    """Vuelca el KV de cada slot a disco ANTES de matar llama-server.

    Best-effort y por slot: el slot vacio, un server sin --slot-save-path o un
    server caido fallan individualmente y seguimos igual — un swap o una
    generacion de imagen nunca se rompen por esto."""
    if not model:
        return
    try:
        os.makedirs(SLOT_DIR, exist_ok=True)
    except OSError:
        return
    slots = _slots_list()
    if not slots:
        sys.stderr.write("[router] save omitido: /slots no responde "
                         "(server caido o sin --slot-save-path)\n")
        sys.stderr.flush()
        return
    for slot in slots:
        fn = slot_file(model, slot["id"])
        # Guardar a .tmp y promover solo con n_saved>0: si el server recien
        # levanto (post-imagen o crash) sus slots estan vacios, y un save
        # directo pisaria el archivo bueno con un header de36 bytes.
        # Costo medido: eso destruyo el KV de19.846 tokens una vez.
        tmp = fn + f".tmp{os.getpid()}-{threading.get_ident()}"
        try:
            res = _slot_action("save", slot["id"], tmp)
            if res.get("n_saved", 0) > 0 and os.path.isfile(SLOT_DIR + tmp):
                os.replace(SLOT_DIR + tmp, SLOT_DIR + fn)
                sys.stderr.write(
                    f"[router] slot {slot['id']} guardado de {model}: "
                    f"{res.get('n_saved', 0)} tokens "
                    f"({res.get('timings', {}).get('save_ms', 0) / 1000:.1f}s)\n")
            else:
                # Slot vacio: no hay nada que preservar ni que pisar.
                try:
                    os.remove(SLOT_DIR + tmp)
                except OSError:
                    pass
        except Exception as e:
            try:
                os.remove(SLOT_DIR + tmp)
            except OSError:
                pass
            sys.stderr.write(f"[router] slot {slot['id']} no se guarda: {e}\n")
        sys.stderr.flush()


def slots_restore(model):
    """Recupera el KV previo de `model` si existe su archivo. llama-server
    reutiliza el prefijo del prompt restaurado que coincida con el proximo
    request; si no coincide, hace prefill normal (cero riesgo de corrupcion)."""
    if not model:
        return
    slots = _slots_list()
    if not slots:
        sys.stderr.write(f"[router] restore de {model} omitido: "
                         "/slots no responde\n")
        sys.stderr.flush()
        return
    found = False
    for slot in slots:
        fn = slot_file(model, slot["id"])
        # <4KB = header sin KV (slot vacio): no hay nada que restaurar.
        if not os.path.isfile(SLOT_DIR + fn) \
                or os.path.getsize(SLOT_DIR + fn) < 4096:
            continue
        found = True
        try:
            res = _slot_action("restore", slot["id"], fn)
            sys.stderr.write(
                f"[router] slot {slot['id']} restaurado de {model}: "
                f"{res.get('n_restored', 0)} tokens "
                f"({res.get('timings', {}).get('restore_ms', 0) / 1000:.1f}s)\n")
        except Exception as e:
            sys.stderr.write(f"[router] slot {slot['id']} no se restaura: {e}\n")
        sys.stderr.flush()
    if not found:
        sys.stderr.write(f"[router] restore de {model}: sin archivo previo "
                         f"en {SLOT_DIR}\n")
        sys.stderr.flush()


def state_dir():
    """Crear el dir del estado cada vez que se escribe: evita el
    FileNotFoundError que mataba el request entero."""
    d = os.path.dirname(STATE)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def server_flags(model):
    """Flags de llama-server para `model`, sin -m ni la key.

    Separado de load() para testearlo sin systemd."""
    extra = f"--mmproj {MMPROJ} " if "vl" in model else ""
    # --parallel 1: con el default (4 slots) las 65.536 celdas de KV se
    # comparten, y un request lateral (el resumen de compresion) desalojaba la
    # conversacion: "failed to find 55298 available cells", 55K tokens
    # releidos. El router ya serializa los chats con _load_lock, asi que los
    # slots extra nunca daban paralelismo real.
    return extra + (MODEL_ARGS.get(model) or (
        f"--host 0.0.0.0 --port 8080 -ngl 99 -c {CTX} -ub 512 --parallel 1 "
        "--cache-type-k q8_0 --cache-type-v q8_0 --threads 4 "
        "--cache-reuse 4096 "
    ))


def load(model):
    slots_save(current())
    try:
        os.makedirs(SLOT_DIR, exist_ok=True)
    except OSError:
        pass
    subprocess.run(["systemctl", "stop", "llama-server"],
                   capture_output=True, check=False)
    time.sleep(2)
    flags = server_flags(model)
    unit = (
        "[Unit]\nDescription=llama.cpp server (router)\nAfter=network.target\n\n"
        "[Service]\nType=simple\n"
        f"ExecStart={BIN} -m {MODELS[model]} {flags}"
        f"--slot-save-path {SLOT_DIR} --api-key {API_KEY} --jinja\n"
        "Restart=always\nRestartSec=5\n\n[Install]\nWantedBy=multi-user.target\n"
    )
    # Nombre unico por hilo/proceso: dos requests concurrentes comparten el
    # router, y con un nombre fijo uno borra el .new del otro antes de que lo
    # renombre (FileNotFoundError) y el cliente se queda sin respuesta.
    tmp = f"/etc/systemd/system/llama-server.service.new.{os.getpid()}.{threading.get_ident()}"
    with open(tmp, "w") as f:
        f.write(unit)
    os.chmod(tmp, 0o644)
    os.replace(tmp, "/etc/systemd/system/llama-server.service")
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True, check=False)
    subprocess.run(["systemctl", "start", "llama-server"], capture_output=True, check=False)
    state_dir()
    for _ in range(150):
        if healthy():
            with open(STATE, "w") as f:
                f.write(model)
            _restore_pending.clear()
            slots_restore(model)
            return True
        time.sleep(1)
    return False


def ensure(model):
    # Lock de proceso: ThreadingHTTPServer atiende cada request en un hilo, y sin
    # esto dos requests que piden modelos distintos (o el mismo) corren load() a la
    # vez: uno para llama-server mientras el otro lo reinicia, y ambos clients
    # se quedan colgados sin respuesta (BrokenPipe / IncompleteRead).
    with _load_lock:
        if current() == model and healthy():
            if _restore_pending.is_set():
                # generate_image reinicio llama-server fuera de load(): aca
                # recien hay un server sano donde restaurar el KV guardado.
                _restore_pending.clear()
                slots_restore(model)
            return True
        return load(model)


def units_active():
    """Estado de las units de imagen y audio en una sola llamada a systemctl."""
    units = [cfg["unit"] for cfg in IMG_MODELS.values()] + ["whisper-server.service"]
    out = subprocess.run(["systemctl", "is-active", *units],
                         capture_output=True, text=True, check=False).stdout.split()
    return dict(zip(units, out))


def models_payload(now=None, active=None):
    """Cuerpo de /v1/models, con categoria por modelo.

    Separado del handler para poder testearlo en CI sin servidor ni systemd:
    ahora y active se inyectan. El orden es por categoria, que es como el
    selector los muestra.
    """
    if now is None:
        now = current() or "qwen2.5-7b-instruct-q4_k_m"
    if active is None:
        active = units_active()
    entries = [{"id": name, "object": "model", "owned_by": "ia-local",
                "created": 0, "root": name, "loaded": name == now,
                "category": CATEGORY_OF[name]}
               for name in sorted(MODELS)]
    for img_id, cfg in IMG_MODELS.items():
        entries.append({"id": img_id, "object": "model", "owned_by": "ia-local",
                        "created": 0, "root": f"stable-diffusion-{img_id}",
                        "loaded": active.get(cfg["unit"]) == "active",
                        "category": "imagen"})
    # Alias legacy: clientes viejos siguen pidiendo "imagen" sin aclarar cual.
    entries.append({"id": "imagen", "object": "model", "owned_by": "ia-local",
                    "created": 0, "root": "stable-diffusion-1.5",
                    "loaded": active.get(IMG_MODELS[IMG_DEFAULT]["unit"]) == "active",
                    "category": "imagen"})
    # El audio se anuncia solo si whisper esta instalado: un id sin backend
    # detras es una opcion muerta en el selector del cliente. systemctl
    # is-active imprime "not-found" cuando no existe la unit.
    if active.get("whisper-server.service", "inactive") != "not-found":
        entries.append({"id": AUDIO_ID, "object": "model", "owned_by": "ia-local",
                        "created": 0, "root": "whisper",
                        "loaded": active.get("whisper-server.service") == "active",
                        "category": "audio", **AUDIO_INFO})
    entries.sort(key=lambda e: (CATEGORY_ORDER.index(e["category"]), e["id"]))
    return {"object": "list", "data": entries}


def forward(method, path, body, headers):
    req = urllib.request.Request(UPSTREAM + path, data=body, method=method)
    for k, v in headers.items():
        if k.lower() in ("host", "content-length", "connection", "accept-encoding"):
            continue
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except (urllib.error.URLError, OSError) as e:
        # Sin esto la excepcion sube hasta el handler, la conexion se cierra sin
        # respuesta y el cliente ve "Empty reply from server" en vez de un error.
        # 502 dice que el problema es llama-server, no el cliente.
        body = json.dumps({"error": {"message": f"llama-server no responde: {e}"}}).encode()
        return 502, {"Content-Type": "application/json"}, body


def cap_max_tokens(payload):
    """Pone DEFAULT_MAX_TOKENS si el request no trae ningun tope de salida.

    Solo cuando falta: un max_tokens explicito del cliente se respeta siempre.
    Devuelve True si toco el payload (hay que re-serializar el body)."""
    if DEFAULT_MAX_TOKENS <= 0 or not isinstance(payload, dict) or not payload:
        return False
    if any(payload.get(k) for k in ("max_tokens", "max_completion_tokens", "n_predict")):
        return False
    payload["max_tokens"] = DEFAULT_MAX_TOKENS
    return True


def client_gone(sock):
    """True si el cliente cerro su lado (EOF al espiar el socket sin consumir).

    Datos pendientes (un request pipelineado) no cuentan como cierre."""
    try:
        readable, _, _ = select.select([sock], [], [], 0)
        if not readable:
            return False
        return sock.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return True


def forward_live(handler, path, body, headers, poll=1.0):
    """Reenvia un POST a llama-server sin bufferizar y lo cancela si el cliente se va.

    El forward() original hacia r.read() de la respuesta entera: el cliente no
    veia ni un token de un SSE hasta el final (Hermes lo lee como "sin
    progreso") y, si se rendia, llama-server seguia generando para nadie con
    el lock del router tomado. Aca un hilo vigila el socket del cliente; si
    cierra, se corta la conexion upstream y llama-server cancela la tarea.
    Devuelve "ok", "cancelled" o "error"."""
    conn = http.client.HTTPConnection(*UPSTREAM_ADDR, timeout=1800)
    done = threading.Event()
    gone = threading.Event()

    def watch():
        while not done.wait(poll):
            if client_gone(handler.connection):
                gone.set()
                try:
                    conn.sock.shutdown(socket.SHUT_RDWR)
                except (OSError, AttributeError):
                    pass
                return

    sent = False
    try:
        conn.request("POST", path, body=body,
                     headers={k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS})
        threading.Thread(target=watch, daemon=True).start()
        resp = conn.getresponse()
        if "text/event-stream" in (resp.getheader("Content-Type") or ""):
            handler.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP_HEADERS:
                    handler.send_header(k, v)
            handler.send_header("Transfer-Encoding", "chunked")
            handler.end_headers()
            sent = True
            while True:
                chunk = resp.read1(65536)
                if not chunk:
                    break
                handler.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
                handler.wfile.flush()
            handler.wfile.write(b"0\r\n\r\n")
            handler.wfile.flush()
        else:
            data = resp.read()
            handler.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP_HEADERS:
                    handler.send_header(k, v)
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            sent = True
            handler.wfile.write(data)
        return "ok"
    except (OSError, http.client.HTTPException) as e:
        if gone.is_set() or isinstance(e, (BrokenPipeError, ConnectionResetError)):
            sys.stderr.write(f"[router] cliente desconectado: upstream cancelado ({path})\n")
            sys.stderr.flush()
            return "cancelled"
        if not sent:
            err = json.dumps({"error": {"message": f"llama-server no responde: {e}"}}).encode()
            try:
                handler.send_response(502)
                handler.send_header("Content-Type", "application/json")
                handler.send_header("Content-Length", str(len(err)))
                handler.end_headers()
                handler.wfile.write(err)
            except OSError:
                pass
        return "error"
    finally:
        done.set()
        conn.close()


def main():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    state_dir()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _auth(self):
            h = self.headers.get("Authorization", "")
            if h != f"Bearer {API_KEY}":
                self.send_response(401)
                self.send_header("Content-Length", "9")
                self.end_headers()
                self.wfile.write(b"unauthor")
                return False
            return True

        def do_GET(self):
            # Listado de imagenes para que la laptop las baje sola. Requiere
            # token porque revela que se genero algo; el archivo si es publico.
            if self.path.rstrip("/").endswith("/img/list"):
                if not self._auth():
                    return
                items = []
                try:
                    for fn in os.listdir(IMG_DIR):
                        if not fn.endswith(".png"):
                            continue
                        stt = os.stat(os.path.join(IMG_DIR, fn))
                        items.append({"name": fn, "size": stt.st_size,
                                      "mtime": int(stt.st_mtime)})
                except OSError:
                    pass
                items.sort(key=lambda x: x["mtime"])
                self._json(200, {"images": items})
                return
            # /img/ es publico a proposito: el usuario abre el link en el browser
            # o lo baja con wget y no puede mandar el header Authorization.
            if "/img/" in self.path:
                base = os.path.basename(self.path.split("/img/", 1)[1])
                full = os.path.join(IMG_DIR, base)
                if not base or not os.path.isfile(full):
                    self._json(404, {"error": {"message": "no existe"}})
                    return
                with open(full, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if not self._auth():
                return
            if self.path.rstrip("/").endswith("/models"):
                # Anunciar TODOS los modelos, no solo el cargado. opencode arma
                # su selector desde este endpoint: si devolvemos solo el que esta
                # en VRAM, el usuario ve una unica opcion y no puede cambiar.
                self._json(200, models_payload())
                return
            st, hd, data = forward("GET", self.path, None, dict(self.headers))
            self.send_response(st)
            for k, v in hd.items():
                if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _image_chat(self, payload):
            """El usuario eligio el modelo 'imagen': su prompt es el texto a dibujar."""
            msgs = payload.get("messages") or []
            prompt = ""
            for m in reversed(msgs):
                c = m.get("content")
                if isinstance(c, str) and c.strip():
                    prompt = c.strip()
                    break
                if isinstance(c, list):
                    for part in c:
                        if isinstance(part, dict) and part.get("type") == "text":
                            prompt = part["text"].strip()
                            break
                    if prompt:
                        break
            prompt = re.sub(r"^(dibuj[aá]|gener[aá]|cre[aá]|hac[eé]|pint[aá]|"
                            r"dame|generame|haceme)\s+(una\s+|un\s+)?", "",
                            prompt, flags=re.IGNORECASE).strip(" .:\n\"'")
            if not prompt:
                self._json(400, {"error": {"message": "prompt vacio para generar imagen"}})
                return
            steps = min(40, max(1, int(payload.get("steps") or 20)))
            name = payload.get("name")
            img_id = img_model(payload.get("model"))
            key = (prompt, steps, 512, 512, img_id)
            with _img_lock:
                cached = _img_cache.get(key)
                if cached and time.time() - cached[1] < IMG_CACHE_TTL \
                        and os.path.isfile(cached[0]):
                    sys.stderr.write(f"[router] imagen: cache {os.path.basename(cached[0])}\n")
                    sys.stderr.flush()
                    base = os.path.basename(cached[0])
                    url = f"http://{self.headers.get('Host', '192.168.10.125:8090')}/img/{base}"
                    text = (f"Imagen generada (cache, {cached[2]:.1f}s, {steps} steps)\n"
                            f"![{base}]({url})\n{url}")
                    if payload.get("stream"):
                        self._sse(text)
                    else:
                        self._json(200, {
                            "id": f"img-{int(time.time())}", "object": "chat.completion",
                            "model": "imagen", "choices": [{
                                "index": 0, "finish_reason": "stop",
                                "message": {"role": "assistant", "content": text}}]})
                    return
                sys.stderr.write(f"[router] imagen: {prompt[:70]}\n")
                sys.stderr.flush()
                try:
                    path, secs, nbytes = generate_image(prompt, steps=steps, name=name,
                                                    model=img_id)
                except Exception as e:
                    self._json(500, {"error": {"message": f"fallo generando imagen: {e}"}})
                    return
                _img_cache[key] = (path, time.time(), secs)
            base = os.path.basename(path)
            url = f"http://{self.headers.get('Host', '192.168.10.125:8090')}/img/{base}"
            text = (f"Imagen generada ({secs:.1f}s, {steps} steps, {nbytes//1024} KB)\n"
                    f"![{base}]({url})\n{url}")

            # opencode siempre pide stream:true. Si respondemos JSON plano, el SDK
            # lo rechaza y REINTENTA en bucle (una imagen por intento). Hay que
            # emitir SSE con la forma de chat.completion.chunk.
            if payload.get("stream"):
                self._sse(text)
            else:
                self._json(200, {
                    "id": f"img-{int(time.time())}", "object": "chat.completion",
                    "model": "imagen", "choices": [{
                        "index": 0, "finish_reason": "stop",
                        "message": {"role": "assistant", "content": text},
                    }],
                })

        def _sse(self, text):
            """SSE con chunked encoding: opencode/ai-sdk lo exige para streaming."""
            cid = f"img-{int(time.time())}"
            created = int(time.time())

            def chunk(delta, finish=None):
                return json.dumps({
                    "id": cid, "object": "chat.completion.chunk", "created": created,
                    "model": "imagen",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                })

            events = [
                chunk({"role": "assistant", "content": ""}),
                chunk({"content": text}),
                chunk({}, "stop"),
            ]
            body = b""
            for ev in events:
                body += f"data: {ev}\n\n".encode()
            body += b"data: [DONE]\n\n"

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            # Un solo write con el chunked framing; el SDK no necesita Receiving
            # progreso parcial porque la imagen ya esta generada a esta altura.
            self.wfile.write(f"{len(body):X}\r\n".encode() + body + b"\r\n0\r\n\r\n")
            self.wfile.flush()

        def do_POST(self):
            if not self._auth():
                return
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n) if n else b""

            if "chat/completions" in self.path or "completions" in self.path:
                try:
                    payload = json.loads(body or b"{}")
                except Exception:
                    payload = {}
                asked = payload.get("model")

                if is_image(asked):
                    self._image_chat(payload)
                    return

                want = resolve(asked)
                if cap_max_tokens(payload):
                    body = json.dumps(payload).encode()
                # El lock cubre ensure() Y forward(), no solo la carga: si se
                # suelta entre una y otra, otro hilo reinicia llama-server con
                # otro modelo mientras este reenvia la peticion, y el cliente
                # recibe 502. Los clientes concurrentes se serializan.
                with _load_lock:
                    if want != current() or not healthy():
                        sys.stderr.write(f"[router] cargando {want} (estaba {current() or 'nada'})\n")
                        sys.stderr.flush()
                        try:
                            ready = ensure(want)
                        except Exception as e:
                            # Sin esto la excepcion sube al handler,
                            # socketserver cierra el socket sin responder y el
                            # cliente espera hasta su timeout.
                            sys.stderr.write(f"[router] fallo ensure({want}): {e}\n")
                            sys.stderr.flush()
                            ready = False
                        if not ready:
                            self.send_response(503)
                            self.send_header("Content-Length", "48")
                            self.end_headers()
                            self.wfile.write(b'{"error":{"message":"no se pudo cargar"}}'[:48])
                            return
                    # En vivo y cancelable: libera el lock apenas el cliente
                    # se va, en vez de esperar a que llama termine para nadie.
                    forward_live(self, self.path, body, dict(self.headers))
                    return
            else:
                # [fix-st] todo POST que no sea chat/completions llegaba ahi
                # sin `st` asignado y reventaba el handler. Reenviar tal cual
                # al upstream (que es el que decide 404/405) en vez de morir.
                sys.stderr.write(f"[router] POST no-chat: {self.path}\n")
                sys.stderr.flush()
                st, hd, data = forward("POST", self.path, body, dict(self.headers))
            self.send_response(st)
            for k, v in hd.items():
                if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = ThreadingHTTPServer(("0.0.0.0", 8090), H)
    srv.serve_forever()


if __name__ == "__main__":
    main()

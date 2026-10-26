"""Basic sanity tests for the router module.

No servers, no GPU, no systemd: these run in CI on a bare runner.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import router  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_seven_text_vision_models():
    assert len(router.MODELS) == 7


def test_aliases_point_to_real_models():
    assert set(router.ALIASES.values()) <= set(router.MODELS)


def test_model_args_reference_known_models():
    assert set(router.MODEL_ARGS) <= set(router.MODELS)


def test_image_defaults_are_valid():
    assert router.IMG_DEFAULT in router.IMG_MODELS
    assert {"sd15", "sd35"} <= set(router.IMG_IDS)


def test_image_units_exist_in_repo():
    units = {p.name for p in (ROOT / "systemd").glob("*.service")}
    for cfg in router.IMG_MODELS.values():
        assert cfg["unit"] in units


def test_api_key_fallback_is_nonempty():
    assert router.API_KEY


def test_every_text_model_has_a_category():
    assert set(router.CATEGORY_OF) == set(router.MODELS)


def test_selector_categories_are_the_five_requested():
    assert set(router.CATEGORY_ORDER) == {
        "texto", "vision", "multitarea", "imagen", "audio"}
    assert set(router.CATEGORY_OF.values()) <= set(router.CATEGORY_ORDER)


def test_models_payload_covers_every_category():
    # active y now se inyectan: CI no tiene systemd ni servidor corriendo.
    payload = router.models_payload(now="ornith-1.5-9b-q4_k_m", active={})
    cats = {entry["category"] for entry in payload["data"]}
    assert cats == set(router.CATEGORY_ORDER)


def test_models_payload_marks_the_loaded_model():
    payload = router.models_payload(now="ornith-1.5-9b-q4_k_m", active={})
    loaded = [e["id"] for e in payload["data"] if e["loaded"]]
    assert loaded == ["ornith-1.5-9b-q4_k_m"]


def test_models_payload_keeps_legacy_image_alias():
    payload = router.models_payload(now="ornith-1.5-9b-q4_k_m", active={})
    ids = {e["id"] for e in payload["data"]}
    assert {"imagen", "sd35", "sd15", router.AUDIO_ID} <= ids


def test_models_payload_orders_by_category():
    payload = router.models_payload(now="ornith-1.5-9b-q4_k_m", active={})
    seen = [e["category"] for e in payload["data"]]
    order = list(router.CATEGORY_ORDER)
    assert seen == sorted(seen, key=order.index)


def test_audio_entry_points_at_the_real_endpoint():
    payload = router.models_payload(now="ornith-1.5-9b-q4_k_m", active={})
    audio = next(e for e in payload["data"] if e["category"] == "audio")
    # whisper-server expone /inference, no la ruta OpenAI (/v1 da 404).
    assert audio["path"] == "/inference"
    assert audio["port"] == 8081


def test_audio_is_not_advertised_when_whisper_is_absent():
    # Una install fresca no trae whisper: anunciarlo seria una opcion muerta.
    payload = router.models_payload(
        now="ornith-1.5-9b-q4_k_m",
        active={"whisper-server.service": "not-found"})
    assert router.AUDIO_ID not in {e["id"] for e in payload["data"]}
    assert "audio" not in {e["category"] for e in payload["data"]}


def test_slot_file_is_keyed_by_model_and_slot():
    # El KV restore solo sirve con el mismo modelo: el nombre lo lleva.
    assert router.slot_file("ornith-1.5-9b-q4_k_m", 0) == \
        "ornith-1.5-9b-q4_k_m-0.bin"
    # fs_validate_filename del server rechaza separadores de ruta.
    assert "/" not in router.slot_file("foo/bar", 2)


def test_slot_dir_has_trailing_slash_and_is_persistent():
    # llama-server concatena slot_save_path + filename sin separador.
    assert router.SLOT_DIR.endswith("/")
    # /run es tmpfs: el KV se perderia en cada reboot del LXC.
    assert not router.SLOT_DIR.startswith("/run/")


def test_state_file_is_persistent():
    # Con STATE en /run, un restart del router (deploy) dejaba current() en ""
    # y slots_save() se saltaba el save: el KV caliente se perdia sin log.
    assert router.STATE.startswith("/var/lib/")
    assert not router.STATE.startswith("/run/")


def test_text_models_allow_memory_autofit():
    for model in router.MODELS:
        flags = router.server_flags(model)
        # Los MoE fijan -ngl 99 y reparten con --n-cpu-moe (medido con -c 65536).
        if "--n-cpu-moe" not in flags:
            assert "-ngl" not in flags
        assert "-c 65536" in flags
        assert "--parallel 1" in flags


def test_cached_text_request_releases_image_backends(monkeypatch):
    events = []
    monkeypatch.setattr(router, "stop_image_backends", lambda: events.append("stop-images"))
    monkeypatch.setattr(router, "current", lambda: "ornith")
    monkeypatch.setattr(router, "healthy", lambda: True)
    router._restore_pending.clear()
    assert router.ensure("ornith")
    assert events == ["stop-images"]


def test_image_stop_failure_blocks_text_load(monkeypatch):
    import subprocess

    import pytest

    def fail():
        raise subprocess.CalledProcessError(1, "systemctl")

    monkeypatch.setattr(router, "stop_image_backends", fail)
    monkeypatch.setattr(router, "load", lambda model: pytest.fail("unsafe text load"))
    with pytest.raises(subprocess.CalledProcessError):
        router.ensure("ornith")


@pytest.mark.parametrize("load_failure", [False, True])
def test_http_cached_model_restores_pending_cache_before_forward(monkeypatch, load_failure):
    import http.client
    import http.server
    import json
    import queue
    import threading
    from http.server import ThreadingHTTPServer

    events, servers = [], queue.Queue()
    real_server = ThreadingHTTPServer

    def server_factory(address, handler):
        server = real_server(("127.0.0.1", 0), handler)
        servers.put(server)
        return server

    def forward(handler, path, body, headers):
        events.append("forward")
        handler._json(200, {"ok": True})

    monkeypatch.setattr(http.server, "ThreadingHTTPServer", server_factory)
    monkeypatch.setattr(router, "state_dir", lambda: None)
    monkeypatch.setattr(router, "current", lambda: "ornith-1.5-9b-q4_k_m")
    monkeypatch.setattr(router, "healthy", lambda: True)
    monkeypatch.setattr(router, "stop_image_backends", lambda: events.append("stop-images"))
    monkeypatch.setattr(router, "slots_restore", lambda model: events.append("restore"))
    monkeypatch.setattr(router, "forward_live", forward)
    if load_failure:
        monkeypatch.setattr(router, "ensure", lambda model: False)
    router._restore_pending.set()
    thread = threading.Thread(target=router.main, daemon=True)
    thread.start()
    server = servers.get(timeout=3)
    try:
        conn = http.client.HTTPConnection(*server.server_address, timeout=3)
        body = json.dumps({"model": "ornith-1.5-9b-q4_k_m", "messages": []})
        conn.request("POST", "/v1/chat/completions", body,
                     {"Authorization": "Bearer " + router.API_KEY})
        response = conn.getresponse()
        assert response.status == (503 if load_failure else 200)
        result = json.loads(response.read())
        conn.close()
        if load_failure:
            assert result["error"]["message"] == "no se pudo cargar"
        else:
            assert events == ["stop-images", "restore", "forward"]
            assert not router._restore_pending.is_set()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        router._restore_pending.clear()

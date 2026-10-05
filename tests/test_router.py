"""Basic sanity tests for the router module.

No servers, no GPU, no systemd: these run in CI on a bare runner.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import router  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_six_text_vision_models():
    assert len(router.MODELS) == 6


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
    payload = router.models_payload(now="qwen2.5-7b-instruct-q4_k_m", active={})
    ids = {e["id"] for e in payload["data"]}
    assert {"imagen", "sd35", "sd15", router.AUDIO_ID} <= ids


def test_models_payload_orders_by_category():
    payload = router.models_payload(now="qwen2.5-7b-instruct-q4_k_m", active={})
    seen = [e["category"] for e in payload["data"]]
    order = list(router.CATEGORY_ORDER)
    assert seen == sorted(seen, key=order.index)


def test_audio_entry_points_at_the_real_endpoint():
    payload = router.models_payload(now="qwen2.5-7b-instruct-q4_k_m", active={})
    audio = next(e for e in payload["data"] if e["category"] == "audio")
    # whisper-server expone /inference, no la ruta OpenAI (/v1 da 404).
    assert audio["path"] == "/inference"
    assert audio["port"] == 8081


def test_audio_is_not_advertised_when_whisper_is_absent():
    # Una install fresca no trae whisper: anunciarlo seria una opcion muerta.
    payload = router.models_payload(
        now="qwen2.5-7b-instruct-q4_k_m",
        active={"whisper-server.service": "not-found"})
    assert router.AUDIO_ID not in {e["id"] for e in payload["data"]}
    assert "audio" not in {e["category"] for e in payload["data"]}

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

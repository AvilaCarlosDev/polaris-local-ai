"""Harmony tests: systemd/ and setup.sh have to agree with each other.

A repo that ships a unit the installer cannot build, enable or start is a
broken install waiting to happen. Everything here runs in CI with no root,
no systemd running and no GPU — which is exactly the point: these are the
guards that keep `setup.sh` from regressing when a unit is added or moved.
"""
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETUP = (ROOT / "setup.sh").read_text(encoding="utf-8")
UNITS = sorted((ROOT / "systemd").glob("*.service"))


def flat(unit):
    """Unit text with backslash continuations joined — ExecStart is multiline."""
    return unit.read_text(encoding="utf-8").replace("\\\n", " ")


def setup_dirs():
    """Every *_DIR the installer declares, e.g. LLAMA_DIR -> /opt/llama.cpp."""
    return dict(re.findall(r'^([A-Z_]+_DIR)="(/[^"]+)"', SETUP, re.MULTILINE))


def test_repo_ships_the_core_units():
    names = {u.name for u in UNITS}
    assert {
        "router.service",
        "llama-server.service",
        "sd-server.service",
        "sd-server-sd15.service",
        "whisper-server.service",
    } <= names


def test_every_unit_can_be_enabled():
    # setup.sh runs `systemctl enable --now` on each unit. Without [Install]
    # the enable fails, the unit runs until reboot and then silently disappears.
    for unit in UNITS:
        assert "[Install]" in unit.read_text(encoding="utf-8"), (
            f"{unit.name} has no [Install] section, so `systemctl enable` fails"
        )


def test_unit_dependencies_stay_inside_the_repo():
    # A unit that Requires a service this repo does not ship cannot start on a
    # fresh host — systemd stops it at Before/After resolution time.
    known = {u.name for u in UNITS}
    for unit in UNITS:
        for field in ("After", "Wants", "Requires", "BindsTo"):
            for line in re.findall(rf"^{field}=(.+)$", flat(unit), re.MULTILINE):
                for dep in line.split():
                    if dep.endswith(".target"):
                        continue
                    assert dep in known, (
                        f"{unit.name} depends on {dep}, which this repo does not ship"
                    )


def test_every_path_the_units_use_is_owned_by_the_installer():
    # Anything under /opt referenced by a unit (binary or weight) must live in
    # a *_DIR setup.sh declares, otherwise a clean install never creates it.
    dirs = list(setup_dirs().values())
    assert dirs, "setup.sh declares no *_DIR variables"
    for unit in UNITS:
        for line in re.findall(r"^ExecStart=(.+)$", flat(unit), re.MULTILINE):
            for token in line.split():
                if not token.startswith("/opt/"):
                    continue
                assert any(token.startswith(d) for d in dirs), (
                    f"{unit.name} uses {token}, which setup.sh does not provision "
                    f"(declared dirs: {sorted(dirs)})"
                )


def test_installer_deploys_the_python_entrypoints():
    # router.py runs from /opt/ia, but a clean host has no /opt/ia — without
    # this step the installed units point at a file that does not exist.
    match = re.search(r"^ENTRYPOINTS=\(([^)]*)\)", SETUP, re.MULTILINE)
    assert match, "setup.sh declares no ENTRYPOINTS array"
    deployed = match.group(1).split()
    assert {"router.py", "image-mcp.py"} <= set(deployed)
    assert "install -D" in SETUP, "setup.sh never copies files into place"
    for name in deployed:
        assert (ROOT / name).is_file(), f"{name} is deployed but missing from the repo"


def test_installer_knows_about_the_whisper_model():
    # The audio unit loads a .bin, not a .gguf, so the weight checks have to
    # name it explicitly or the engine starts and dies on the first request.
    assert "ggml-medium.bin" in SETUP


def test_no_secret_is_committed():
    for unit in UNITS:
        text = unit.read_text(encoding="utf-8")
        for value in re.findall(r"--api-key\s+(\S+)", text):
            assert value == "__IA_API_KEY__", (
                f"{unit.name} hardcodes an API key — it must use __IA_API_KEY__"
            )


def test_check_mode_parses_and_reports_every_unit():
    # `--check` is the only mode that runs as a normal user. It must never
    # abort on a syntax error and must list every unit we ship.
    bash = subprocess.run(["bash", "-n", str(ROOT / "setup.sh")],
                          capture_output=True, text=True, timeout=60,
                          check=False)
    assert bash.returncode == 0, bash.stderr

    proc = subprocess.run(["bash", str(ROOT / "setup.sh"), "--check"],
                          capture_output=True, text=True, timeout=180,
                          check=False)
    # Non-zero is allowed: CI has no AMD card and no engines built, and the
    # script reports those as failures by design.
    assert proc.returncode in (0, 1), proc.stderr
    for section in ("System", "Engines", "Systemd units"):
        assert section in proc.stdout, f"missing section {section!r}"
    assert "unknown option" not in proc.stdout
    for unit in UNITS:
        assert unit.name in proc.stdout, f"--check never mentions {unit.name}"

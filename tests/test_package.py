"""The package: manifests agree with each other, the release archives are complete, the launchers work."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

import pytest

from conftest import FEATURE, REPO
from archiguard_core import __version__, yamlio


def load(rel):
    return yamlio.load_file(REPO / rel)


def test_versions_agree():
    ext = load("extension.yml")["extension"]["version"]
    preset = load("preset/preset.yml")["preset"]["version"]
    workflow = load("workflows/archiguard-sdd/workflow.yml")["workflow"]["version"]
    catalog_ext = json.loads((REPO / "catalog/extensions.json").read_text())["extensions"]["archiguard"]["version"]
    catalog_preset = json.loads((REPO / "catalog/presets.json").read_text())["presets"]["archiguard-templates"]["version"]
    assert {ext, preset, workflow, catalog_ext, catalog_preset, __version__} == {__version__}
    assert f"## [{__version__}]" in (REPO / "CHANGELOG.md").read_text(encoding="utf-8")


def test_extension_manifest_is_consistent():
    ext = load("extension.yml")
    commands = {c["name"]: c for c in ext["provides"]["commands"]}
    for c in commands.values():
        assert (REPO / c["file"]).is_file(), c["file"]
        assert c["name"].startswith("speckit.archiguard.")
    for event, hook in ext["hooks"].items():
        assert hook["command"] in commands, event
    for event in ext["events"].values():
        assert event["command"] in commands
    for cfg in ext["provides"]["config"]:
        assert (REPO / cfg["template"]).is_file()
    catalog = json.loads((REPO / "catalog/extensions.json").read_text())["extensions"]["archiguard"]
    assert catalog["provides"] == {"commands": len(commands), "hooks": len(ext["hooks"]), "events": len(ext["events"])}
    assert catalog["license"] == ext["extension"]["license"]


def test_command_scripts_point_at_the_launchers():
    for path in sorted((REPO / "commands").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        front = text.split("---")[1]
        for kind, launcher in (("sh", "scripts/bash/archiguard.sh"), ("ps", "scripts/powershell/archiguard.ps1"),
                               ("py", "scripts/python/archiguard.py")):
            m = re.search(rf"^\s+{kind}: (.+)$", front, re.M)
            if m:
                assert launcher in m.group(1), (path.name, kind)
        assert "{SCRIPT}" in text or "editguard" in path.name, path.name


def test_command_prose_never_names_an_extension_directory():
    """Spec Kit rewrites '<dir>/' for every directory the extension ships; feature paths must not collide."""
    shipped = {"scripts", "manifests", "templates"}
    for path in sorted((REPO / "commands").glob("*.md")):
        body = path.read_text(encoding="utf-8").split("---", 2)[2]
        for m in re.finditer(r"(^|[\s`\"'(])(?:\./)?([A-Za-z0-9_.-]+)/", body, re.M):
            assert m.group(2) not in shipped | {"gates"}, f"{path.name}: '{m.group(2)}/' would be rewritten"


def test_preset_manifest_is_consistent():
    preset = load("preset/preset.yml")
    for item in preset["provides"]["templates"]:
        assert (REPO / "preset" / item["file"]).is_file(), item["file"]
    catalog = json.loads((REPO / "catalog/presets.json").read_text())["presets"]["archiguard-templates"]
    kinds = [i["type"] for i in preset["provides"]["templates"]]
    assert catalog["provides"] == {"templates": kinds.count("template"), "commands": kinds.count("command")}


def test_workflow_backstops_cover_the_ceiling_plus_the_escalating_run():
    policy = load("package-policy.yml")
    text = (REPO / "workflows/archiguard-sdd/workflow.yml").read_text(encoding="utf-8")
    for value in re.findall(r"max_iterations: (\d+)", text):
        assert int(value) == policy["max_iterations_ceiling"] + 1


def test_build_archives(tmp_path):
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "build.py")], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    ext = zipfile.ZipFile(REPO / "dist" / "archiguard.zip")
    names = set(ext.namelist())
    assert "extension.yml" in names and "config-template.yml" in names and "package-policy.yml" in names
    assert "manifests/A0.yml" in names and "manifests/scope.yml" in names
    assert "scripts/python/archiguard_core/gates/dispatch.py" in names
    assert "templates/domain-map-template.yaml" in names
    assert not any(n.startswith(("tests/", "examples/", "preset/", "dist/", ".github/")) or "__pycache__" in n for n in names)
    info = ext.getinfo("scripts/bash/archiguard.sh")
    assert (info.external_attr >> 16) & 0o111
    preset = zipfile.ZipFile(REPO / "dist" / "archiguard-preset.zip")
    assert "preset.yml" in preset.namelist() and "commands/speckit.plan.md" in preset.namelist()
    sums = (REPO / "dist" / "SHA256SUMS").read_text()
    assert "archiguard.zip" in sums and "archiguard-preset.zip" in sums and "archiguard-sdd.yml" in sums
    # reproducible
    first = (REPO / "dist" / "archiguard.zip").read_bytes()
    subprocess.run([sys.executable, str(REPO / "tools" / "build.py")], capture_output=True, check=True)
    assert (REPO / "dist" / "archiguard.zip").read_bytes() == first
    bad = subprocess.run([sys.executable, str(REPO / "tools" / "build.py"), "--check-tag", "v9.9.9"],
                         capture_output=True, text=True)
    assert bad.returncode == 1


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="bash launcher")
def test_bash_launcher(project):
    launcher = REPO / "scripts" / "bash" / "archiguard.sh"
    proc = subprocess.run(["bash", str(launcher), "version"], capture_output=True, text=True)
    assert proc.returncode == 0 and __version__ in proc.stdout
    proc = subprocess.run(["bash", str(launcher), "run", "plan", "b", "--feature-dir", FEATURE],
                          cwd=str(project), capture_output=True, text=True)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    env = dict(os.environ, ARCHIGUARD_PYTHON="/nonexistent/python")
    proc = subprocess.run(["bash", str(launcher), "version"], capture_output=True, text=True, env=env)
    assert proc.returncode == 2 and "ARCHIGUARD_PYTHON" in proc.stderr


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell not installed")
def test_powershell_launcher(project):
    launcher = REPO / "scripts" / "powershell" / "archiguard.ps1"
    proc = subprocess.run(["pwsh", "-NoProfile", "-File", str(launcher), "run", "plan", "b", "--feature-dir", FEATURE],
                          cwd=str(project), capture_output=True, text=True)
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_python_launcher_refuses_old_python():
    text = (REPO / "scripts" / "python" / "archiguard.py").read_text(encoding="utf-8")
    assert "sys.version_info < (3, 9)" in text

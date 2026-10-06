#!/usr/bin/env python3
"""Build the release archives for archiGuard.

    python tools/build.py            # -> dist/archiguard.zip, dist/archiguard-preset.zip, dist/archiguard-sdd.yml, dist/SHA256SUMS
    python tools/build.py --check-tag v0.1.0

Both archives have their manifest (extension.yml / preset.yml) at the archive root, as
`specify extension add --from` and `specify preset add --from` expect. Archives are reproducible:
fixed timestamps, sorted entries, normalized modes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
FIXED_DATE = (2026, 1, 1, 0, 0, 0)

EXTENSION_FILES = ["extension.yml", "config-template.yml", "scope-config-template.yml", "package-policy.yml",
                   "README.md", "LICENSE", "CHANGELOG.md"]
EXTENSION_DIRS = ["commands", "scripts", "manifests", "templates"]
PRESET_ROOT = ROOT / "preset"
WORKFLOW = ROOT / "workflows" / "archiguard-sdd" / "workflow.yml"


def version_of(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.M)
    if not match:
        raise SystemExit(f"version not found in {path}")
    return match.group(1)


def versions() -> dict:
    yml = r'^\s*version:\s*"?([0-9][^"\s]*)"?'
    found = {
        "extension.yml": version_of(ROOT / "extension.yml", yml),
        "preset/preset.yml": version_of(PRESET_ROOT / "preset.yml", yml),
        "workflow.yml": version_of(WORKFLOW, yml),
        "archiguard_core": version_of(ROOT / "scripts" / "python" / "archiguard_core" / "__init__.py", r'^__version__\s*=\s*"([^"]+)"'),
    }
    for name in ("extensions.json", "presets.json"):
        data = json.loads((ROOT / "catalog" / name).read_text(encoding="utf-8"))
        for entry in (data.get("extensions") or data.get("presets") or {}).values():
            found[f"catalog/{name}"] = entry["version"]
    return found


def add_file(zf: zipfile.ZipFile, source: Path, arcname: str) -> None:
    info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE)
    executable = source.suffix in (".sh", ".py") and "scripts" in source.parts
    info.external_attr = ((0o100755 if executable else 0o100644) & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, source.read_bytes())


def build_zip(target: Path, entries: list) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as zf:
        for source, arcname in sorted(entries, key=lambda e: e[1]):
            add_file(zf, source, arcname)


def collect_extension() -> list:
    entries = [(ROOT / name, name) for name in EXTENSION_FILES]
    for directory in EXTENSION_DIRS:
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                entries.append((path, path.relative_to(ROOT).as_posix()))
    return entries


def collect_preset() -> list:
    entries = [(p, p.relative_to(PRESET_ROOT).as_posix()) for p in sorted(PRESET_ROOT.rglob("*")) if p.is_file()]
    entries.append((ROOT / "LICENSE", "LICENSE"))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-tag", help="fail unless all versions equal this tag (with or without leading v)")
    args = parser.parse_args()

    found = versions()
    if len(set(found.values())) != 1:
        print(f"version mismatch: {found}", file=sys.stderr)
        return 1
    version = next(iter(found.values()))
    if args.check_tag and args.check_tag.lstrip("v") != version:
        print(f"tag {args.check_tag} does not match version {version}", file=sys.stderr)
        return 1

    outputs = {
        DIST / "archiguard.zip": collect_extension(),
        DIST / "archiguard-preset.zip": collect_preset(),
    }
    sums = []
    for target, entries in outputs.items():
        build_zip(target, entries)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        sums.append(f"{digest}  {target.name}")
        print(f"built {target.relative_to(ROOT)} ({len(entries)} files) sha256={digest}")
    workflow_out = DIST / "archiguard-sdd.yml"
    shutil.copyfile(WORKFLOW, workflow_out)
    sums.append(f"{hashlib.sha256(workflow_out.read_bytes()).hexdigest()}  {workflow_out.name}")
    (DIST / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(f"version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

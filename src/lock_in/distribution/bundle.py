"""Validate complete release payloads before an installation is activated."""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

MANIFEST = "bundle.json"
REQUIRED = {
    "lock-in.exe",
    "lock-in-production-native-host.exe",
    "lock-in-setup.exe",
    "extension/manifest.json",
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_child(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if (
        not relative
        or parts.is_absolute()
        or ".." in parts.parts
        or "\\" in relative
        or ":" in relative
    ):
        raise ValueError("Invalid relative installation path")
    candidate = root.joinpath(*parts.parts)
    if (
        not candidate.resolve().is_relative_to(root.resolve())
        or candidate.resolve() == root.resolve()
    ):
        raise ValueError("Installation path escapes its root")
    current = candidate
    while current != root:
        if current.is_symlink() or current.is_junction():
            raise ValueError("Installation cannot contain links or junctions")
        current = current.parent
    return candidate


def write_manifest(bundle: Path, version: str, schema: int) -> dict:
    files = {
        path.relative_to(bundle).as_posix(): sha256(path)
        for path in sorted(bundle.rglob("*"))
        if path.is_file() and path != bundle / MANIFEST
    }
    value = {
        "product": "Lock-In",
        "format": 1,
        "version": version,
        "schema": schema,
        "files": files,
    }
    (bundle / MANIFEST).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value


def validate_bundle(bundle: Path) -> dict:
    value = json.loads((bundle / MANIFEST).read_text(encoding="utf-8"))
    if value.get("product") != "Lock-In" or value.get("format") != 1:
        raise ValueError("Not a supported Lock-In release")
    if not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+(?:[-a-zA-Z0-9.]*)", value.get("version", "")
    ):
        raise ValueError("Invalid release version")
    files = value.get("files")
    if (
        not isinstance(files, dict)
        or not REQUIRED <= files.keys()
        or not isinstance(value.get("schema"), int)
    ):
        raise ValueError("Incomplete release manifest")
    for name, digest in files.items():
        path = safe_child(bundle, name)
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f"Missing or damaged release file: {name}")
    for path in bundle.rglob("*"):
        safe_child(bundle, path.relative_to(bundle).as_posix())
    actual = {
        p.relative_to(bundle).as_posix()
        for p in bundle.rglob("*")
        if p.is_file() and p != bundle / MANIFEST
    }
    if actual != files.keys():
        raise ValueError("Unexpected release files; use a clean extracted bundle")
    return value

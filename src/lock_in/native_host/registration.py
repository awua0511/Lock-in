"""Register Experiment 3 Native Messaging manifests for Chrome and Edge."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

if os.name == "nt":
    import winreg


HOST_NAME = "com.lockin.experiment3"
EXTENSION_ID_PATTERN = re.compile(r"^[a-p]{32}$")
REGISTRY_PATHS = {
    "chrome": rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}",
    "edge": rf"Software\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}",
}


def validate_extension_ids(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not EXTENSION_ID_PATTERN.fullmatch(normalized):
            raise ValueError(f"Invalid Chromium extension ID: {value}")
        if normalized not in unique:
            unique.append(normalized)
    return unique


def manifest_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LockIn" / "NativeMessaging"


def native_host_executable() -> Path:
    candidate = Path(sys.executable).resolve().parent / "lock-in-native-host.exe"
    if not candidate.is_file():
        raise FileNotFoundError(
            f"Native Host entry point not found: {candidate}. Reinstall the project first."
        )
    return candidate


def register_browser(browser: str, extension_ids: list[str]) -> Path:
    ids = validate_extension_ids(extension_ids)
    if not ids:
        raise ValueError(f"At least one {browser} extension ID is required")
    directory = manifest_directory()
    directory.mkdir(parents=True, exist_ok=True)
    path = (directory / f"{HOST_NAME}.{browser}.json").resolve()
    manifest = {
        "name": HOST_NAME,
        "description": "Lock-In Experiment 3 Native Messaging relay",
        "path": str(native_host_executable()),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{value}/" for value in ids],
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATHS[browser]) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(path))
    return path


def unregister_browser(browser: str) -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATHS[browser])
    except FileNotFoundError:
        pass
    path = manifest_directory() / f"{HOST_NAME}.{browser}.json"
    path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Register the Experiment 3 Native Messaging Host.",
    )
    parser.add_argument("--chrome-extension-id", action="append", default=[])
    parser.add_argument("--edge-extension-id", action="append", default=[])
    parser.add_argument("--uninstall", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if os.name != "nt":
        print("Native Messaging registration requires Windows.", file=sys.stderr)
        return 2
    if args.uninstall:
        unregister_browser("chrome")
        unregister_browser("edge")
        print("Experiment 3 Native Messaging registration removed.")
        return 0
    if not args.chrome_extension_id and not args.edge_extension_id:
        print("Provide at least one Chrome or Edge extension ID.", file=sys.stderr)
        return 2
    try:
        if args.chrome_extension_id:
            path = register_browser("chrome", args.chrome_extension_id)
            print(f"Chrome manifest: {path}")
        if args.edge_extension_id:
            path = register_browser("edge", args.edge_extension_id)
            print(f"Edge manifest: {path}")
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

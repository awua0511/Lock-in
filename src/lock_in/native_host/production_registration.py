"""Register the production Native Messaging Host for Chrome and Edge."""

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

HOST_NAME = "com.lockin.desktop"
_EXTENSION_ID = re.compile(r"^[a-p]{32}$")
_REGISTRY_PATHS = {
    "chrome": rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}",
    "edge": rf"Software\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}",
}


def register_browser(browser: str, extension_ids: list[str]) -> Path:
    if browser not in _REGISTRY_PATHS:
        raise ValueError("browser must be chrome or edge")
    normalized = list(dict.fromkeys(value.strip().lower() for value in extension_ids))
    if not normalized or any(
        not _EXTENSION_ID.fullmatch(value) for value in normalized
    ):
        raise ValueError(
            "Provide one or more valid 32-character Chromium extension IDs"
        )
    executable = (
        Path(sys.executable).resolve().parent / "lock-in-production-native-host.exe"
    )
    if not executable.is_file():
        raise FileNotFoundError(f"Production Native Host not found: {executable}")
    directory = (
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LockIn" / "NativeMessaging"
    )
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / f"{HOST_NAME}.{browser}.json"
    manifest = {
        "name": HOST_NAME,
        "description": "Lock-In browser context relay",
        "path": str(executable),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{value}/" for value in normalized],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REGISTRY_PATHS[browser]) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(manifest_path))
    return manifest_path


def unregister_browser(browser: str) -> None:
    if browser not in _REGISTRY_PATHS:
        raise ValueError("browser must be chrome or edge")
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _REGISTRY_PATHS[browser])
    except FileNotFoundError:
        pass
    directory = (
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LockIn" / "NativeMessaging"
    )
    (directory / f"{HOST_NAME}.{browser}.json").unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Register Lock-In browser integration."
    )
    parser.add_argument("--chrome-extension-id", action="append", default=[])
    parser.add_argument("--edge-extension-id", action="append", default=[])
    parser.add_argument("--uninstall", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if os.name != "nt":
        return 2
    args = build_parser().parse_args(argv)
    if args.uninstall:
        unregister_browser("chrome")
        unregister_browser("edge")
        return 0
    if not args.chrome_extension_id and not args.edge_extension_id:
        return 2
    try:
        if args.chrome_extension_id:
            print(register_browser("chrome", args.chrome_extension_id))
        if args.edge_extension_id:
            print(register_browser("edge", args.edge_extension_id))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

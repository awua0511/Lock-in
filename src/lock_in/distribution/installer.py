"""Recoverable per-user deployment. User databases are never removed or replaced."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

from lock_in.distribution.bundle import safe_child, validate_bundle
from lock_in.native_host.production_registration import (
    _EXTENSION_ID,
    _REGISTRY_PATHS,
    HOST_NAME,
)

STATE = "installation.json"
JOURNAL = "pending-installation.json"
OWNER = ".lock-in-installation"


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


class UserRegistry:
    """Register both views: Chrome checks the 32-bit view before the 64-bit view."""

    def __init__(self, paths=None) -> None:
        import winreg

        self.api = winreg
        self.paths = paths or _REGISTRY_PATHS

    def read(self, browser: str) -> list[str | None]:
        reg = self.api
        result = []
        for view in (reg.KEY_WOW64_32KEY, reg.KEY_WOW64_64KEY):
            try:
                with reg.OpenKey(
                    reg.HKEY_CURRENT_USER,
                    self.paths[browser],
                    0,
                    reg.KEY_READ | view,
                ) as key:
                    result.append(reg.QueryValueEx(key, None)[0])
            except FileNotFoundError:
                result.append(None)
        return result

    def write(self, browser: str, values: list[str | None]) -> None:
        reg = self.api
        for view, value in zip(
            (reg.KEY_WOW64_32KEY, reg.KEY_WOW64_64KEY), values, strict=True
        ):
            if value is None:
                try:
                    reg.DeleteKeyEx(reg.HKEY_CURRENT_USER, self.paths[browser], view, 0)
                except FileNotFoundError:
                    pass
            else:
                with reg.CreateKeyEx(
                    reg.HKEY_CURRENT_USER,
                    self.paths[browser],
                    0,
                    reg.KEY_WRITE | view,
                ) as key:
                    reg.SetValueEx(key, None, 0, reg.REG_SZ, value)


class Installation:
    def __init__(self, root: Path, registry) -> None:
        self.root = root.absolute()
        self.registry = registry

    def _path(self, relative: str) -> Path:
        return safe_child(self.root, relative)

    def _owned(self) -> None:
        if self.root.is_symlink() or self.root.is_junction():
            raise ValueError("Installation root cannot be a link")
        if self.root == Path(self.root.anchor) or self.root == Path.home():
            raise ValueError("Refusing a broad installation directory")
        if not self.root.exists():
            self.root.mkdir(parents=True)
        marker = self._path(OWNER)
        if not marker.exists():
            if any(self.root.iterdir()):
                raise ValueError("Destination is not an owned Lock-In installation")
            atomic_write(marker, b"Lock-In per-user installation v1\n")
        if marker.read_bytes() != b"Lock-In per-user installation v1\n":
            raise ValueError("Invalid installation owner marker")

    def state(self) -> dict:
        path = self._path(STATE)
        if not path.exists():
            return {}
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("product") != "Lock-In":
            raise ValueError("Invalid installation state; nothing was removed")
        return state

    def recover(self) -> None:
        """An interrupted activation is rolled back before any new operation."""
        journal_path = self._path(JOURNAL)
        if not journal_path.exists():
            return
        value = json.loads(journal_path.read_text(encoding="utf-8"))
        if value.get("product") != "Lock-In":
            raise ValueError("Invalid installation recovery journal")
        for browser, values in value["registry"].items():
            self.registry.write(browser, values)
        for relative, previous in value["files"].items():
            path = self._path(relative)
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, base64.b64decode(previous, validate=True))
        journal_path.unlink()

    def _activate(self, state: dict) -> None:
        bundle = self._path("versions/" + state["current"])
        validate_bundle(bundle)
        updates = {
            STATE: encoded(state),
            "Start Lock-In.cmd": (
                f'@echo off\r\nstart "" "%~dp0versions\\{state["current"]}\\lock-in.exe"\r\n'
            ).encode(),
        }
        for path in (bundle / "extension").iterdir():
            if path.is_file():
                updates["extension/" + path.name] = path.read_bytes()
        for browser, ids in state["extension_ids"].items():
            updates[f"manifests/{browser}.json"] = encoded(
                {
                    "name": HOST_NAME,
                    "description": "Lock-In browser context relay",
                    "path": str(bundle / "lock-in-production-native-host.exe"),
                    "type": "stdio",
                    "allowed_origins": [
                        f"chrome-extension://{value}/" for value in ids
                    ],
                }
            )
        snapshot = {
            "product": "Lock-In",
            "registry": {
                browser: self.registry.read(browser)
                for browser in state["extension_ids"]
            },
            "files": {
                name: base64.b64encode(self._path(name).read_bytes()).decode("ascii")
                if self._path(name).exists()
                else None
                for name in updates
            },
        }
        atomic_write(self._path(JOURNAL), encoded(snapshot))
        try:
            for name, data in updates.items():
                atomic_write(self._path(name), data)
            for browser in state["extension_ids"]:
                manifest = str(self._path(f"manifests/{browser}.json"))
                self.registry.write(browser, [manifest, manifest])
            self._path(JOURNAL).unlink()
        except BaseException:
            self.recover()
            raise

    def install(self, source: Path, extension_ids: dict[str, list[str]]) -> dict:
        source = source.resolve()
        metadata = validate_bundle(source)
        for browser, ids in extension_ids.items():
            if (
                browser not in _REGISTRY_PATHS
                or not ids
                or any(not _EXTENSION_ID.fullmatch(value) for value in ids)
            ):
                raise ValueError("Invalid browser or extension ID")
        self._owned()
        self.recover()
        old = self.state()
        if old:
            current_metadata = validate_bundle(self._path("versions/" + old["current"]))
            if metadata["schema"] < current_metadata["schema"]:
                raise ValueError("Unsafe schema downgrade; use a compatible release")
        release = "release-" + uuid.uuid4().hex
        destination = self._path("versions/" + release)
        destination.parent.mkdir(exist_ok=True)
        # Copy to a unique inactive directory. No existing runtime is overwritten.
        shutil.copytree(source, destination)
        validate_bundle(destination)
        origins = {**old.get("extension_ids", {}), **extension_ids}
        previous_registration = dict(old.get("previous_registration", {}))
        for browser in origins:
            previous_registration.setdefault(browser, self.registry.read(browser))
        state = {
            "product": "Lock-In",
            "current": release,
            "previous": old.get("current"),
            "version": metadata["version"],
            "schema": metadata["schema"],
            "extension_ids": origins,
            "previous_registration": previous_registration,
            "releases": [*old.get("releases", []), release],
        }
        self._activate(state)
        return state

    def rollback(self) -> dict:
        self._owned()
        self.recover()
        old = self.state()
        if not old.get("previous"):
            raise ValueError("No previous release is available")
        previous = validate_bundle(self._path("versions/" + old["previous"]))
        if previous["schema"] != old["schema"]:
            raise ValueError(
                "Rollback would cross database schemas; data is preserved and rollback refused"
            )
        state = {
            **old,
            "current": old["previous"],
            "previous": old["current"],
            "version": previous["version"],
        }
        self._activate(state)
        return state

    def uninstall(self) -> None:
        self._owned()
        self.recover()
        state = self.state()
        # Recover browser registrations that preceded this installation, but
        # never remove another installation's newer registration.
        for browser in state.get("extension_ids", {}):
            owned = str(self._path(f"manifests/{browser}.json"))
            current = self.registry.read(browser)
            previous = state["previous_registration"][browser]
            self.registry.write(
                browser,
                [
                    previous[i] if value == owned else value
                    for i, value in enumerate(current)
                ],
            )
        # Delete only individually validated release subdirectories, never root
        # or the separate user-data directory. Interrupted copies are included.
        versions = self._path("versions")
        if versions.exists():
            for path in versions.iterdir():
                if not re.fullmatch(r"release-[a-f0-9]{32}", path.name):
                    continue
                safe_child(self.root, path.relative_to(self.root).as_posix())
                for child in path.rglob("*"):
                    safe_child(self.root, child.relative_to(self.root).as_posix())
                shutil.rmtree(path)
            if not any(versions.iterdir()):
                versions.rmdir()
        for folder in ("extension", "manifests"):
            directory = self._path(folder)
            if directory.exists():
                for file in directory.iterdir():
                    safe_child(
                        self.root, file.relative_to(self.root).as_posix()
                    ).unlink()
                directory.rmdir()
        self._path("Start Lock-In.cmd").unlink(missing_ok=True)
        self._path(STATE).unlink(missing_ok=True)
        self._path(OWNER).unlink()
        if not any(self.root.iterdir()):
            self.root.rmdir()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Install, roll back or remove Lock-In for this Windows user. Data is always kept."
    )
    parser.add_argument("action", choices=("install", "rollback", "uninstall"))
    parser.add_argument("--bundle", type=Path, default=Path(sys.executable).parent)
    parser.add_argument("--chrome-extension-id", action="append", default=[])
    parser.add_argument("--edge-extension-id", action="append", default=[])
    args = parser.parse_args(argv)
    if os.name != "nt":
        return 2
    from lock_in.platform.windows.local_identity import (
        SingleInstanceMutex,
        application_mutex_name,
    )

    root = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "LockIn"
    if args.action == "uninstall" and Path(sys.executable).resolve().is_relative_to(
        root.resolve()
    ):
        print(
            "Run setup from the original extracted download, not the installed folder.",
            file=sys.stderr,
        )
        return 2
    with SingleInstanceMutex(application_mutex_name()) as mutex:
        if mutex.already_exists:
            print(
                "Exit Lock-In from the tray before changing its installation.",
                file=sys.stderr,
            )
            return 2
        try:
            installation = Installation(root, UserRegistry())
            if args.action == "install":
                ids = {
                    browser: values
                    for browser, values in (
                        ("chrome", args.chrome_extension_id),
                        ("edge", args.edge_extension_id),
                    )
                    if values
                }
                installation.install(args.bundle, ids)
                print(f"Installed: {root / 'Start Lock-In.cmd'}")
                print(f"Unpacked browser extension: {root / 'extension'}")
            elif args.action == "rollback":
                installation.rollback()
                print("Previous compatible release restored. User data was kept.")
            else:
                installation.uninstall()
                print(
                    "Application and owned browser registrations removed. User data was kept."
                )
        except (OSError, ValueError, KeyError) as error:
            print(f"Setup could not complete: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

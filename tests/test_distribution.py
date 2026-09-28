from __future__ import annotations

import json
from pathlib import Path

import pytest

from lock_in.distribution.bundle import validate_bundle, write_manifest
from lock_in.distribution.installer import JOURNAL, STATE, Installation, encoded


class Registry:
    def __init__(self):
        self.values = {"chrome": [None, None], "edge": [None, None]}
        self.fail = False

    def read(self, browser):
        return list(self.values[browser])

    def write(self, browser, values):
        if self.fail:
            self.fail = False
            raise OSError("injected registry failure")
        self.values[browser] = list(values)


def bundle(path: Path, version="0.1.0", schema=3):
    path.mkdir()
    for name in (
        "lock-in.exe",
        "lock-in-production-native-host.exe",
        "lock-in-setup.exe",
    ):
        (path / name).write_bytes(version.encode())
    (path / "extension").mkdir()
    (path / "extension/manifest.json").write_text("{}", encoding="utf-8")
    write_manifest(path, version, schema)
    return path


def test_install_upgrade_rollback_uninstall_preserve_user_data_and_registration(
    tmp_path,
):
    registry = Registry()
    registry.values["chrome"] = ["developer-manifest", None]
    installation = Installation(tmp_path / "programs", registry)
    data = tmp_path / "user-data"
    data.mkdir()
    (data / "settings").write_bytes(b"preserve")
    source = bundle(tmp_path / "bundle")
    first = installation.install(source, {"chrome": ["a" * 32]})
    assert all(registry.values["chrome"])
    second = installation.install(bundle(tmp_path / "new", "0.1.1"), {})
    assert second["previous"] == first["current"]
    assert installation.rollback()["current"] == first["current"]
    assert (installation.root / "extension/manifest.json").exists()
    assert (installation.root / "Start Lock-In.cmd").exists()
    installation.uninstall()
    assert registry.values["chrome"] == ["developer-manifest", None]
    assert not installation.root.exists()
    assert (data / "settings").read_bytes() == b"preserve"


def test_partial_or_modified_bundle_never_replaces_working_install(tmp_path):
    installation = Installation(tmp_path / "programs", Registry())
    good = bundle(tmp_path / "good")
    first = installation.install(good, {})
    bad = bundle(tmp_path / "bad", "0.1.1")
    (bad / "lock-in.exe").unlink()
    with pytest.raises(ValueError):
        installation.install(bad, {})
    assert installation.state() == first
    (good / "lock-in.exe").write_bytes(b"modified")
    with pytest.raises(ValueError):
        validate_bundle(good)


def test_registry_failure_rolls_back_state_manifest_and_extension(tmp_path):
    registry = Registry()
    installation = Installation(tmp_path / "programs", registry)
    old = installation.install(bundle(tmp_path / "old"), {"chrome": ["a" * 32]})
    manifest = (installation.root / "manifests/chrome.json").read_bytes()
    registry.fail = True
    with pytest.raises(OSError):
        installation.install(bundle(tmp_path / "new", "0.1.1"), {})
    assert installation.state() == old
    assert (installation.root / "manifests/chrome.json").read_bytes() == manifest
    assert not (installation.root / JOURNAL).exists()


def test_recovery_journal_restores_interrupted_activation(tmp_path):
    registry = Registry()
    installation = Installation(tmp_path / "programs", registry)
    installation.install(bundle(tmp_path / "bundle"), {})
    (installation.root / "partial-file").write_bytes(b"partial")
    (installation.root / JOURNAL).write_bytes(
        encoded(
            {
                "product": "Lock-In",
                "registry": {"chrome": [None, None]},
                "files": {"partial-file": None},
            }
        )
    )
    installation.recover()
    assert not (installation.root / "partial-file").exists()


def test_rollback_refuses_schema_downgrade(tmp_path):
    installation = Installation(tmp_path / "programs", Registry())
    installation.install(bundle(tmp_path / "old", schema=3), {})
    installation.install(bundle(tmp_path / "new", "0.2.0", schema=4), {})
    with pytest.raises(ValueError, match="database schemas"):
        installation.rollback()


def test_uninstall_does_not_remove_newer_external_registration(tmp_path):
    registry = Registry()
    installation = Installation(tmp_path / "programs", registry)
    installation.install(bundle(tmp_path / "bundle"), {"edge": ["b" * 32]})
    registry.values["edge"] = ["another-installation", "another-installation"]
    installation.uninstall()
    assert registry.values["edge"] == ["another-installation", "another-installation"]


def test_unsafe_or_unowned_targets_are_rejected(tmp_path):
    root = tmp_path / "unrelated"
    root.mkdir()
    (root / "user-file").write_bytes(b"keep")
    with pytest.raises(ValueError, match="owned"):
        Installation(root, Registry()).uninstall()
    source = bundle(tmp_path / "bundle")
    manifest = json.loads((source / "bundle.json").read_text())
    manifest["files"]["../user-file"] = "wrong"
    (source / "bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_bundle(source)
    assert (root / "user-file").read_bytes() == b"keep"


def test_corrupted_installation_state_is_not_silently_reset(tmp_path):
    installation = Installation(tmp_path / "programs", Registry())
    installation.install(bundle(tmp_path / "bundle"), {})
    (installation.root / STATE).write_text("corrupted", encoding="utf-8")
    with pytest.raises(ValueError):
        installation.uninstall()
    assert (installation.root / "Start Lock-In.cmd").exists()

"""Build a new, isolated onedir candidate; never overwrite an older candidate."""

import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from importlib.metadata import distribution
from pathlib import Path

from lock_in.app.config import APPLICATION_VERSION
from lock_in.distribution.bundle import validate_bundle, write_manifest
from lock_in.storage.migrations import MIGRATIONS

ROOT = Path(__file__).resolve().parents[1]


def main():
    candidate = "candidate-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = ROOT / "dist" / candidate
    destination.mkdir(parents=True, exist_ok=False)
    # Do not collect unrelated DLLs from tools injected into the caller's PATH.
    # In particular, another ICU distribution can shadow Windows' ICU API.
    environment = os.environ.copy()
    windows = Path(os.environ["WINDIR"])
    environment["PATH"] = os.pathsep.join(
        map(
            str,
            (
                Path(sys.executable).parent,
                Path(sys.base_prefix),
                windows / "System32",
                windows,
            ),
        )
    )
    environment.pop("PYTHONPATH", None)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(ROOT / "packaging/lock-in.spec"),
            "--distpath",
            str(destination),
            "--workpath",
            str(ROOT / "build" / candidate),
        ],
        check=True,
        cwd=ROOT,
        env=environment,
    )
    bundle = destination / "LockIn"
    shutil.copytree(ROOT / "browser_extension/production", bundle / "extension")
    shutil.copy2(ROOT / "MILESTONE_07.md", bundle / "MILESTONE_07.md")
    dependencies = {}
    for name in ("PyInstaller", "PySide6-Essentials", "shiboken6", "idna", "tzdata"):
        package = distribution(name)
        dependencies[name] = package.version
        for file in package.files or ():
            # Preserve the license files supplied by each installed wheel.
            if "licenses" in file.parts and ".dist-info" in file.parts[0]:
                destination_file = bundle / "THIRD_PARTY_LICENSES" / name / file.name
                destination_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(package.locate_file(file), destination_file)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, bundle / "THIRD_PARTY_LICENSES/Python-LICENSE.txt")
    (bundle / "build-info.json").write_text(
        json.dumps(
            {
                "application_version": APPLICATION_VERSION,
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "dependencies": dependencies,
                "signed": False,
                "public_distribution_approved": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_manifest(bundle, APPLICATION_VERSION, MIGRATIONS[-1].version)
    validate_bundle(bundle)
    archive = shutil.make_archive(
        str(destination / f"LockIn-{APPLICATION_VERSION}-windows-x64"),
        "zip",
        destination,
        "LockIn",
    )
    print(json.dumps({"bundle": str(bundle), "archive": archive}))


if __name__ == "__main__":
    main()

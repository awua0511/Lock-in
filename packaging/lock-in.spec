# Three entry points share one onedir runtime. Host must keep binary stdio;
# desktop must not create a console window. No admin manifest is requested.
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
analyses, executables = [], []
for entry, name, console in (
    ("desktop.py", "lock-in", False),
    ("host.py", "lock-in-production-native-host", True),
    ("setup.py", "lock-in-setup", True),
):
    analysis = Analysis(
        [str(root / "packaging" / entry)],
        pathex=[str(root / "src")],
        datas=collect_data_files("tzdata") if entry == "desktop.py" else [],
        excludes=["tkinter", "pytest", "psutil"],
    )
    allowed = [
        Path(sys.prefix).resolve(),
        Path(sys.base_prefix).resolve(),
        Path(os.environ["WINDIR"]).resolve(),
    ]
    for destination, source, kind in analysis.binaries:
        if not any(Path(source).resolve().is_relative_to(base) for base in allowed):
            raise RuntimeError(
                f"Unexpected binary dependency outside Python/Windows: {destination}. "
                "Use scripts/build_release.py with its clean PATH."
            )
    exe = EXE(
        PYZ(analysis.pure), analysis.scripts, [],
        exclude_binaries=True, name=name, console=console, upx=False,
    )
    analyses.append(analysis)
    executables.append(exe)
coll = COLLECT(
    *executables,
    *(table for analysis in analyses for table in (analysis.binaries, analysis.datas)),
    name="LockIn", upx=False,
)

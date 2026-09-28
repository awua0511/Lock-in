import json
import sys
import traceback
from multiprocessing import freeze_support
from pathlib import Path

from lock_in.app.main import main

if __name__ == "__main__":
    freeze_support()
    try:
        code = main()
    except Exception as error:
        # Windowed bootloaders have no stderr. Explicit diagnostics opt in to a
        # local traceback (no locals); normal launches show only a safe message.
        if "--diagnostics-file" in sys.argv:
            index = sys.argv.index("--diagnostics-file")
            path = Path(sys.argv[index + 1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "startup_error": type(error).__name__,
                        "traceback": traceback.format_exc(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        else:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                "Lock-In could not start. Your data has not been reset. Please re-extract the complete package or contact the developer.",
                "Lock-In startup error",
                0x10,
            )
        code = 1
    raise SystemExit(code)

"""Child entry point: windowed builds capture output without opening the GUI."""
import contextlib
from pathlib import Path
import runpy
import traceback


def run_script(filename: str) -> int:
    script = Path(filename)
    with (script.parent / "stdout.txt").open("w", encoding="utf-8") as out, (script.parent / "stderr.txt").open("w", encoding="utf-8") as err:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                runpy.run_path(str(script), run_name="__main__")
            except SystemExit as exc:
                if exc.code is None:
                    return 0
                if isinstance(exc.code, int):
                    return exc.code
                print(exc.code, file=err)
                return 1
            except BaseException:
                traceback.print_exc()
                return 1
    return 0

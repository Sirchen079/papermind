"""Child entry point: windowed builds capture output without opening the GUI."""
import contextlib
from pathlib import Path
import runpy
import json
import sys
import traceback


def run_script(filename: str, args: list[str] | None = None, output_dir: str | None = None) -> int:
    script = Path(filename)
    work = Path(output_dir) if output_dir else script.parent
    previous = sys.argv
    sys.argv = [str(script), *(args or [])]
    try:
        return _execute(script, work)
    finally:
        sys.argv = previous


def _execute(script: Path, work: Path) -> int:
    with (work / "stdout.txt").open("w", encoding="utf-8") as out, (work / "stderr.txt").open("w", encoding="utf-8") as err:
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


def run_job(filename: str) -> int:
    job = json.loads(Path(filename).read_text(encoding='utf-8'))
    return run_script(job['script'], job['args'], str(Path(filename).parent))


if __name__ == '__main__':
    raise SystemExit(run_job(sys.argv[1]))

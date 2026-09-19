"""PaperMind executable entry point: desktop window by default.

PAPERMIND_NO_BROWSER=1 is an explicit headless diagnostic mode.
"""
import multiprocessing
import os
import sys

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


def main() -> None:
    if sys.argv[1:] == ["--desktop-smoke-test"]:
        from app.desktop import main as desktop_main
        desktop_main(smoke_test=True)
        return
    if len(sys.argv) > 1 and sys.argv[1] == '--application-archive':
        from app.archive.application_cli import main as archive_main
        raise SystemExit(archive_main(sys.argv[2:]))
    if len(sys.argv) == 3 and sys.argv[1] == "--run-skill":
        from app.skills.worker import run_script
        raise SystemExit(run_script(sys.argv[2]))
    if os.environ.get("PAPERMIND_NO_BROWSER"):
        # A windowed Windows executable has no stdout/stderr. Uvicorn's
        # formatter probes stdout.isatty(), even in headless diagnostic mode.
        if sys.stdout is None or sys.stderr is None:
            from app.paths import default_data_dir
            directory = default_data_dir() / 'logs'
            directory.mkdir(parents=True, exist_ok=True)
            stream = (directory / 'headless.log').open('a', encoding='utf-8', buffering=1)
            if sys.stdout is None:
                sys.stdout = stream
            if sys.stderr is None:
                sys.stderr = stream
        try:
            import uvicorn
            from app.main import create_app
            uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("PAPERMIND_PORT", "4278")), log_level="info")
        except Exception:
            import traceback
            traceback.print_exc()
            raise SystemExit(1)
    else:
        from app.desktop import main as desktop_main
        desktop_main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

import ctypes
import logging
from logging.handlers import RotatingFileHandler
import sys

from souls_studio import APP_NAME, __version__
from souls_studio.paths import DATA


def main():
    stream = None
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(DATA / "effigy.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler],
                            format="%(asctime)s %(levelname)s %(name)s %(message)s")
        if sys.stdout is None or sys.stderr is None:
            stream = (DATA / "runtime.log").open("w", encoding="utf-8", buffering=1)
            sys.stdout = sys.stdout or stream
            sys.stderr = sys.stderr or stream
        logging.info("%s %s", APP_NAME, __version__)
        from souls_studio.app import main as run
        run()
    except Exception:
        logging.exception("Startup failed")
        ctypes.windll.user32.MessageBoxW(
            None, f"Effigy Exporter could not start.\n\nLog: {DATA / 'effigy.log'}", APP_NAME, 0x10)
        return 1
    finally:
        if stream:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
            stream.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

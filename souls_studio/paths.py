import os
from pathlib import Path
import sys


PACKAGE = Path(__file__).resolve().parent
RESOURCES = PACKAGE / "resources"
LOCAL_DATA = Path(os.environ["LOCALAPPDATA"])
DATA = LOCAL_DATA / "EffigyExporter"
LEGACY_DATA = LOCAL_DATA / "SoulsAssetStudio"
DEFAULT_RUNTIME = Path(sys._MEIPASS) / "runtime" if getattr(sys, "frozen", False) else PACKAGE.parent / "build/runtime"
RUNTIME = Path(os.environ.get("EFFIGY_RUNTIME") or os.environ.get("SOULS_STUDIO_HOME") or DEFAULT_RUNTIME)

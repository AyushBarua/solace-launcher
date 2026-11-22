import os
import sys

def get_data_dir() -> str:
    """Returns the writable data directory (e.g. %LOCALAPPDATA%\Solace).

    Override with the SOLACE_DATA_DIR environment variable to point both
    dev and frozen modes at the same directory for testing:
        set SOLACE_DATA_DIR=C:\\Users\\me\\AppData\\Local\\Solace
    """
    # Explicit override wins over everything — useful for testing & CI
    override = os.environ.get("SOLACE_DATA_DIR", "").strip()
    if override:
        d = override
    elif getattr(sys, 'frozen', False):
        appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        d = os.path.join(appdata, "Solace")
    else:
        d = os.path.join(os.path.dirname(__file__), "..", "dev_data")

    os.makedirs(d, exist_ok=True)
    return os.path.normpath(d)

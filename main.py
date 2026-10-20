import os
import subprocess as sub
import sys

VENV = "myenv"
REQUIREMENTS = "requirements.txt"

from setup import environment

is_relaunch = os.environ.get("DESKTOP_INTELLIGENCE_RELAUNCHED") == "1"

# Skip setup.environment when already running in relaunched virtual environment
if not is_relaunch:
    environment(VENV, REQUIREMENTS)

venv_python = os.path.join(
    os.getcwd(),
    VENV,
    "Scripts" if os.name == "nt" else "bin",
    "python.exe" if os.name == "nt" else "python"
)

if os.path.exists(venv_python) and not is_relaunch:
    current_exe = os.path.normcase(os.path.abspath(sys.executable))
    target_exe = os.path.normcase(os.path.abspath(venv_python))
    if current_exe != target_exe:
        env = os.environ.copy()
        env["DESKTOP_INTELLIGENCE_RELAUNCHED"] = "1"
        try:
            res = sub.run([venv_python, __file__] + sys.argv[1:], env=env)
            sys.exit(res.returncode)
        except KeyboardInterrupt:
            sys.exit(130)

import matplotlib as mp
import numpy as np
import pandas as pd


def main(argv=None):
    try:
        from desktop_intelligence.app import main as app_main
        return app_main(argv)
    except ModuleNotFoundError as err:
        if err.name and (err.name == "desktop_intelligence" or err.name.startswith("desktop_intelligence.")):
            sys.stderr.write(f"Failed to load Desktop Intelligence: {err}\n")
            return 1
        raise
    except ImportError as err:
        sys.stderr.write(f"Failed to load Desktop Intelligence dependencies: {err}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
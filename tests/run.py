"""Every check the build relies on, in one command.

    python3 tests/run.py

The unit tests, then the node checks on the built page. Exits 1 if anything fails.
"""
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


def main():
    ok = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(str(HERE.joinpath("tests")),
                                                                                     top_level_dir=str(HERE))).wasSuccessful()
    for script in sorted(HERE.joinpath("tests", "js").glob("check_*.js")):
        ok &= subprocess.run(["node", str(script)], cwd=HERE).returncode == 0
    print("All checks pass." if ok else "Something failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

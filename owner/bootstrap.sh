#!/bin/bash
# The owner's machine only. Checks the two tools the build and the runs need, Python 3.11 or newer and Node 18 or
# newer, then builds the page and runs every test. The build uses only Python's standard library and Node with no
# packages, so there's nothing to install.
# Run from the build folder:   bash owner/bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11 or newer is needed, and this is " + sys.version.split()[0])'
echo "Python $(python3 -c 'import sys; print(sys.version.split()[0])')"
if ! command -v node >/dev/null 2>&1; then
  echo "Node isn't installed. Install it with: brew install node"
  exit 1
fi
node -e 'const major = Number(process.versions.node.split(".")[0]); if (major < 18) { console.error("Node 18 or newer is needed"); process.exit(1); } console.log("Node " + process.versions.node);'
mkdir -p data/ai_runs
python3 build.py
if python3 tests/run.py >/dev/null 2>&1; then
  echo "Every test passes."
else
  echo "A test failed. See it with: python3 tests/run.py"
  exit 1
fi

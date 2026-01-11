#!/usr/bin/env bash
set -euo pipefail

python -m pip install -r requirements.txt
python -m playwright install chromium

echo "If playwright asks for system deps on Linux, install them via your distro package manager."


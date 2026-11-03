#!/bin/sh
# Builds a single SelectData executable (no Python needed where it runs).
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --onefile --name SelectData --collect-all pyreadstat selectdata.py
echo "Done: dist/SelectData"

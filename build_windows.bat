@echo off
REM Builds SelectData.exe (one file, no Python needed on the target PC).
REM Requires Python 3.10+ from python.org on the build machine (tick "Add to PATH").
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --onefile --name SelectData --collect-all pyreadstat selectdata.py
echo.
echo Done: dist\SelectData.exe
pause

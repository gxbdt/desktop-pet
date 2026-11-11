@echo off
cd /d "%~dp0"
where pythonw >nul 2>&1
if errorlevel 1 (
  echo 没有找到 Python，请先安装 Python 3.12，并运行: python -m pip install -r requirements.txt
  pause
  exit /b 1
)
start "" pythonw "%~dp0main.py"

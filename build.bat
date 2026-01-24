@echo off
echo ========================================
echo Video Scene Splitter - EXE Builder
echo ========================================
echo.

REM 仮想環境があれば有効化
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

REM ビルドスクリプトを実行
python scripts\build_exe.py

echo.
pause

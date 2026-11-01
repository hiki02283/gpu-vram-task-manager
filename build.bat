@echo off
title Building GPU VRAM Task Manager Standalone EXE...
echo ========================================================
echo  Building GPU VRAM Task Manager Standalone EXE
echo ========================================================
echo.
pyinstaller --noconfirm GPU_VRAM_Manager.spec
echo.
if exist "dist\GPU_VRAM_Manager.exe" (
    echo [SUCCESS] Built executable at: dist\GPU_VRAM_Manager.exe
) else (
    echo [ERROR] Build failed. Please check the logs above.
)
pause

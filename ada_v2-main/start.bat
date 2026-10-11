@echo off
title ANBU BLACK OPS V2
echo ============================================
echo   ANBU BLACK OPS V2 - Starting...
echo ============================================
echo.

:: Check if dist exists, build if not
if not exist "dist" (
    echo [1/2] Building frontend...
    call npm run build
    echo.
) else (
    echo [1/2] Frontend already built.
)

echo [2/2] Starting server on http://localhost:8000
echo.
echo   Press Ctrl+C to stop.
echo ============================================
echo.

python backend/server.py

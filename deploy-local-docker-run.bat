@echo off
echo.

REM ── Config ─────────────────────────────
set CONTAINER_NAME=dn-rsm-lens
set IMAGE_NAME=dn-rsm-lens
set IMAGE_TAG=latest
set PORT=8000
REM ──────────────────────────────────────

echo =====================================
echo   Running Docker Locally
echo   http://localhost:%PORT%
echo =====================================
echo.

echo [1/3] Checking if .env file exists...
if not exist .env (
  echo ERROR: .env file not found!
  echo Please create .env file with your GEMINI_API_KEY
  echo Copy from .env.example and add your API key
  pause
  exit /b 1
)

echo [2/3] Removing old container (if exists)...
docker rm -f %CONTAINER_NAME% >nul 2>&1

echo [3/3] Starting new container...
docker run -d -p %PORT%:%PORT% ^
  --env-file .env ^
  --name %CONTAINER_NAME% ^
  %IMAGE_NAME%:%IMAGE_TAG%

if %errorlevel% neq 0 (
  echo ERROR: Failed to start container!
  echo Make sure Docker is running and image exists
  echo Build image with: docker build -t %IMAGE_NAME%:%IMAGE_TAG% .
  pause
  exit /b 1
)

echo.
echo =====================================
echo   SUCCESS 🚀
echo   Container: %CONTAINER_NAME%
echo   Open: http://localhost:%PORT%
echo =====================================
echo.
echo Useful commands:
echo   View logs: docker logs -f %CONTAINER_NAME%
echo   Stop: docker stop %CONTAINER_NAME%
echo.

start http://localhost:%PORT%
pause
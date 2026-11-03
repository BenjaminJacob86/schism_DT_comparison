@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Build the scenario-comparison image from the repo root (parent of docker/).
rem   cd docker
rem   build.bat
rem
rem Run:
rem   docker run --rm -p 8080:8080 schism-scenario-hub:latest
rem Then open http://localhost:8080/
rem (5173 is only the local Vite dev server from start.bat)

docker build -t schism-scenario-hub:latest -f Dockerfile ..
if errorlevel 1 (
  echo Docker build failed.
  exit /b 1
)
echo.
echo Image schism-scenario-hub:latest ready.
echo docker run --rm -p 8080:8080 schism-scenario-hub:latest
endlocal

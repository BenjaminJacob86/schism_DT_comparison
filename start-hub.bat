@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem SCHISM scenario comparison hub (A / B / B−A).
rem Starts FastAPI (port 8000) and the Vite UI (port 5173).
rem Stop the single-run viewer first if it is using the same ports.
rem Open http://127.0.0.1:5173 after both windows say they are ready.
rem Edit named runs in config\scenarios.json

set "PY=%LOCALAPPDATA%\miniforge3\envs\schismview\python.exe"
if not exist "%PY%" (
  where python >nul 2>&1
  if errorlevel 1 (
    echo Could not find the schismview Python env:
    echo   %LOCALAPPDATA%\miniforge3\envs\schismview\python.exe
    echo Activate that conda env or edit PY in this script.
    pause
    exit /b 1
  )
  for /f "delims=" %%I in ('where python') do (
    set "PY=%%I"
    goto :py_ok
  )
)
:py_ok

set "NODEDIR=%LOCALAPPDATA%\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.19.0-win-x64"
if exist "%NODEDIR%\node.exe" set "PATH=%NODEDIR%;%PATH%"
where node >nul 2>&1
if errorlevel 1 (
  echo Node.js not found. Install Node 20+ or add it to PATH.
  pause
  exit /b 1
)

if not exist "frontend\node_modules\" (
  echo Installing frontend packages...
  pushd frontend
  call npm install
  if errorlevel 1 (
    echo npm install failed.
    popd
    pause
    exit /b 1
  )
  popd
)

set "OPENBLAS_NUM_THREADS=1"
set "HDF5_USE_FILE_LOCKING=FALSE"
set "DATA_SOURCE=s3"
set "APP_MODE=hub"
set "VITE_APP_MODE=hub"
set "S3_ENDPOINT=https://minio.dive.edito.eu"
set "S3_BUCKET=project-foccus"
set "S3_MODEL_PREFIX=DigitalTwinTest/model"
set "S3_ZARR_PREFIX=DigitalTwinTest/zarr/schism.zarr"
set "S3_BUILDINGS_PREFIX=DigitalTwinTest/Buildings/hamburg/area1"

echo Stopping any old API on port 8000 and UI on 5173 ...
powershell -NoProfile -Command "8000,5173 | ForEach-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }"
timeout /t 2 /nobreak >nul

echo Starting hub API on http://127.0.0.1:8000 ...
start "Scenario hub API" cmd /k "cd /d "%~dp0backend" && set OPENBLAS_NUM_THREADS=1&& set HDF5_USE_FILE_LOCKING=FALSE&& set DATA_SOURCE=%DATA_SOURCE%&& set APP_MODE=hub&& set S3_ENDPOINT=%S3_ENDPOINT%&& set S3_BUCKET=%S3_BUCKET%&& set S3_MODEL_PREFIX=%S3_MODEL_PREFIX%&& set S3_ZARR_PREFIX=%S3_ZARR_PREFIX%&& set S3_BUILDINGS_PREFIX=%S3_BUILDINGS_PREFIX%&& "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo Starting hub UI on http://127.0.0.1:5173 ...
start "Scenario hub UI" cmd /k "cd /d "%~dp0frontend" && set PATH=%NODEDIR%;%PATH%&& set VITE_APP_MODE=hub&& npm run dev"

echo Waiting a few seconds, then opening the browser...
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:5173/"

echo.
echo Two windows stay open: hub API and UI. Close them to stop the app.
echo Named scenarios: config\scenarios.json
endlocal

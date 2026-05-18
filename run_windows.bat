@echo off
setlocal EnableDelayedExpansion
echo Buscando PrusaSlicer...

if exist "C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe" (
  set "PRUSASLICER_PATH=C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe"
) else if exist "C:\Program Files\PrusaSlicer\prusa-slicer-console.exe" (
  set "PRUSASLICER_PATH=C:\Program Files\PrusaSlicer\prusa-slicer-console.exe"
) else if exist "C:\Program Files\Prusa3D\PrusaSlicer\PrusaSlicer.exe" (
  set "PRUSASLICER_PATH=C:\Program Files\Prusa3D\PrusaSlicer\PrusaSlicer.exe"
) else (
  echo No encontre prusa-slicer-console.exe en las rutas comunes.
  echo Si lo tienes instalado en otra ruta, ejecuta manualmente:
  echo set "PRUSASLICER_PATH=C:\ruta\a\prusa-slicer-console.exe"
  echo.
)

if defined PRUSASLICER_PATH (
  echo PrusaSlicer encontrado en: !PRUSASLICER_PATH!
)

python -m uvicorn server:app --host 127.0.0.1 --port 8000
pause

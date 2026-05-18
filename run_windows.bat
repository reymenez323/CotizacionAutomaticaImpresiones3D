@echo off
echo Buscando PrusaSlicer...

if exist "C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe" (
  set "PRUSASLICER_PATH=C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe"
  echo PrusaSlicer encontrado en: %PRUSASLICER_PATH%
) else if exist "C:\Program Files\PrusaSlicer\prusa-slicer-console.exe" (
  set "PRUSASLICER_PATH=C:\Program Files\PrusaSlicer\prusa-slicer-console.exe"
  echo PrusaSlicer encontrado en: %PRUSASLICER_PATH%
) else (
  echo No encontre prusa-slicer-console.exe en las rutas comunes.
  echo Si lo tienes instalado en otra ruta, ejecuta:
  echo set "PRUSASLICER_PATH=C:\ruta\a\prusa-slicer-console.exe"
  echo.
)

if "%ADMIN_PASSWORD%"=="" (
  set "ADMIN_PASSWORD=admin123"
)

set "DATABASE_PATH=%CD%\data\prototiposrd.db"
set "UPLOAD_DIR=%CD%\data\uploads"

echo.
echo Panel admin:
echo http://127.0.0.1:8000/admin
echo Contrasena admin por defecto: %ADMIN_PASSWORD%
echo.
echo Sitio cliente:
echo http://127.0.0.1:8000
echo.

python -m uvicorn server:app --host 127.0.0.1 --port 8000
pause

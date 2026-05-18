Write-Host "Actualizando pip, setuptools y wheel..."
python -m pip install --upgrade pip setuptools wheel

Write-Host "Instalando requerimientos..."
python -m pip install -r requirements.txt

Write-Host ""
Write-Host "Si todo instaló correctamente, ejecuta:"
Write-Host "python -m uvicorn server:app --reload --host 127.0.0.1 --port 8000"

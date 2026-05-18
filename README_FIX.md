# Fix aplicado

Se corrigió el error:

```text
NameError: name 'app' is not defined
```

Causa: el evento `@app.on_event("startup")` estaba declarado antes de crear `app = FastAPI(...)`.

Uso local:

```bat
run_windows.bat
```

Luego abre:

```text
http://127.0.0.1:8000
http://127.0.0.1:8000/admin
```

Contraseña admin por defecto local:

```text
admin123
```

Para producción cambia `ADMIN_PASSWORD`.

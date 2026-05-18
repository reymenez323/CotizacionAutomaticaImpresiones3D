# Fix de previsualización

Se corrigió la lógica de carga para evitar que el usuario suba archivos antes de que estén listos:

- catálogo de materiales desde la base de datos,
- visor 3D con Three.js.

La página ahora desactiva el input de archivos hasta que ambos estén disponibles.

## Importante

Esta versión ya no tiene materiales hardcoded. Por eso, si abres el HTML directamente con doble clic (`file://`), no podrá consultar `/api/materials` ni cargar el catálogo desde SQLite.

Para probar correctamente:

```bat
run_windows.bat
```

Luego abre:

```text
http://127.0.0.1:8000
```

No uses el HTML suelto para pruebas funcionales con base de datos.

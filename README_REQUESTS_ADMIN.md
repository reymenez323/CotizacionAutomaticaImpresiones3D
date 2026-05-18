# PrototiposRD - Solicitudes y panel admin

## Nuevas funciones

- Al presionar "Solicitar cotización", el cliente debe ingresar:
  - nombre,
  - correo,
  - teléfono,
  - notas opcionales.
- La solicitud se guarda en SQLite.
- Los archivos subidos se guardan en `data/uploads`.
- Se genera un código tipo `PRD-XXXXXXXX`.
- Se registra un historial de logs.
- El administrador puede:
  - aceptar,
  - mandar a corrección,
  - rechazar,
  - ignorar,
  - ver historial.
- Nada se borra desde el panel.

## Variables de entorno importantes

```text
ADMIN_PASSWORD=una_contraseña_segura
DATABASE_PATH=/app/data/prototiposrd.db
UPLOAD_DIR=/app/data/uploads
ADMIN_NOTIFICATION_EMAIL=admin@tudominio.com
```

## SMTP opcional para enviar copia al cliente

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu_correo@gmail.com
SMTP_PASSWORD=tu_app_password
SMTP_FROM=PrototiposRD <tu_correo@gmail.com>
SMTP_USE_TLS=true
```

Si SMTP no está configurado, la solicitud se guarda igualmente, pero no se enviará correo.

## Panel admin

```text
/admin
```

La contraseña se valida contra `ADMIN_PASSWORD`.

## Importante en Render

Para que SQLite y archivos sobrevivan reinicios, usa un Persistent Disk en Render o una base de datos externa.
En plan gratis, el almacenamiento local puede ser efímero.

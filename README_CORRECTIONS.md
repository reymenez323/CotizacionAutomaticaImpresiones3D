# PrototiposRD - Admin + correcciones

## Agregado en esta versión

### Formulario del cliente
El formulario de contacto al solicitar cotización fue rediseñado para verse más profesional.

### Archivos en admin
El panel `/admin` ahora permite descargar los archivos subidos por el cliente, incluyendo STL/OBJ/3MF y archivos corregidos.

### Flujo de corrección
Cuando el administrador elige **Mandar a corrección**:

1. Debe escribir la razón para el cliente.
2. Se guarda la acción en el log.
3. Se genera o reutiliza un enlace único de corrección.
4. Se intenta enviar correo al cliente con la razón y el enlace.
5. El cliente puede subir archivos corregidos desde `/correction/<token>`.
6. Los archivos corregidos se agregan a la misma solicitud; no se borra nada.
7. La solicitud vuelve al estado `new` para revisión.

## Variables recomendadas

```text
ADMIN_PASSWORD=una_contraseña_segura
PUBLIC_BASE_URL=https://tu-dominio.com
DATABASE_PATH=/app/data/prototiposrd.db
UPLOAD_DIR=/app/data/uploads
```

Para correos:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu_correo@gmail.com
SMTP_PASSWORD=tu_app_password
SMTP_FROM=PrototiposRD <tu_correo@gmail.com>
SMTP_USE_TLS=true
ADMIN_NOTIFICATION_EMAIL=admin@tudominio.com
```

`PUBLIC_BASE_URL` es importante en producción para que el enlace de corrección llegue con el dominio correcto.

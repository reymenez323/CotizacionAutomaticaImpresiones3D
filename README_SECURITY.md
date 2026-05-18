# PrototiposRD - Seguridad agregada

Esta versión agrega protecciones prácticas de ciberseguridad para el cotizador:

## Backend

- Rate limiting por IP para:
  - `/api/slice-batch`
  - `/api/quote-requests`
  - `/api/corrections`
  - `/api/admin`
- Límite de tamaño de request.
- Límite de tamaño por archivo.
- Límite de cantidad de archivos por solicitud.
- Validación de extensiones permitidas:
  - `.stl`
  - `.obj`
  - `.3mf`
  - `.step`
  - `.stp`
- Sanitización de nombres de archivo.
- Protección contra path traversal en descargas.
- Comparación de contraseña admin con `hmac.compare_digest`.
- Tokens de corrección generados con `secrets.token_urlsafe(32)`.
- Validación de correo, teléfono, notas y fecha compromiso.
- Headers de seguridad:
  - `Content-Security-Policy`
  - `X-Frame-Options`
  - `X-Content-Type-Options`
  - `Referrer-Policy`
  - `Permissions-Policy`
  - `Strict-Transport-Security` en HTTPS
- CORS restringido a `ALLOWED_ORIGINS`.
- Rechazo de `Origin` no permitido en métodos POST.

## Frontend/Admin

- La contraseña admin se guarda en `sessionStorage`, no en `localStorage`.
- Campos con `required`/`maxlength`.
- El botón admin sigue usando header `X-Admin-Password`; para producción real se recomienda migrar a sesiones/JWT con expiración.

## Variables recomendadas en producción

```text
ENVIRONMENT=production
ADMIN_PASSWORD=una_contraseña_larga_y_segura
PUBLIC_BASE_URL=https://tu-dominio.com
ALLOWED_ORIGINS=https://tu-dominio.com
ALLOWED_HOSTS=tu-dominio.com
MAX_UPLOAD_MB=50
MAX_REQUEST_BODY_MB=250
MAX_FILES_PER_REQUEST=20
```

## Importante

Esto endurece bastante la app, pero no reemplaza una auditoría profesional de seguridad. Para producción real considera:

- HTTPS obligatorio.
- WAF / protección DDoS.
- Backups de base de datos.
- Escaneo antivirus de archivos subidos.
- Autenticación admin con usuarios, hash de contraseña y 2FA.
- Logs centralizados.

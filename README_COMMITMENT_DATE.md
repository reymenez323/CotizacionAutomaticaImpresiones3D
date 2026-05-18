# Fecha compromiso al aceptar

En el panel `/admin`, cuando se presiona **Aceptar**, ahora aparece un modal para introducir:

- fecha compromiso,
- nota interna opcional.

La fecha se guarda en `quote_requests.commitment_date` y también queda registrada en el log de la solicitud.

Si se deja vacía, la solicitud se acepta sin fecha compromiso.

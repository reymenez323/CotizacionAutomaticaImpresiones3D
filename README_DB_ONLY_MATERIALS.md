# Materiales 100% desde base de datos

Esta versión elimina los materiales hardcoded del frontend y backend.

## Qué cambió

- El frontend inicia con `MATERIALS = {}`.
- La página del cliente carga materiales desde `/api/materials`.
- Si no hay materiales activos/disponibles en la base de datos, el cliente no puede cotizar.
- El backend ya no crea materiales iniciales automáticamente.
- El backend ya no usa precios o densidades de respaldo por material.
- Si una cotización usa un material que no existe en la base de datos, el backend rechaza la solicitud.

## Cómo agregar materiales

Entra al panel admin:

```text
/admin
```

Luego ve a:

```text
Materiales y colores
```

Agrega al menos:
- clave,
- nombre,
- precio por kilogramo,
- densidad,
- factor visual,
- colores disponibles.

## Nota para bases de datos existentes

Si ya habías ejecutado una versión anterior, los materiales que fueron sembrados previamente seguirán existiendo en SQLite.
Puedes eliminarlos desde el panel admin o borrar la base de datos para iniciar desde cero.

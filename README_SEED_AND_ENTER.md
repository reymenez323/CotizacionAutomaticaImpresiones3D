# Seed inicial de materiales y envío con Enter

## Seed inicial

Los materiales y colores iniciales están en:

```text
seed_materials.sql
```

Cuando la base de datos está vacía, el backend carga automáticamente ese archivo y crea:

- PLA
- PETG
- ABS
- TPU
- Nylon

con los colores definidos anteriormente.

Si la base de datos ya tiene materiales, el seed no vuelve a ejecutarse para no sobrescribir cambios del admin.

## No hardcoded en la interfaz

El frontend sigue iniciando con `MATERIALS = {}` y carga el catálogo desde `/api/materials`.

## Enviar con Enter

Ahora los formularios principales se pueden enviar con Enter:

- formulario del cliente al solicitar cotización,
- login admin,
- aceptar con fecha compromiso,
- mandar a corrección,
- crear/modificar material,
- subir corrección del cliente.

En el campo de colores del material, Enter/Espacio/coma sigue agregando el color como chip.

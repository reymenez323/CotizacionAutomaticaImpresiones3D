# Fix de procesamiento/previsualización

Problema:
- La política CSP podía bloquear la lectura de modelos porque los loaders usaban URLs `blob:`.
- Esto hacía que el frontend mostrara: "No se pudo cargar o analizar este modelo".

Corrección:
- STL, OBJ y 3MF ahora se leen directamente desde `File.arrayBuffer()` o `File.text()`.
- Ya no dependen de `URL.createObjectURL()`.
- CSP permite `blob:` y `data:` en `connect-src` como respaldo.
- La lista de objetos se actualiza inmediatamente después de procesar cada archivo.
- El slicer solo se llama si existe al menos un objeto válido y analizable.

# Miniaturas isométricas por archivo

Cada archivo cargado genera una miniatura fija y liviana.

Características:
- Imagen pequeña tipo isométrico.
- No tiene controles.
- No se puede rotar ni mover.
- No cambia de color cuando el cliente cambia material/color.
- Se genera una sola vez después de analizar el modelo.
- Sirve para que el cliente identifique visualmente a qué archivo corresponde cada configuración.

La miniatura se guarda en el estado del frontend como `thumbnailDataUrl`.

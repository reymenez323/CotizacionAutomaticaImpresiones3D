# Cotizador 3D con slicing no lineal por cama

Esta versión no multiplica el tiempo por cantidad.

El backend:
1. Recibe todos los modelos y cantidades.
2. Orienta cada modelo.
3. Duplica las piezas.
4. Acomoda las piezas en una o varias camas de 256 x 256 mm.
5. Exporta cada cama como STL combinado.
6. Pasa cada cama completa por PrusaSlicer.
7. Suma el tiempo real y material real del G-code.

## Instalación

```bash
pip install -r requirements.txt
```

Instala PrusaSlicer.

Si PrusaSlicer no está en el PATH, define la ruta:

### Windows PowerShell

```powershell
$env:PRUSASLICER_PATH="C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe"
python -m uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

### Linux/macOS

```bash
export PRUSASLICER_PATH=/usr/bin/prusa-slicer
python -m uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

Abre:

```text
http://127.0.0.1:8000
```

## Perfil recomendado

Para producción real, define un perfil calibrado:

```bash
export PRUSASLICER_PROFILE=/ruta/a/tu/perfil.ini
```

En Windows PowerShell:

```powershell
$env:PRUSASLICER_PROFILE="C:\ruta\perfil.ini"
```

## Nota

El slicing exacto por cama depende de PrusaSlicer instalado en la máquina donde corre el backend.


## Nota para Python 3.14 en Windows

Si usas Python 3.14, no fijes `numpy==2.2.1`, porque puede intentar compilar NumPy desde código fuente y fallar si no tienes compilador C/C++ instalado.

Este paquete usa:

```text
numpy>=2.4.5
```

que permite instalar una versión con wheel compatible para Python 3.14.

Comando recomendado:

```powershell
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

Si todavía falla, usa Python 3.12 en un entorno virtual, que suele ser más estable para librerías científicas/CAD/CAM.


## Corrección de distribución

Esta versión usa validación por rectángulos con margen entre objetos.  
Para cada pieza prueba orientación 0° y 90° sobre la cama, escoge la posición que reduce el área usada y rechaza cualquier colocación que genere intersección.


## Error 503 en `/api/slice-batch`

Si ves algo como:

```text
POST /api/slice-batch HTTP/1.1" 503 Service Unavailable
```

significa que el backend no encontró PrusaSlicer.

### Verificar estado

Con el servidor corriendo, abre:

```text
http://127.0.0.1:8000/api/slicer-status
```

Si dice `ok: false`, debes configurar la ruta del slicer.

### Solución en Windows PowerShell

Verifica si existe esta ruta:

```powershell
Test-Path "C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe"
```

Si devuelve `True`, ejecuta:

```powershell
$env:PRUSASLICER_PATH="C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe"
python -m uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

Luego abre:

```text
http://127.0.0.1:8000
```

### Si no tienes PrusaSlicer instalado

Instálalo y vuelve a correr el servidor.


## Packing MaxRects

Esta versión reemplaza el acomodado por un algoritmo tipo MaxRects:
- Mantiene una lista de rectángulos libres.
- Prueba cada pieza en 0° y 90°.
- Reserva el footprint real más margen.
- Rechaza cualquier intersección.
- Escoge el mejor encaje para reducir espacio desperdiciado.


## Rotación global

Esta versión no decide la rotación solo en el punto actual.  
Ejecuta varios intentos de packing con distintas estrategias:
- prioridad por área,
- prioridad por lado largo,
- prioridad ancho/largo,
- orientación preferida rotada,
- orientación de lado largo en X o Z.

Luego escoge el resultado que usa menos camas y menor área útil.


## Error 400 en `/api/slice-batch`

El error 400 significa que el backend recibió la solicitud, pero rechazó un archivo o parámetro.

En esta versión, la página muestra el motivo exacto debajo de la cotización.

También puedes revisar:

```text
http://127.0.0.1:8000/api/debug-info
```

Causas comunes:
- El archivo no es STL/OBJ/3MF.
- El archivo 3MF/OBJ no pudo convertirse a malla con `trimesh`.
- La pieza excede 256×256×256 mm después de orientarla.
- El modelo tiene geometría corrupta, vacía o no triangular.
- La metadata enviada no coincide con los archivos.

Recomendación práctica:
Si falla con OBJ o 3MF, exporta la pieza como STL binario y vuelve a subirla.

## Corrección SyntaxError anterior

Esta versión corrige un error de indentación en `server.py` que causaba:

```text
SyntaxError: expected 'except' or 'finally' block
```

También `run_windows.bat` se actualizó para correr sin `--reload`, evitando procesos duplicados durante pruebas en Windows.


## Diagnóstico de error 400

Esta versión imprime el error real en PowerShell.

Cuando ocurra:

```text
POST /api/slice-batch HTTP/1.1" 400 Bad Request
```

busca justo arriba o abajo en la consola un bloque como:

```text
[BACKEND ERROR]
Path: /api/slice-batch
Status: 400
Detail: {...}
[/BACKEND ERROR]
```

Copia ese bloque completo para saber exactamente qué archivo o condición está fallando.


## Fix trimesh 4.12+

Si aparece:

```text
'Trimesh' object has no attribute 'remove_duplicate_faces'
```

esta versión ya lo corrige usando funciones compatibles con `trimesh` nuevo:
- `unique_faces()`
- `nondegenerate_faces()`
- `update_faces()`

No necesitas cambiar tu STL por este error.


## Fix: `All objects are outside of the print volume`

Esta versión exporta las camas combinadas en coordenadas positivas `0..256 mm` y también pasa a PrusaSlicer:

```text
--bed-shape 0x0,256x0,256x256,0x256
```

Esto evita que una cama parcial, creada al cambiar parámetros y separar grupos, quede fuera del volumen de impresión de PrusaSlicer.


## Orientación corregida para producción

Esta versión penaliza fuertemente piezas colocadas de canto o verticales.

El score de orientación ahora prioriza:
- menor altura de impresión,
- mayor estabilidad,
- contacto suficiente con cama,
- reducción de soportes y overhang,
- evitar orientaciones altas aunque tengan una cara grande.

Esto corrige casos donde una pieza larga aparecía parada verticalmente.


## Force low orientation

Esta versión aplica una regla dura de producción:
primero encuentra la orientación de menor altura posible y rechaza orientaciones
mucho más altas cuando existe una alternativa baja.

Esto evita piezas largas paradas de canto/verticales aunque tengan gran área lateral.


## Rotación manual XYZ

Cada pieza puede rotarse manualmente en X, Y y Z.

Reglas:
- La rotación se aplica alrededor del centro geométrico de la pieza.
- Después de rotar, la pieza se centra nuevamente para cálculo de cama.
- La pieza se baja automáticamente hasta tocar la cama.
- El backend recibe la misma rotación y la aplica antes de exportar la cama al slicer.


## Rotación con flechas

Los campos de ángulo fueron reemplazados por botones:
- ↶ 90°
- ↷ 90°

Cada eje X, Y y Z rota en pasos de 90°.  
Después de cada clic se actualizan:
- orientación de la pieza,
- bounding box,
- distribución en cama,
- vista previa,
- cotización/slicer.


## Rotación manual removida y orientación automática V2

Se eliminaron los controles de rotación manual.

La orientación automática ahora detecta piezas delgadas como:
- piñones,
- ruedas,
- washers,
- poleas,
- discos.

Si dos dimensiones son grandes y una es claramente menor, fuerza la prueba de orientar la dimensión menor como altura de impresión. Esto evita que los piñones se impriman parados de canto.


## Orientación automática V3

Se ajustó la detección de piezas tipo piñón/disco.

La regla especial de "dimensión menor como altura" ahora solo aplica si:
- la pieza es delgada, y
- las dos dimensiones grandes son parecidas entre sí.

Esto evita que un rack o pieza alargada sea tratada como piñón/disco.


## Orientación por máxima área de contacto

La orientación automática ahora usa como criterio principal maximizar el área real de contacto con la cama.

Criterio:
1. Se prueban orientaciones candidatas.
2. Se calcula el área que realmente queda tocando la cama.
3. Se escoge la orientación con mayor área de contacto.
4. Si hay empate o valores muy cercanos, desempata por menor soporte, menor overhang y menor altura.

Esto prioriza estabilidad y adherencia a la cama.


## Fix material en 0 g

Esta versión corrige casos donde el material aparecía como 0 g.

Cambios:
- El frontend ya no acepta resultados de slicer con `totalFilamentGrams <= 0`.
- El backend lee material desde G-code en gramos, cm3 o mm.
- Si PrusaSlicer no reporta gramos, el backend convierte:
  - cm3 -> gramos usando densidad del material.
  - mm de filamento -> cm3 -> gramos usando diámetro 1.75 mm.
- También se pasan `--filament-diameter` y `--filament-density` a PrusaSlicer.


## Separación por material y costo de seteo

Reglas agregadas:
- Si una pieza usa un material diferente, se coloca en otra cama/lote.
- El backend ya separa también cuando cambia el perfil de impresión.
- Se agrega un costo interno por cama para seteo, nivelación y preparación de máquina.
- El precio al cliente sigue siendo no itemizado.


## Orientación estable al cambiar material

Se ajustó el reacomodo para que cambiar el material no provoque rotaciones innecesarias de cama.

Ahora:
- la orientación base de la pieza se mantiene estable,
- se penaliza rotar 90° dentro de la cama si no hace falta,
- solo se rota en cama cuando ayuda claramente a encajar mejor o reducir lotes,
- frontend y backend usan la misma regla.


## UI lista para producción

Se actualizó la interfaz comercial:
- título y marca visual limpios,
- textos reducidos y orientados a cliente,
- ocultos los detalles internos de material/costo/margen,
- estados técnicos simplificados,
- cotización mostrada como total estimado,
- advertencias técnicas visibles solo cuando son necesarias.

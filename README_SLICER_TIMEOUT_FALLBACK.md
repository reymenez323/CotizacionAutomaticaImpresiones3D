# Fallback de slicer por timeout

Esta versión agrega un fallback automático cuando PrusaSlicer tarda demasiado en generar una cama completa.

## Regla

Si una cama tarda más de:

```text
SLICER_PLATE_TIMEOUT_SECONDS=60
```

el backend:

1. Cancela ese slicing de cama completa.
2. Exporta cada pieza de esa cama por separado.
3. Pasa cada pieza individualmente por PrusaSlicer.
4. Suma el material.
5. Suma los tiempos.
6. Aplica corrección al tiempo:

```text
INDIVIDUAL_FALLBACK_TIME_CORRECTION=1.25
```

Es decir, suma un 25% al tiempo cuando se usa el fallback individual.

## Variables configurables

```text
SLICER_PLATE_TIMEOUT_SECONDS=60
SLICER_INDIVIDUAL_TIMEOUT_SECONDS=60
INDIVIDUAL_FALLBACK_TIME_CORRECTION=1.25
```

## Nota

El material no recibe corrección del 25%; solo el tiempo. El precio sí usa el tiempo corregido para máquina y electricidad.

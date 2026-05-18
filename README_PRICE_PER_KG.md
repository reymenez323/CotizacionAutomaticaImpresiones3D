# Precio por kilogramo

El panel admin ahora muestra y recibe precios como RD$/kg.

Internamente el backend sigue guardando `price_per_gram` para que el cálculo de cotización no se rompa.

Conversión:
- RD$ 2000/kg -> RD$ 2/g
- RD$ 3000/kg -> RD$ 3/g

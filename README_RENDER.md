# PrototiposRD en Render con Docker

Este paquete incluye los archivos necesarios para desplegar el cotizador en Render usando Docker.

## Archivos importantes

- `index.html`: frontend.
- `server.py`: backend FastAPI.
- `requirements.txt`: dependencias Python.
- `Dockerfile`: imagen Docker con Python + PrusaSlicer.
- `render.yaml`: configuración opcional tipo Blueprint para Render.
- `.dockerignore`: evita subir archivos innecesarios al build.

## Prueba local con Docker

```bash
docker build -t prototiposrd-cotizador .
docker run -p 8000:10000 prototiposrd-cotizador
```

Abre:

```text
http://localhost:8000
```

## Render

En Render selecciona:

- New > Web Service
- GitHub repository
- Language: Docker
- Dockerfile path: `./Dockerfile`

La app debe escuchar en `0.0.0.0` y en el puerto que Render pase por `PORT`.
Este Dockerfile ya lo hace.

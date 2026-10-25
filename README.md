# jwalt

Muestra el título de un artículo de jw.org y **todas sus imágenes junto a su texto alternativo** (`alt`): las descripciones
que se escriben para las personas que no ven las imágenes. Pensado para usarlo desde el iPad con la hoja de compartir de
JW Library, pero vale para cualquier enlace.

> Proyecto personal, **sin relación con jw.org ni con sus editores**. No se guardan imágenes: solo se lee la página del
> artículo y se enseñan las imágenes desde sus propias direcciones.

## Cómo funciona

- Pega un enlace de jw.org (o compártelo desde JW Library) y la página lista cada imagen con su texto alternativo.
- Los enlaces `www.jw.org/finder?docid=…&wtlocale=…` (el formato que comparte JW Library) se reescriben a `wol.jw.org`,
  que sirve las direcciones de imagen correctas. Las del CDN antiguo (`akamaihd.net`) se corrigen igual que hace el navegador.
- Solo se muestran las imágenes con `alt` no vacío (jw.org marca así los iconos decorativos).
- Caché en disco: 30 días por artículo, 50 MB como máximo (solo se guarda el JSON, no imágenes).

## API

```
GET /api/extract?url=<enlace>[&format=json|html][&refresh=true]
```

- `format=json` (por defecto): título, imágenes con su `alt`, y `cached`.
- `format=html`: un fragmento HTML sin `<head>`, con estilos en línea y adaptable al ancho, para incrustar en otra página.
- `refresh=true`: ignora la caché y vuelve a descargar.
- `GET /health` → `{"status": "ok"}`. Documentación automática en `/docs`.

## Puesta en marcha

FastAPI + Jinja2 + BeautifulSoup, sin base de datos.

```bash
docker compose up -d --build
```

El `docker-compose.yml` espera una red externa `shared-net` y un volumen `jwalt_cache` ya creados
(`docker network create shared-net`, `docker volume create jwalt_cache`). La app escucha en el puerto 8084.

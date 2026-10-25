import re
from typing import Literal
from urllib.parse import parse_qs, urljoin, urlparse

import diskcache
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(
    title="jwalt",
    description="Dado un enlace a un artículo de jw.org, devuelve el título y cada imagen junto a su texto alt.",
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# El contenido de un artículo apenas cambia y las peticiones tienden a
# repetirse durante la misma semana, así que cacheamos en disco. 50 MB de
# límite es de sobra (solo guardamos JSON de título+alt-text, no imágenes) y
# evita que la caché crezca sin control; 30 días de expiración por entrada.
cache = diskcache.Cache("cache", size_limit=50 * 1024 * 1024)
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; jwalt/1.0; "
        "+https://jwalt.joelgoncalves.es)"
    )
}

# Las imágenes de contenido de artículo se sirven desde varios dominios/rutas
# según la sección de jw.org (wol.jw.org para artículos de estudio,
# jw-cdn.org/akamaihd.net para otros). En vez de una lista de hosts, nos
# apoyamos en que jw.org ya marca los iconos/logos decorativos con alt=""
# de forma consistente, así que basta con exigir alt no vacío.


def _prefer_wol(url: str) -> str:
    """Si es un enlace www.jw.org/finder con wtlocale+docid (el que comparte
    JW Library), lo reescribimos al finder de wol.jw.org: sirve HTML con las
    URLs de imagen ya correctas, sin las referencias rotas que www.jw.org
    corrige por JavaScript en el navegador."""
    parsed = urlparse(url)
    if parsed.netloc != "www.jw.org" or parsed.path != "/finder":
        return url

    params = parse_qs(parsed.query)
    wtlocale = params.get("wtlocale", [None])[0]
    docid = params.get("docid", [None])[0]
    if not wtlocale or not docid:
        return url

    return f"https://wol.jw.org/wol/finder?wtlocale={wtlocale}&docid={docid}"


def _fix_broken_cdn(src: str) -> str:
    """assetsnffrgf-a.akamaihd.net (y variantes) es un CDN legado ya caído;
    jw.org lo sustituye por cms-imgp.jw-cdn.org vía JavaScript en el
    navegador. Replicamos aquí esa reescritura para que las imágenes se
    vean también en páginas que no pasan por /finder (portada, artículos
    normales de www.jw.org, etc.), no solo en wol.jw.org."""
    parsed = urlparse(src)
    if not parsed.netloc.lower().endswith("akamaihd.net"):
        return src
    path = parsed.path.replace("/assets/m/", "/img/p/").replace("/univ/wpub/", "/univ/art/")
    return f"https://cms-imgp.jw-cdn.org{path}"


def _upsize(src: str) -> str:
    """El HTML crudo de jw.org sirve las imágenes de artículo en baja
    resolución (_xs) y jw.org las cambia a un tamaño mayor por JavaScript
    según el ancho de pantalla. Pedimos directamente el tamaño grande."""
    return re.sub(r"_(xs|sm|md)(\.\w+)$", r"_lg\2", src)


class ImageAlt(BaseModel):
    src: str
    alt: str


class ExtractResponse(BaseModel):
    title: str
    source_url: str
    images: list[ImageAlt]
    cached: bool


def _normalize_url(url: str) -> str:
    """Añade https:// si falta y reescribe a wol.jw.org cuando aplica."""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return _prefer_wol(url)


def extract_article_data(url: str) -> dict:
    """Descarga el artículo y devuelve título + imágenes con alt no vacío."""
    url = _normalize_url(url)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"]
    elif soup.title and soup.title.string:
        title = soup.title.string.split("|")[0].strip()
    else:
        title = "Artículo"

    images = []
    seen_srcs = set()
    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").strip()
        src = img.get("src") or ""

        if not alt or not src:
            continue

        src = _upsize(_fix_broken_cdn(urljoin(resp.url, src)))

        if src in seen_srcs:
            continue
        seen_srcs.add(src)

        images.append({"src": src, "alt": alt})

    return {
        "title": title,
        "source_url": resp.url,
        "images": images,
    }


def get_cached_article_data(url: str, refresh: bool = False) -> tuple[dict, bool]:
    """Envuelve extract_article_data con la caché en disco."""
    cache_key = _normalize_url(url)
    if not refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached, True

    data = extract_article_data(url)
    cache.set(cache_key, data, expire=CACHE_TTL_SECONDS)
    return data, False


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/extract", response_model=ExtractResponse)
def api_extract(
    request: Request,
    url: str = Query(..., description="URL de un artículo de jw.org"),
    format: Literal["json", "html"] = Query(
        "json", description="Formato de la respuesta: json (por defecto) o html"
    ),
    refresh: bool = Query(
        False, description="Ignora la caché y vuelve a descargar el artículo"
    ),
):
    error_message = "No se ha podido leer ese enlace. Comprueba que sea correcto."
    try:
        data, cached = get_cached_article_data(url, refresh=refresh)
    except requests.RequestException:
        if format == "html":
            return templates.TemplateResponse(
                "fragment.html",
                {"request": request, "error": error_message},
                status_code=502,
            )
        raise HTTPException(status_code=502, detail=error_message)

    if format == "html":
        return templates.TemplateResponse("fragment.html", {"request": request, **data})
    return {**data, "cached": cached}


@app.get("/health")
def health():
    return {"status": "ok"}
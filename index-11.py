"""
LumosGG / LumosKomik scraper API
Source: https://03.lumosgg.com
Version: 1.0.0
"""

from __future__ import annotations

import base64
import os
import re
from html import unescape
from typing import Any, Optional
from urllib.parse import quote, urljoin

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

APP_VERSION = "1.0.1"
BASE = os.environ.get("LUMOSGG_BASE", "https://03.lumosgg.com").rstrip("/")
TIMEOUT = float(os.environ.get("LUMOSGG_TIMEOUT", "28"))

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": BASE + "/",
    "Cache-Control": "no-cache",
}

app = FastAPI(
    title="LumosGG API",
    description="Unofficial scraper API for 03.lumosgg.com (LumosKomik)",
    version=APP_VERSION,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_CARD_RE = re.compile(
    r'href="/comic/([a-z0-9\-]+)"[^>]*>\s*<img[^>]+src="([^"]+)"[^>]*alt="([^"]*)"',
    re.I,
)
_CHAPTER_RE = re.compile(r'href="(/read/([a-z0-9\-]+)/chapter-(\d+(?:\.\d+)?))"', re.I)
_PAGE_IMG_RE = re.compile(
    r'src="(https://lms\.imgsvr\.my\.id/comic/[^"]+/chapter-[^"]+\.(?:webp|jpg|jpeg|png))"',
    re.I,
)
_GENRE_RE = re.compile(r'href="/browse\?genre=([a-z0-9\-]+)"[^>]*>\s*([^<]+?)\s*<', re.I)
_H1_RE = re.compile(r"<h1[^>]*>([^<]+)</h1>", re.I)
_NATIVE_RE = re.compile(r"<h1[^>]*>[^<]+</h1>\s*<p[^>]*>([^<]+)</p>", re.I)
_DATA_SR_RE = re.compile(r'data-sr="([A-Za-z0-9+/=]+)"')
_STATUS_RE = re.compile(r"\b(Ongoing|Completed|Hiatus)\b", re.I)
_TYPE_RE = re.compile(r"\b(MANHWA|MANHUA|MANGA|COMIC)\b")
_META_DESC_RE = re.compile(
    r'<meta\s+(?:name="description"|property="og:description")\s+content="([^"]+)"',
    re.I,
)
_PAGE_NUM_RE = re.compile(r"[?&]page=(\d+)")


def _clean_text(s: str) -> str:
    s = unescape(s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _abs_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        return url
    return urljoin(BASE + "/", url.lstrip("/"))


async def _get_html(path: str, params: Optional[dict] = None) -> str:
    url = path if path.startswith("http") else BASE + path
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, headers=BROWSER_HEADERS, params=params)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Gagal menghubungi LumosGG: {type(e).__name__}") from e
    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"LumosGG HTTP {r.status_code} untuk {url}")
    return r.text


def _parse_cards(html: str) -> list[dict[str, Any]]:
    seen = set()
    out: list[dict[str, Any]] = []
    for slug, thumb, title in _CARD_RE.findall(html):
        if slug in seen or slug in {"comic", "login", "browse"}:
            continue
        seen.add(slug)
        out.append(
            {
                "judul": _clean_text(title) or slug,
                "title": _clean_text(title) or slug,
                "slug": slug,
                "thumbnail": _abs_url(thumb),
                "sampul": _abs_url(thumb),
                "type": "",
                "source": "lumosgg",
                "url": f"{BASE}/comic/{slug}",
            }
        )
    return out


def _decode_synopsis(html: str) -> str:
    m = _DATA_SR_RE.search(html)
    if m:
        try:
            return _clean_text(base64.b64decode(m.group(1)).decode("utf-8", errors="replace"))
        except Exception:
            pass
    m2 = _META_DESC_RE.search(html)
    if m2:
        return _clean_text(m2.group(1))
    return ""


def _guess_type(html: str) -> str:
    """Ambil tipe dari area header detail (hindari list rekomendasi di sidebar)."""
    h1 = _H1_RE.search(html)
    window = html
    if h1:
        start = max(0, h1.start() - 3500)
        end = min(len(html), h1.end() + 3500)
        window = html[start:end]
    # badge eksplisit di header
    m = re.search(r"\b(MANHWA|MANHUA|MANGA|COMIC)\b", window)
    if m:
        return m.group(1).upper()
    m2 = re.search(r"\b(Manhwa|Manhua|Manga|Comic)\b", window)
    if m2:
        return m2.group(1).upper()
    return "MANHWA"


def _parse_status(html: str) -> str:
    h1 = _H1_RE.search(html)
    window = html
    if h1:
        start = max(0, h1.start() - 3500)
        end = min(len(html), h1.end() + 3500)
        window = html[start:end]
    m = re.search(r"\b(Ongoing|Completed|Hiatus)\b", window, re.I)
    if m:
        return m.group(1).capitalize()
    m2 = _STATUS_RE.search(html)
    return m2.group(1).capitalize() if m2 else ""


def _parse_chapters(html: str, slug: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen = set()
    for path, s, num in _CHAPTER_RE.findall(html):
        if s != slug:
            continue
        key = str(num)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            {
                "judul": f"Chapter {num}",
                "title": f"Chapter {num}",
                "slug": f"chapter-{num}",
                "number": num,
                "id": num,
                "url": _abs_url(path),
            }
        )

    def _num_key(ch: dict) -> float:
        try:
            return float(ch["number"])
        except Exception:
            return 0.0

    # newest first (site order)
    found.sort(key=_num_key, reverse=True)
    return found


def _parse_pages(html: str) -> list[str]:
    pages = []
    seen = set()
    for u in _PAGE_IMG_RE.findall(html):
        u = u.strip()
        if u in seen:
            continue
        # skip tiny icons / logos if any slipped in
        low = u.lower()
        if any(x in low for x in ("logo", "icon", "avatar", "emoji", "banner")):
            continue
        seen.add(u)
        pages.append(u)
    return pages


# ---------- routes ----------


@app.get("/")
async def root():
    return {
        "name": "LumosGG API",
        "version": APP_VERSION,
        "source": BASE,
        "endpoints": {
            "health": "/health",
            "latest": "/api/latest?page=1&sort=latest|popular|rating|az",
            "search": "/api/search?q=",
            "detail": "/api/detail/{slug}",
            "chapter": "/api/chapter?slug=&chapter=",
            "proxy_img": "/api/img?url=",
        },
    }


@app.get("/health")
async def health():
    return {"status": True, "version": APP_VERSION, "base": BASE}


@app.get("/api/latest")
async def api_latest(
    page: int = Query(1, ge=1, le=200),
    sort: str = Query("latest", description="latest | popular | rating | az"),
):
    """
    Daftar komik.
    - sort=latest  -> home-style / project default
    - popular / rating / az -> /project?sort=...
    """
    sort = (sort or "latest").lower().strip()
    if sort in ("popular", "rating", "az"):
        path = "/project"
        params = {"sort": sort, "page": page}
    elif sort in ("latest", "update", "updated", "new"):
        # project default listing acts as main catalog; page supported
        path = "/project"
        params = {"page": page}
    else:
        path = "/project"
        params = {"page": page}

    html = await _get_html(path, params)
    items = _parse_cards(html)
    pages = [int(x) for x in _PAGE_NUM_RE.findall(html)]
    max_page = max(pages) if pages else page
    return {
        "status": True,
        "source": "lumosgg",
        "page": page,
        "sort": sort,
        "max_page_hint": max_page,
        "total": len(items),
        "data": items,
    }


@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1, max_length=120)):
    q = q.strip()
    if not q:
        raise HTTPException(400, "Query kosong")
    html = await _get_html("/browse", {"q": q})
    items = _parse_cards(html)
    return {
        "status": True,
        "source": "lumosgg",
        "query": q,
        "total": len(items),
        "data": items,
    }


@app.get("/api/detail/{slug}")
async def api_detail(slug: str):
    slug = slug.strip().strip("/")
    if not slug or not re.match(r"^[a-z0-9\-]+$", slug):
        raise HTTPException(400, "Slug tidak valid")
    html = await _get_html(f"/comic/{slug}")
    if "Just a moment" in html and len(html) < 8000:
        raise HTTPException(503, "Cloudflare challenge — coba lagi")

    title_m = _H1_RE.search(html)
    judul = _clean_text(title_m.group(1)) if title_m else slug
    native_m = _NATIVE_RE.search(html)
    native = _clean_text(native_m.group(1)) if native_m else ""
    genres = []
    for gslug, gname in _GENRE_RE.findall(html):
        name = _clean_text(gname)
        if name and name not in genres:
            genres.append(name)
    cover = ""
    cm = re.search(
        rf'src="(https://lms\.imgsvr\.my\.id/covers/[^"]+)"[^>]*alt="{re.escape(judul)}"',
        html,
        re.I,
    )
    if not cm:
        cm = re.search(r'src="(https://lms\.imgsvr\.my\.id/covers/[^"]+)"', html, re.I)
    if cm:
        cover = cm.group(1)
    chapters = _parse_chapters(html, slug)
    sinopsis = _decode_synopsis(html)
    return {
        "status": True,
        "source": "lumosgg",
        "data": {
            "judul": judul,
            "title": judul,
            "native": native,
            "slug": slug,
            "thumbnail": cover,
            "sampul": cover,
            "sinopsis": sinopsis,
            "synopsis": sinopsis,
            "type": _guess_type(html),
            "status": _parse_status(html),
            "genres": genres,
            "genre": genres,
            "chapters": chapters,
            "total_chapters": len(chapters),
            "url": f"{BASE}/comic/{slug}",
        },
    }


@app.get("/api/chapter")
async def api_chapter(
    slug: str = Query(..., min_length=1),
    chapter: str = Query(""),
    url: str = Query(""),
):
    slug = (slug or "").strip().strip("/")
    # Saat dipanggil di luar FastAPI, default Query() bisa bukan str
    if not isinstance(chapter, str):
        chapter = ""
    if not isinstance(url, str):
        url = ""
    ch = (chapter or "").strip()
    ch = ch.replace("chapter-", "").replace("Chapter ", "").strip()
    if url and "/read/" in url:
        html = await _get_html(url if url.startswith("http") else url)
    else:
        if not ch:
            raise HTTPException(400, "Parameter chapter wajib diisi")
        if not re.match(r"^\d+(?:\.\d+)?$", ch):
            m = re.search(r"(\d+(?:\.\d+)?)", ch)
            if not m:
                raise HTTPException(400, "Nomor chapter tidak valid")
            ch = m.group(1)
        html = await _get_html(f"/read/{slug}/chapter-{ch}")

    images = _parse_pages(html)
    if not images:
        # fallback broader
        broad = re.findall(r'src="(https://lms\.imgsvr\.my\.id/comic/[^"]+)"', html, re.I)
        images = []
        seen = set()
        for u in broad:
            if "/chapter-" not in u:
                continue
            if u in seen:
                continue
            seen.add(u)
            images.append(u)

    return {
        "status": True,
        "source": "lumosgg",
        "slug": slug,
        "chapter": ch,
        "images": images,
        "gambar": images,
        "pages": images,
        "total": len(images),
        "url": f"{BASE}/read/{slug}/chapter-{ch}" if ch else "",
    }


@app.get("/api/img")
async def api_img(url: str = Query(..., min_length=8)):
    """Proxy gambar CDN Lumos (opsional)."""
    url = url.strip()
    if not url.startswith("http"):
        raise HTTPException(400, "url invalid")
    low = url.lower()
    allow = ("lms.imgsvr.my.id", "imgsvr.my.id", "lumosgg.com", "i.ibb.co")
    if not any(a in low for a in allow):
        raise HTTPException(403, "host tidak diizinkan")
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(
                url,
                headers={
                    **BROWSER_HEADERS,
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "Referer": BASE + "/",
                },
            )
        if r.status_code != 200 or not r.content:
            raise HTTPException(404, "gambar gagal")
        ctype = r.headers.get("content-type") or "image/webp"
        if "image" not in ctype and "octet" not in ctype:
            ctype = "image/webp"
        return Response(
            content=r.content,
            media_type=ctype.split(";")[0].strip(),
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"proxy: {type(e).__name__}: {e}") from e


# Vercel / Mangum
try:
    from mangum import Mangum

    handler = Mangum(app)
except Exception:  # pragma: no cover
    handler = None

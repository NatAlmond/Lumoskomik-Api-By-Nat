# LumosGG API (unofficial)

Scraper API untuk [03.lumosgg.com](https://03.lumosgg.com) (LumosKomik).

## Endpoints

| Method | Path | Keterangan |
|--------|------|------------|
| GET | `/health` | Status + versi |
| GET | `/api/latest?page=1&sort=latest\|popular\|rating\|az` | Daftar komik |
| GET | `/api/search?q=` | Cari judul |
| GET | `/api/detail/{slug}` | Detail + sinopsis + chapter |
| GET | `/api/chapter?slug=&chapter=` | Gambar halaman chapter |
| GET | `/api/img?url=` | Proxy gambar CDN (opsional) |

## Contoh

```bash
curl "https://YOUR_HOST/api/latest?page=1&sort=popular"
curl "https://YOUR_HOST/api/search?q=solo"
curl "https://YOUR_HOST/api/detail/bad-born-blood"
curl "https://YOUR_HOST/api/chapter?slug=bad-born-blood&chapter=1"
```

## Env (opsional)

- `LUMOSGG_BASE` — default `https://03.lumosgg.com`
- `LUMOSGG_TIMEOUT` — detik, default `28`

## Deploy Vercel

Root project ini, framework Other / Python. `vercel.json` sudah mengarah ke `index.py`.

## Entry point

Vercel memakai `index.py` (bukan `main.py`). `main.py` hanya re-export agar import lokal tetap aman.

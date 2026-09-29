# Specter Intel — Social Media Intelligence (MVP v1.0)

Dashboard web untuk mencari akun media sosial berdasarkan username melalui **EnsembleData API**.
Browser hanya mengirim username; backend Python yang menyimpan API key, memanggil EnsembleData,
menormalisasi data, dan mengembalikan JSON yang aman ke frontend.

```
Browser (HTML/CSS/Vanilla JS) ──username──▶ FastAPI ──HTTPS + token──▶ EnsembleData
                                  ◀──normalized JSON──
```

## Stack

| Layer    | Teknologi |
| -------- | --------- |
| Backend  | Python 3.11+, FastAPI, Uvicorn, httpx, Pydantic, python-dotenv |
| Frontend | HTML5 + CSS3 + Vanilla JavaScript (tanpa build step, disajikan oleh FastAPI) |
| Database | SQLite (riwayat pencarian & snapshot metrik akun) |
| Deploy   | Docker / docker-compose |

## Fitur

- **Pencarian username** untuk X/Twitter, Instagram, TikTok, atau **All Platforms** (paralel, multi-hasil).
- **Profile card** berisi avatar, nama, verifikasi, bio, followers/following/posts, tanggal pembuatan akun, dan payload JSON yang sudah dinormalisasi.
- **Open Profile**, **Export JSON**, dan **Copy URL**.
- **30-Day Follower Signal**: grafik yang dibuat dari snapshot yang *benar-benar* diamati aplikasi setiap kali akun dicari (tidak ada data rekaan).
- **Recent Inquiries**, modal **Search History** (bisa di-klik untuk menjalankan ulang), dan **Clear Log**.
- **KPI**: jumlah inquiry hari ini, sisa quota unit EnsembleData, rata-rata respon, dan status provider.
- **System Health**: pemakaian rate limit per IP secara real-time.
- **Loading state**, **error state**, dan **not-found state** sesuai SRS.
- **Demo mode**: tanpa API key, aplikasi memakai data sintetis yang diberi label jelas (`DEMO DATA`) supaya UI bisa dicoba tanpa memakai unit.

## Menjalankan secara lokal

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # isi ENSEMBLEDATA_API_KEY untuk live mode
uvicorn app.main:app --reload --port 8000
```

Buka http://localhost:8000. Dokumentasi API interaktif tersedia di http://localhost:8000/docs.

### Docker

```bash
cp backend/.env.example backend/.env   # isi API key
docker compose up --build
```

## Konfigurasi (`backend/.env`)

| Variabel | Default | Keterangan |
| --- | --- | --- |
| `ENSEMBLEDATA_API_KEY` | – | Token EnsembleData. **Jangan di-commit.** |
| `ENSEMBLEDATA_BASE_URL` | `https://ensembledata.com/apis` | Base URL API |
| `ENSEMBLEDATA_DAILY_UNITS` | `1000` | Jatah unit harian paket Anda (untuk KPI "Quota Remaining") |
| `PROVIDER_MODE` | `auto` | `auto` (live jika key ada), `live`, atau `mock` |
| `REQUEST_TIMEOUT` | `15` | Timeout ke provider (maks. 15 detik) |
| `REQUEST_RETRIES` | `1` | Retry untuk timeout/5xx |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | `10` / `60` | Rate limit `/api/search` per IP |
| `TRUST_PROXY_HEADERS` | `false` | Set `true` hanya di belakang reverse proxy milik Anda |
| `CORS_ORIGINS` | `http://localhost:8000,...` | Origin yang diizinkan |
| `DATABASE_PATH` | `data/intel.db` | Lokasi SQLite |

> **Endpoint EnsembleData** yang dipakai ada di `backend/app/services/ensembledata.py`
> (`/twitter/user/info`, `/tt/user/info`, `/instagram/user/info`, `/customer/get-used-units`).
> Cocokkan dengan dokumentasi paket EnsembleData Anda sebelum produksi. Mapping field ada di
> `backend/app/services/normalizer.py`.

## API

| Method | Path | Keterangan |
| --- | --- | --- |
| GET | `/health` | `{"status": "ok"}` |
| GET | `/api/search?username=<u>&platform=twitter\|instagram\|tiktok\|all` | Pencarian akun |
| GET | `/api/accounts/{platform}/{username}/trend?days=30` | Snapshot metrik akun |
| GET / DELETE | `/api/history` | Riwayat pencarian / hapus riwayat |
| GET | `/api/system/status` | KPI, status provider, rate limit (tanpa secret) |
| GET | `/api/avatar?url=` | Proxy avatar, hanya untuk host CDN platform yang di-allowlist |

Contoh response sukses:

```json
{
  "success": true,
  "query": "example",
  "platform": "twitter",
  "results": [{ "platform": "twitter", "username": "example", "display_name": "...", "followers": 1234, "...": "..." }],
  "warnings": [],
  "meta": { "provider": "EnsembleData", "mode": "live", "latency_ms": 812, "searched_at": "..." }
}
```

Mapping error (SRS §17):

| Kondisi | HTTP | `error.code` |
| --- | --- | --- |
| Username kosong / invalid | 400 | `USERNAME_REQUIRED` / `INVALID_USERNAME` |
| Rate limit aplikasi | 429 | `RATE_LIMITED` (+ header `Retry-After`) |
| Quota / rate limit provider | 429 | `PROVIDER_RATE_LIMITED` |
| API key ditolak | 502 | `PROVIDER_UNAUTHORIZED` |
| Provider error / 5xx / response rusak | 502 | `PROVIDER_ERROR` / `PROVIDER_UNAVAILABLE` / `PROVIDER_MALFORMED_RESPONSE` |
| Timeout provider | 504 | `PROVIDER_TIMEOUT` |
| Tidak ditemukan | 200 | `results: []` |
| Server error | 500 | `INTERNAL_ERROR` |

## Keamanan

- API key hanya dibaca dari environment di server. Key tidak pernah dikirim ke frontend, disimpan di localStorage, dimasukkan ke response JSON, atau ditulis ke log (ada filter redaksi, dan log request `httpx` dimatikan).
- Username divalidasi di frontend dan backend (`^[A-Za-z0-9._-]{1,30}$`).
- Rate limit sliding-window per IP, timeout 15 detik, dan retry terbatas.
- Header keamanan: CSP ketat (`script-src 'self'`), `X-Frame-Options`, `nosniff`, dan `Referrer-Policy`.
- Data dari provider dirender lewat `textContent` (tanpa `innerHTML`) untuk mencegah XSS.
- Proxy avatar hanya menerima HTTPS ke CDN platform yang di-allowlist, tanpa mengikuti redirect, dengan batas ukuran 3 MB.

## Testing

```bash
pip install -r backend/requirements-dev.txt
pytest
```

Test menggunakan `httpx.MockTransport` (tanpa memanggil jaringan) dan mencakup: username valid/kosong/invalid, akun tidak ditemukan, timeout, 401, 429/495, 5xx dengan retry, response rusak, multi-hasil, rate limit, riwayat, demo mode, allowlist avatar, header keamanan, dan pengecekan bahwa API key tidak bocor.

## Struktur

```
backend/app/
  main.py                 # app factory, middleware, error handler, static frontend
  api/                    # search.py, history.py, system.py, deps.py
  services/               # ensembledata.py, normalizer.py, search_service.py, history.py, rate_limiter.py
  schemas/search.py       # model Pydantic
  core/                   # config.py, errors.py
  utils/                  # logger.py, validation.py
frontend/                 # index.html, style.css, app.js
tests/                    # test_search.py, test_ensembledata.py
```

## Catatan untuk produksi

- Rate limiter dan cache quota bersifat in-memory (satu proses). Untuk banyak instance, pindahkan ke store bersama seperti Redis.
- Untuk PostgreSQL, ganti `HistoryRepository` dengan implementasi yang memakai skema yang sama.
- Jalankan di belakang Nginx dengan TLS, lalu set `TRUST_PROXY_HEADERS=true` dan `CORS_ORIGINS` ke domain Anda.
- Gunakan hanya data yang boleh diakses sesuai ketentuan EnsembleData dan platform terkait.

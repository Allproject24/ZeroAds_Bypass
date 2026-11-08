# ZeroAds Gabungan

## Peta folder

- `api/index.py` — routing API, penyajian file lokal, dan entry point Flask.
- `zeroads/` — resolver ZeroAds serta penanganan link dan file Sfile.
- `public/` — halaman, CSS, JavaScript, font, dan ikon statis.
- `vercel.json` — routing dan konfigurasi deploy Vercel.

## Jalan lokal

Pasang Python 3.9 atau lebih baru dan dependensi:

```sh
pip install -r requirements.txt
python api/index.py
```

Buka `http://localhost:5000`. Port dapat diubah melalui variabel `PORT`.

## Deploy ke Vercel

Impor folder `zeroads-gabungan` sebagai root project di Vercel, lalu deploy. Vercel memakai `api/index.py` untuk `/api/*` dan file statis dari `public/` untuk halaman lainnya.

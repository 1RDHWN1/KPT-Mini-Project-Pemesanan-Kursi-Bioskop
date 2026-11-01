# Bioskop Kita — Reservasi Kursi dengan gRPC

Mini project RPC untuk satu studio dan satu jadwal film. Web menampilkan 50 kursi (baris A–E); perubahan kursi dikirim real-time melalui server-streaming gRPC dan SSE.

## Arsitektur

```text
Browser (HTML/CSS/JS) -- HTTP + SSE --> FastAPI Gateway -- gRPC --> Python gRPC Server
```

Browser memakai HTTP karena browser biasa tidak mendukung gRPC native. Gateway menerjemahkan permintaan web menjadi RPC. Untuk status langsung, gateway berlangganan `PantauKursi` (server streaming) lalu meneruskan pembaruannya ke browser melalui SSE.

## RPC

| RPC | Pola | Fungsi |
|---|---|---|
| `LihatKursi` | Unary | Mengambil status seluruh kursi. |
| `PesanKursi` | Unary | Memesan satu kursi dengan `request_id` idempoten. |
| `BatalkanPesanan` | Unary | Membatalkan pesanan menggunakan `booking_id`. |
| `PantauKursi` | Server streaming | Mengirim snapshot awal dan snapshot baru saat status berubah. |

Semua akses ke kursi dan data pesanan dilindungi `threading.Condition` (yang juga menyediakan lock). Pengecekan kursi tersedia dan perubahan status terjadi di dalam critical section yang sama. Retry gateway menggunakan ID permintaan yang sama. Hasil operasi disimpan dalam memori untuk deduplikasi.

## Menjalankan dengan Docker

```bash
docker compose up --build
```

Buka `http://localhost:8000`. Untuk demo dua komputer dalam jaringan yang sama, jalankan compose di komputer server lalu buka `http://IP-KOMPUTER-SERVER:8000` dari komputer client. Pastikan firewall mengizinkan port 8000.

## Menjalankan lokal tanpa Docker

Gunakan Python 3.10 atau lebih baru:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate
pip install -r requirements.txt
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. proto/bioskop.proto
```

Jalankan server dan gateway pada dua terminal:

```bash
python server.py
```

```bash
uvicorn gateway:app --host 0.0.0.0 --port 8000
```

Lalu buka `http://localhost:8000`.

## Skenario demo

1. Buka halaman dari dua browser/perangkat.
2. Pilih kursi yang sama dan pesan hampir bersamaan. Hanya satu permintaan yang akan berhasil.
3. Tunjukkan status kursi berubah langsung di browser lainnya.
4. Batalkan pesanan dari panel “Pesanan saya”; kursi kembali tersedia.
5. Untuk pengukuran tugas, jalankan beban 1, 5, dan 20 client. Catat waktu, latensi rata-rata, throughput, lalu bandingkan hasilnya.

## Catatan batasan prototipe

Status dan deduplikasi disimpan di memori. Restart server akan menghapus pesanan dan riwayat request ID. Ini cukup untuk demo concurrency satu server; persistensi database dan deduplikasi lintas restart dapat ditambahkan sebagai pengembangan lanjutan.

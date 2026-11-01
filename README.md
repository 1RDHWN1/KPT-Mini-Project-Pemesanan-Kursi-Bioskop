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

## Menjalankan di Windows tanpa Docker

Pakai cara ini kalau perintah `docker` tidak dikenali. Semua perintah di bawah dijalankan dari PowerShell di folder proyek (`D:\KPT Mini Project BIoskop`).

### 1. Pastikan Python tersedia

```powershell
python --version
```

Proyek memerlukan Python 3.10 atau lebih baru. Kalau `python` tidak dikenali, pasang Python dari [halaman resmi Python untuk Windows](https://www.python.org/downloads/windows/). Saat memasang Python, centang **Add python.exe to PATH**, lalu tutup dan buka PowerShell lagi. Setelah itu ulangi `python --version`. Perintah `py` juga bisa dipakai jika Python Launcher terpasang, tetapi langkah berikut menggunakan `python`.

### 2. Buat environment dan pasang dependensi

Jalankan sekali dari folder proyek:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. proto/bioskop.proto
```

Tunggu setiap perintah selesai tanpa error sebelum menjalankan perintah berikutnya. Langkah `protoc` membuat file stub Python dari `proto/bioskop.proto`.

### 3. Jalankan server dan web gateway

Buka **dua jendela PowerShell** di folder proyek yang sama. Biarkan keduanya tetap terbuka saat aplikasi digunakan.

Di terminal pertama, jalankan server gRPC:

```powershell
.\.venv\Scripts\python.exe server.py
```

Terminal ini seharusnya menampilkan:

```text
Server gRPC berjalan di 0.0.0.0:50051
```

Di terminal kedua, jalankan gateway web:

```powershell
.\.venv\Scripts\python.exe -m uvicorn gateway:app --host 0.0.0.0 --port 8000
```

Terminal ini seharusnya menampilkan bahwa Uvicorn berjalan pada port 8000. Buka **http://localhost:8000** di browser (gunakan `http`, bukan `https`). Untuk menghentikan masing-masing proses, tekan `Ctrl+C` di terminalnya.

### Jika halaman gagal dibuka

- Pastikan kedua terminal masih berjalan dan tidak menampilkan traceback/error.
- Pastikan URL-nya `http://localhost:8000`.
- Jika `python` atau `.venv\Scripts\python.exe` tidak dikenali, kembali ke langkah 1 dan 2; environment `.venv` baru terbentuk jika `python -m venv .venv` berhasil.
- Jika instalasi dependensi atau pembuatan stub gagal, selesaikan error tersebut dulu sebelum menjalankan server.
- Saat minta bantuan, salin error dari terminal gateway dan server. Pesan browser saja biasanya belum menunjukkan proses mana yang gagal.

## Menjalankan lokal tanpa Docker (Linux/macOS)

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

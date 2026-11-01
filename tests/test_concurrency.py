"""Pengujian Concurrency dan Race Condition untuk Sistem Reservasi Kursi Bioskop."""

import random
import threading
import time
from concurrent import futures

from proto import bioskop_pb2 as pb


def test_perebutan_satu_kursi_20_client(grpc_test_server):
    """Kasus 1: 20 client secara simultan memperebutkan satu kursi yang sama (C5).
    
    Assertion: Tepat 1 client sukses, 19 client lainnya gagal dengan pesan 'Kursi sudah dipesan'.
    Verifikasi status kursi C5 tidak tersedia dan pesanan tercatat tepat 1 tiket.
    """
    stub = grpc_test_server["stub"]
    servicer = grpc_test_server["servicer"]
    num_clients = 20
    barrier = threading.Barrier(num_clients)
    kursi_target = "C5"

    def client_worker(client_id):
        # Barrier memastikan seluruh 20 thread menembak RPC pada momen yang sama
        barrier.wait()
        req = pb.PesanKursiRequest(
            request_id=f"req-c5-{client_id}",
            kursi_id=kursi_target,
            nama_pemesan=f"Client-{client_id}",
        )
        return stub.PesanKursi(req)

    with futures.ThreadPoolExecutor(max_workers=num_clients) as executor:
        results = list(executor.map(client_worker, range(num_clients)))

    sukses_list = [r for r in results if r.sukses]
    gagal_list = [r for r in results if not r.sukses]

    assert len(sukses_list) == 1, f"Harus tepat 1 pemesan sukses, tetapi didapat: {len(sukses_list)}"
    assert len(gagal_list) == num_clients - 1, f"Harus {num_clients - 1} pemesan gagal, didapat: {len(gagal_list)}"

    pemenang = sukses_list[0]
    assert pemenang.kursi_id == kursi_target
    assert len(pemenang.booking_id) > 0
    assert f"Kursi {kursi_target} berhasil dipesan" in pemenang.pesan

    for r in gagal_list:
        assert r.pesan == "Kursi sudah dipesan"
        assert r.kursi_id == kursi_target
        assert r.booking_id == ""

    # Verifikasi status kursi via RPC LihatKursi
    daftar_kursi = stub.LihatKursi(pb.LihatKursiRequest()).kursi
    kursi_c5 = next(k for k in daftar_kursi if k.id == kursi_target)
    assert kursi_c5.tersedia is False

    # Verifikasi konsistensi state internal servicer
    with servicer.kondisi:
        assert servicer.kursi[kursi_target]["tersedia"] is False
        pesanan_c5 = [p for b_id, p in servicer.pesanan.items() if p["kursi_id"] == kursi_target]
        assert len(pesanan_c5) == 1
        assert pemenang.booking_id in servicer.pesanan


def test_batch_booking_atomik_contention(grpc_test_server):
    """Kasus 2: Transaksi batch booking dengan contention (overlap).
    
    Thread A memesan ['B1', 'B2'], Thread B memesan ['B2', 'B3'] bersamaan.
    Assertion: Tepat 1 transaksi sukses penuh. Transaksi yang kalah gagal total (all-or-nothing).
    Tidak boleh terjadi partial booking di mana B3 atau B1 terpesan saat B2 gagal.
    """
    stub = grpc_test_server["stub"]
    servicer = grpc_test_server["servicer"]
    barrier = threading.Barrier(2)

    def pesan_batch(req_id, kursi_ids, nama):
        barrier.wait()
        req = pb.PesanBeberapaKursiRequest(
            request_id=req_id,
            kursi_id=kursi_ids,
            nama_pemesan=nama,
        )
        return stub.PesanBeberapaKursi(req)

    with futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut_a = executor.submit(pesan_batch, "req-batch-A", ["B1", "B2"], "Thread-A")
        fut_b = executor.submit(pesan_batch, "req-batch-B", ["B2", "B3"], "Thread-B")
        res_a = fut_a.result()
        res_b = fut_b.result()

    assert (res_a.sukses and not res_b.sukses) or (res_b.sukses and not res_a.sukses), (
        f"Hanya satu transaksi batch yang boleh sukses. res_a: {res_a.sukses}, res_b: {res_b.sukses}"
    )

    daftar_kursi = {k.id: k.tersedia for k in stub.LihatKursi(pb.LihatKursiRequest()).kursi}

    if res_a.sukses:
        # Thread A menang: B1 & B2 terpesan, B3 HARUS tetap tersedia (bebas dari partial booking)
        assert daftar_kursi["B1"] is False, "B1 harus terpesan oleh Thread A"
        assert daftar_kursi["B2"] is False, "B2 harus terpesan oleh Thread A"
        assert daftar_kursi["B3"] is True, "B3 HARUS tetap tersedia, partial booking dilarang"
        assert "Kursi sudah dipesan: B2" in res_b.pesan
        assert len(res_b.pesanan) == 0
        assert len(res_a.pesanan) == 2
    else:
        # Thread B menang: B2 & B3 terpesan, B1 HARUS tetap tersedia (bebas dari partial booking)
        assert daftar_kursi["B1"] is True, "B1 HARUS tetap tersedia, partial booking dilarang"
        assert daftar_kursi["B2"] is False, "B2 harus terpesan oleh Thread B"
        assert daftar_kursi["B3"] is False, "B3 harus terpesan oleh Thread B"
        assert "Kursi sudah dipesan: B2" in res_a.pesan
        assert len(res_a.pesanan) == 0
        assert len(res_b.pesanan) == 2


def test_pesan_dan_batal_simultan(grpc_test_server):
    """Kasus 3: Simulasi rapid concurrent booking & cancellation simultan.
    
    Memastikan threading.Condition dan critical section mencegah deadlock
    dan menjaga konsistensi state tanpa data corruption.
    """
    stub = grpc_test_server["stub"]
    servicer = grpc_test_server["servicer"]

    kursi_pool = [f"D{i}" for i in range(1, 11)]
    num_threads = 16
    operations_per_thread = 20
    barrier = threading.Barrier(num_threads)

    active_bookings_lock = threading.Lock()
    active_bookings = []  # list of (booking_id, kursi_id)

    def worker_simultan(worker_id):
        barrier.wait()
        for op_idx in range(operations_per_thread):
            action = random.choice(["pesan", "batal"])
            req_id = f"simul-{worker_id}-{op_idx}-{random.randint(1000, 9999)}"

            if action == "pesan":
                target_kursi = random.choice(kursi_pool)
                req = pb.PesanKursiRequest(
                    request_id=req_id,
                    kursi_id=target_kursi,
                    nama_pemesan=f"User-{worker_id}",
                )
                res = stub.PesanKursi(req)
                if res.sukses:
                    with active_bookings_lock:
                        active_bookings.append((res.booking_id, res.kursi_id))
            else:
                target_booking = None
                with active_bookings_lock:
                    if active_bookings:
                        target_booking = active_bookings.pop(0)

                if target_booking:
                    b_id, _ = target_booking
                    batal_req = pb.BatalkanPesananRequest(
                        request_id=req_id,
                        booking_id=b_id,
                    )
                    res = stub.BatalkanPesanan(batal_req)
                    # Jika pembatalan gagal karena race condition/sudah dibatalkan, itu valid

    with futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futs = [executor.submit(worker_simultan, i) for i in range(num_threads)]
        for fut in futures.as_completed(futs):
            fut.result()  # Pastikan tidak ada exception/deadlock

    # Verifikasi konsistensi akhir
    resp_kursi = stub.LihatKursi(pb.LihatKursiRequest())
    kursi_map = {k.id: k.tersedia for k in resp_kursi.kursi}

    with servicer.kondisi:
        # Jumlah kursi yang tidak tersedia harus sama persis dengan jumlah tiket aktif di servicer.pesanan
        jumlah_kursi_terisi = sum(1 for k in resp_kursi.kursi if not k.tersedia)
        assert len(servicer.pesanan) == jumlah_kursi_terisi, (
            f"Jumlah pesanan aktif ({len(servicer.pesanan)}) tidak cocok dengan kursi terisi ({jumlah_kursi_terisi})"
        )

        for b_id, pesanan_data in servicer.pesanan.items():
            k_id = pesanan_data["kursi_id"]
            assert kursi_map[k_id] is False, f"Kursi {k_id} ada di pesanan aktif tapi berstatus tersedia"
            assert servicer.kursi[k_id]["tersedia"] is False

    # Pastikan server tetap dapat melayani permintaan baru secara normal (di luar with servicer.kondisi)
    test_req = pb.PesanKursiRequest(
        request_id="post-simultan-check",
        kursi_id="E1",
        nama_pemesan="FinalVerification",
    )
    res_final = stub.PesanKursi(test_req)
    assert res_final.sukses is True
    assert res_final.kursi_id == "E1"

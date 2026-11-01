"""Pengujian Toleransi Kegagalan, Idempotensi, dan Semantik At-Most-Once."""

from unittest.mock import MagicMock, patch
import grpc
import pytest

from gateway import panggil_dengan_retry
from proto import bioskop_pb2 as pb


def test_deduplikasi_pesan_kursi_idempotent(grpc_test_server):
    """Kasus 1: Permintaan PesanKursi dengan request_id yang sama persis sebanyak 5 kali.
    
    Assertion: Kelima pemanggilan mengembalikan HasilPesanResponse yang identik
    (booking_id sama persis), dan kursi tetap hanya terpesan satu kali di server.
    """
    stub = grpc_test_server["stub"]
    servicer = grpc_test_server["servicer"]
    request_id = "idem-kursi-single-001"
    kursi_id = "A1"

    req = pb.PesanKursiRequest(
        request_id=request_id,
        kursi_id=kursi_id,
        nama_pemesan="Budi Santoso",
    )

    responses = [stub.PesanKursi(req) for _ in range(5)]

    pertama = responses[0]
    assert pertama.sukses is True
    assert pertama.kursi_id == kursi_id
    assert len(pertama.booking_id) > 0

    # Pastikan kelima respons identik
    for idx, resp in enumerate(responses[1:], start=2):
        assert resp.sukses is True, f"Panggilan ke-{idx} harus sukses"
        assert resp.booking_id == pertama.booking_id, f"Panggilan ke-{idx} booking_id berbeda"
        assert resp.pesan == pertama.pesan, f"Panggilan ke-{idx} pesan berbeda"
        assert resp.kursi_id == pertama.kursi_id, f"Panggilan ke-{idx} kursi_id berbeda"

    # Verifikasi kursi hanya tercatat 1 kali di storage/pesanan
    with servicer.kondisi:
        pesanan_a1 = [p for p in servicer.pesanan.values() if p["kursi_id"] == kursi_id]
        assert len(pesanan_a1) == 1, f"Harus tepat 1 pesanan di server, ditemukan: {len(pesanan_a1)}"
        assert ("pesan", request_id) in servicer.hasil_permintaan


def test_deduplikasi_pesan_batch_idempotent(grpc_test_server):
    """Kasus 2: Permintaan PesanBeberapaKursi berulang dengan request_id sama.
    
    Assertion: Mengembalikan HasilPesanBanyakResponse yang identik,
    daftar pesanan konsisten, dan tidak ada duplikasi data kursi di server.
    """
    stub = grpc_test_server["stub"]
    servicer = grpc_test_server["servicer"]
    request_id = "idem-batch-002"
    kursi_target = ["A2", "A3"]

    req = pb.PesanBeberapaKursiRequest(
        request_id=request_id,
        kursi_id=kursi_target,
        nama_pemesan="Citra Lestari",
    )

    responses = [stub.PesanBeberapaKursi(req) for _ in range(5)]

    pertama = responses[0]
    assert pertama.sukses is True
    assert len(pertama.pesanan) == 2
    tiket_pertama = [(p.booking_id, p.kursi_id) for p in pertama.pesanan]

    for idx, resp in enumerate(responses[1:], start=2):
        assert resp.sukses is True
        assert resp.pesan == pertama.pesan
        tiket_sekarang = [(p.booking_id, p.kursi_id) for p in resp.pesanan]
        assert tiket_sekarang == tiket_pertama, f"Panggilan ke-{idx} menghasilkan tiket berbeda"

    # Verifikasi server hanya memesan 2 kursi secara total untuk kedua id ini
    with servicer.kondisi:
        for k_id in kursi_target:
            assert servicer.kursi[k_id]["tersedia"] is False
            pesanan_k = [p for p in servicer.pesanan.values() if p["kursi_id"] == k_id]
            assert len(pesanan_k) == 1
        assert ("pesan_banyak", request_id) in servicer.hasil_permintaan


def test_deduplikasi_batalkan_pesanan_idempotent(grpc_test_server):
    """Kasus 3: Permintaan BatalkanPesanan berulang dengan request_id sama.
    
    Assertion: Respons pembatalan identik, kursi kembali tersedia,
    dan tidak terjadi error saat dipanggil berulang kali.
    """
    stub = grpc_test_server["stub"]
    servicer = grpc_test_server["servicer"]

    # Buat pesanan terlebih dahulu
    pesan_res = stub.PesanKursi(
        pb.PesanKursiRequest(
            request_id="prep-cancel-003",
            kursi_id="A4",
            nama_pemesan="Dewi Anggraeni",
        )
    )
    assert pesan_res.sukses is True
    booking_id = pesan_res.booking_id

    # Batalkan pesanan dengan request_id yang sama sebanyak 5 kali
    batal_req_id = "idem-batal-003"
    batal_req = pb.BatalkanPesananRequest(
        request_id=batal_req_id,
        booking_id=booking_id,
    )

    responses = [stub.BatalkanPesanan(batal_req) for _ in range(5)]

    pertama = responses[0]
    assert pertama.sukses is True
    assert pertama.kursi_id == "A4"
    assert "dibatalkan" in pertama.pesan

    for idx, resp in enumerate(responses[1:], start=2):
        assert resp.sukses is True
        assert resp.pesan == pertama.pesan
        assert resp.kursi_id == pertama.kursi_id

    # Verifikasi kursi sudah kembali tersedia
    daftar_kursi = {k.id: k.tersedia for k in stub.LihatKursi(pb.LihatKursiRequest()).kursi}
    assert daftar_kursi["A4"] is True
    with servicer.kondisi:
        assert booking_id not in servicer.pesanan
        assert ("batal", batal_req_id) in servicer.hasil_permintaan


def test_retry_exponential_backoff_handling():
    """Kasus 4: Pengujian fungsi panggil_dengan_retry untuk transient failure dan backoff delay."""
    dummy_request = pb.LihatKursiRequest()
    expected_response = pb.DaftarKursiResponse(versi=42)

    class MockRpcError(grpc.RpcError):
        def __init__(self, code, details="Mock gRPC error"):
            self._code = code
            self._details = details

        def code(self):
            return self._code

        def details(self):
            return self._details

    # Skenario A: Gagal sementara (UNAVAILABLE) lalu sukses pada percobaan kedua
    mock_method = MagicMock(
        side_effect=[
            MockRpcError(grpc.StatusCode.UNAVAILABLE),
            expected_response,
        ]
    )

    with patch("time.sleep") as mock_sleep:
        hasil = panggil_dengan_retry(mock_method, dummy_request, timeout=2.0, attempts=3)
        assert hasil == expected_response
        assert mock_method.call_count == 2
        # Backoff percobaan pertama: 0.25 * (2**0) = 0.25 detik
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(0.25)

    # Skenario B: Gagal terus-menerus (DEADLINE_EXCEEDED) hingga melewati batas attempts
    mock_method_fail = MagicMock(
        side_effect=MockRpcError(grpc.StatusCode.DEADLINE_EXCEEDED)
    )

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(grpc.RpcError) as exc_info:
            panggil_dengan_retry(mock_method_fail, dummy_request, timeout=1.0, attempts=3)
        assert exc_info.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
        assert mock_method_fail.call_count == 3
        # Backoff terpanggil 2 kali (attempt 0 dan 1): 0.25 dan 0.50 detik
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0][0][0] == 0.25
        assert mock_sleep.call_args_list[1][0][0] == 0.50

    # Skenario C: Non-retryable error (misal INVALID_ARGUMENT), tidak boleh ada retry
    mock_method_non_retry = MagicMock(
        side_effect=MockRpcError(grpc.StatusCode.INVALID_ARGUMENT)
    )

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(grpc.RpcError) as exc_info:
            panggil_dengan_retry(mock_method_non_retry, dummy_request, timeout=2.0, attempts=3)
        assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        assert mock_method_non_retry.call_count == 1
        assert mock_sleep.call_count == 0

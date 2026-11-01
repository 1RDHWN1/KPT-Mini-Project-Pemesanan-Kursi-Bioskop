"""gRPC server for the single-screen cinema seat reservation demo."""

from concurrent import futures
import secrets
import threading

import grpc

from proto import bioskop_pb2 as pb
from proto import bioskop_pb2_grpc as rpc


def buat_kursi():
    return {
        f"{baris}{nomor}": {
            "id": f"{baris}{nomor}",
            "baris": baris,
            "nomor": nomor,
            "tersedia": True,
        }
        for baris in "ABCDE"
        for nomor in range(1, 11)
    }


class LayananBioskop(rpc.LayananBioskopServicer):
    def __init__(self):
        self.kursi = buat_kursi()
        self.pesanan = {}  # booking_id -> {kursi_id, nama_pemesan}
        self.hasil_permintaan = {}  # (operasi, request_id) -> response
        self.versi = 1
        self.kondisi = threading.Condition()

    def _kursi_pb(self):
        return [pb.Kursi(**data) for data in self.kursi.values()]

    def _snapshot(self):
        return pb.PembaruanKursi(kursi=self._kursi_pb(), versi=self.versi)

    def LihatKursi(self, request, context):
        with self.kondisi:
            return pb.DaftarKursiResponse(kursi=self._kursi_pb(), versi=self.versi)

    def PesanKursi(self, request, context):
        if not request.request_id.strip() or not request.kursi_id.strip():
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "request_id dan kursi_id wajib diisi")
        key = ("pesan", request.request_id)
        with self.kondisi:
            if key in self.hasil_permintaan:
                return self.hasil_permintaan[key]
            kursi = self.kursi.get(request.kursi_id)
            if kursi is None:
                hasil = pb.HasilPesanResponse(sukses=False, pesan="Kursi tidak ditemukan", kursi_id=request.kursi_id)
            elif not kursi["tersedia"]:
                hasil = pb.HasilPesanResponse(sukses=False, pesan="Kursi sudah dipesan", kursi_id=request.kursi_id)
            else:
                booking_id = secrets.token_urlsafe(18)
                kursi["tersedia"] = False
                self.pesanan[booking_id] = {"kursi_id": request.kursi_id, "nama_pemesan": request.nama_pemesan.strip()}
                hasil = pb.HasilPesanResponse(
                    sukses=True,
                    pesan=f"Kursi {request.kursi_id} berhasil dipesan",
                    booking_id=booking_id,
                    kursi_id=request.kursi_id,
                )
                self.versi += 1
                self.kondisi.notify_all()
            self.hasil_permintaan[key] = hasil
            return hasil

    def PesanBeberapaKursi(self, request, context):
        kursi_ids = list(request.kursi_id)
        if not request.request_id.strip() or not kursi_ids:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "request_id dan minimal satu kursi wajib diisi")
        key = ("pesan_banyak", request.request_id)
        with self.kondisi:
            if key in self.hasil_permintaan:
                return self.hasil_permintaan[key]

            if len(set(kursi_ids)) != len(kursi_ids):
                hasil = pb.HasilPesanBanyakResponse(sukses=False, pesan="Daftar kursi berisi pilihan yang sama")
            else:
                kursi_tidak_ada = [kursi_id for kursi_id in kursi_ids if kursi_id not in self.kursi]
                kursi_sudah_dipesan = [kursi_id for kursi_id in kursi_ids if kursi_id in self.kursi and not self.kursi[kursi_id]["tersedia"]]
                if kursi_tidak_ada:
                    hasil = pb.HasilPesanBanyakResponse(
                        sukses=False,
                        pesan=f"Kursi tidak ditemukan: {', '.join(kursi_tidak_ada)}",
                    )
                elif kursi_sudah_dipesan:
                    hasil = pb.HasilPesanBanyakResponse(
                        sukses=False,
                        pesan=f"Kursi sudah dipesan: {', '.join(kursi_sudah_dipesan)}",
                    )
                else:
                    daftar_pesanan = []
                    for kursi_id in kursi_ids:
                        booking_id = secrets.token_urlsafe(18)
                        self.kursi[kursi_id]["tersedia"] = False
                        self.pesanan[booking_id] = {
                            "kursi_id": kursi_id,
                            "nama_pemesan": request.nama_pemesan.strip(),
                        }
                        daftar_pesanan.append(pb.TiketPesanan(booking_id=booking_id, kursi_id=kursi_id))
                    hasil = pb.HasilPesanBanyakResponse(
                        sukses=True,
                        pesan=f"{len(daftar_pesanan)} kursi berhasil dipesan",
                        pesanan=daftar_pesanan,
                    )
                    self.versi += 1
                    self.kondisi.notify_all()

            self.hasil_permintaan[key] = hasil
            return hasil

    def BatalkanPesanan(self, request, context):
        if not request.request_id.strip() or not request.booking_id.strip():
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "request_id dan booking_id wajib diisi")
        key = ("batal", request.request_id)
        with self.kondisi:
            if key in self.hasil_permintaan:
                return self.hasil_permintaan[key]
            pesanan = self.pesanan.pop(request.booking_id, None)
            if pesanan is None:
                hasil = pb.HasilPesanResponse(sukses=False, pesan="Pesanan tidak ditemukan atau sudah dibatalkan")
            else:
                kursi_id = pesanan["kursi_id"]
                self.kursi[kursi_id]["tersedia"] = True
                hasil = pb.HasilPesanResponse(sukses=True, pesan=f"Pesanan kursi {kursi_id} dibatalkan", kursi_id=kursi_id)
                self.versi += 1
                self.kondisi.notify_all()
            self.hasil_permintaan[key] = hasil
            return hasil

    def PantauKursi(self, request, context):
        with self.kondisi:
            versi_terkirim = self.versi
            yield self._snapshot()
        while context.is_active():
            with self.kondisi:
                self.kondisi.wait_for(
                    lambda: self.versi != versi_terkirim or not context.is_active(), timeout=1.0
                )
                if not context.is_active():
                    return
                if self.versi == versi_terkirim:
                    continue
                versi_terkirim = self.versi
                pembaruan = self._snapshot()
            yield pembaruan


def main():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
    rpc.add_LayananBioskopServicer_to_server(LayananBioskop(), server)
    port = "0.0.0.0:50051"
    server.add_insecure_port(port)
    server.start()
    print(f"Server gRPC berjalan di {port}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    main()

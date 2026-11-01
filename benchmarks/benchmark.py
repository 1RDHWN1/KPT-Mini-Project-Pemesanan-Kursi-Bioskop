"""Skrip Benchmark Beban Kinerja Sistem Reservasi Kursi Bioskop (gRPC).

Mengukur Latensi (Avg, Min, Max, p50, p95, p99) dan Throughput (req/s)
untuk 1, 5, dan 20 client secara simultan.
Mengekspor hasil ke CSV, JSON, dan grafik visual matplotlib PNG.
"""

import argparse
import csv
import json
import os
import random
import sys
import threading
import time
from concurrent import futures
from datetime import datetime

import numpy as np

# Matplotlib headless backend wajib disetel sebelum import pyplot
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import grpc
from proto import bioskop_pb2 as pb
from proto import bioskop_pb2_grpc as rpc
from server import LayananBioskop


def start_local_server():
    """Menjalankan server gRPC terisolasi pada port dinamis untuk benchmark."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=40))
    servicer = LayananBioskop()
    rpc.add_LayananBioskopServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    return server, port


def run_benchmark_scenario(target_address, concurrency, total_requests=150):
    """Menjalankan benchmark beban untuk concurrency tertentu."""
    channel = grpc.insecure_channel(target_address)
    stub = rpc.LayananBioskopStub(channel)

    requests_per_client = total_requests // concurrency
    actual_total_requests = requests_per_client * concurrency

    barrier = threading.Barrier(concurrency)
    latencies = []
    error_count = 0
    results_lock = threading.Lock()

    kursi_pool = [f"{b}{n}" for b in "ABCDE" for n in range(1, 11)]

    def worker(client_id):
        nonlocal error_count
        worker_latencies = []
        worker_errors = 0

        # Tunggu sampai semua thread client siap
        barrier.wait()

        for req_idx in range(requests_per_client):
            # Campuran beban: ~70% LihatKursi, ~30% PesanKursi
            op_type = "read" if (req_idx % 10) < 7 else "write"
            t0 = time.perf_counter()
            try:
                if op_type == "read":
                    stub.LihatKursi(pb.LihatKursiRequest())
                else:
                    k_id = random.choice(kursi_pool)
                    req_id = f"bench-c{concurrency}-u{client_id}-r{req_idx}-{random.randint(1000, 9999)}"
                    stub.PesanKursi(
                        pb.PesanKursiRequest(
                            request_id=req_id,
                            kursi_id=k_id,
                            nama_pemesan=f"BenchClient-{client_id}",
                        )
                    )
                t1 = time.perf_counter()
                worker_latencies.append((t1 - t0) * 1000.0)
            except grpc.RpcError:
                t1 = time.perf_counter()
                worker_errors += 1
                worker_latencies.append((t1 - t0) * 1000.0)

        with results_lock:
            latencies.extend(worker_latencies)
            error_count += worker_errors

    # Mulai eksekusi serentak
    wall_start = time.perf_counter()
    with futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futs = [executor.submit(worker, i) for i in range(concurrency)]
        for f in futs:
            f.result()
    wall_end = time.perf_counter()

    channel.close()
    duration_sec = wall_end - wall_start
    throughput = actual_total_requests / duration_sec if duration_sec > 0 else 0.0

    lat_arr = np.array(latencies)
    metrics = {
        "concurrency": concurrency,
        "total_requests": actual_total_requests,
        "duration_seconds": round(duration_sec, 4),
        "throughput_req_per_sec": round(throughput, 2),
        "latency_avg_ms": round(float(np.mean(lat_arr)), 3),
        "latency_min_ms": round(float(np.min(lat_arr)), 3),
        "latency_max_ms": round(float(np.max(lat_arr)), 3),
        "latency_p50_ms": round(float(np.percentile(lat_arr, 50)), 3),
        "latency_p95_ms": round(float(np.percentile(lat_arr, 95)), 3),
        "latency_p99_ms": round(float(np.percentile(lat_arr, 99)), 3),
        "error_count": error_count,
        "error_rate_pct": round((error_count / actual_total_requests) * 100.0, 2),
    }
    return metrics


def export_csv(results, file_path):
    """Mengekspor metrik ke format CSV."""
    if not results:
        return
    headers = list(results[0].keys())
    with open(file_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(results)
    print(f"Hasil CSV tersimpan di: {file_path}")


def export_json(results, file_path):
    """Mengekspor metrik ke format JSON dengan metadata."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "proyek": "Sistem Reservasi Kursi Bioskop Terdistribusi Berbasis gRPC",
        "benchmark_scenarios": results,
    }
    with open(file_path, mode="w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Hasil JSON tersimpan di: {file_path}")


def generate_plot(results, file_path):
    """Menghasilkan grafik visual ilmiah modern dan profesional dengan Matplotlib."""
    clients = [r["concurrency"] for r in results]
    throughputs = [r["throughput_req_per_sec"] for r in results]
    avg_latencies = [r["latency_avg_ms"] for r in results]
    p95_latencies = [r["latency_p95_ms"] for r in results]

    # Palet warna modern dark-theme
    bg_color = "#0f172a"
    panel_color = "#1e293b"
    grid_color = "#334155"
    text_color = "#f8fafc"
    muted_text = "#94a3b8"
    accent_blue = "#38bdf8"
    accent_green = "#4ade80"
    accent_pink = "#f43f5e"

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), facecolor=bg_color)
    fig.suptitle(
        "Analisis Kinerja Beban Sistem Reservasi Bioskop (gRPC)",
        fontsize=16,
        fontweight="bold",
        color=text_color,
        y=0.98,
    )

    x_indices = np.arange(len(clients))
    x_labels = [f"{c} Client" for c in clients]

    # Subplot 1: Throughput vs Concurrency
    ax1.set_facecolor(panel_color)
    bars = ax1.bar(
        x_indices,
        throughputs,
        width=0.45,
        color=accent_blue,
        edgecolor="#7dd3fc",
        linewidth=1.2,
        alpha=0.85,
        label="Throughput (req/s)",
    )
    ax1.plot(x_indices, throughputs, color="#e0f2fe", marker="o", markersize=7, linewidth=2)

    for bar, val in zip(bars, throughputs):
        height = bar.get_height()
        ax1.annotate(
            f"{val:.1f} req/s",
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
            color=accent_blue,
        )

    ax1.set_title("Throughput vs Concurrency Client", fontsize=13, fontweight="bold", color=text_color, pad=12)
    ax1.set_xlabel("Jumlah Client Simultan", fontsize=11, color=muted_text, labelpad=8)
    ax1.set_ylabel("Throughput (Request / Detik)", fontsize=11, color=muted_text, labelpad=8)
    ax1.set_xticks(x_indices)
    ax1.set_xticklabels(x_labels, fontsize=10, color=text_color)
    ax1.tick_params(colors=muted_text)
    ax1.grid(True, linestyle="--", alpha=0.5, color=grid_color)
    ax1.set_ylim(0, max(throughputs) * 1.25)
    for spine in ax1.spines.values():
        spine.set_color(grid_color)

    # Subplot 2: Latensi Rata-rata & p95 vs Concurrency
    ax2.set_facecolor(panel_color)
    line1 = ax2.plot(
        x_indices,
        avg_latencies,
        color=accent_green,
        marker="s",
        markersize=7,
        linewidth=2.2,
        label="Latensi Rata-rata (Avg)",
    )
    line2 = ax2.plot(
        x_indices,
        p95_latencies,
        color=accent_pink,
        marker="^",
        markersize=7,
        linewidth=2.2,
        label="Latensi 95th Percentile (p95)",
    )

    for idx, (avg_val, p95_val) in enumerate(zip(avg_latencies, p95_latencies)):
        # Label Avg selalu di bawah marker, label p95 selalu di atas marker
        ax2.annotate(
            f"{avg_val:.2f} ms",
            xy=(idx, avg_val),
            xytext=(0, -16),
            textcoords="offset points",
            ha="center",
            fontsize=9.5,
            fontweight="bold",
            color=accent_green,
        )
        ax2.annotate(
            f"{p95_val:.2f} ms",
            xy=(idx, p95_val),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=9.5,
            fontweight="bold",
            color=accent_pink,
        )

    ax2.set_title("Latensi (Avg & p95) vs Concurrency Client", fontsize=13, fontweight="bold", color=text_color, pad=12)
    ax2.set_xlabel("Jumlah Client Simultan", fontsize=11, color=muted_text, labelpad=8)
    ax2.set_ylabel("Latensi (Milidetik / ms)", fontsize=11, color=muted_text, labelpad=8)
    ax2.set_xticks(x_indices)
    ax2.set_xticklabels(x_labels, fontsize=10, color=text_color)
    ax2.tick_params(colors=muted_text)
    ax2.grid(True, linestyle="--", alpha=0.5, color=grid_color)
    y_max = max(max(p95_latencies), max(avg_latencies)) * 1.3
    ax2.set_ylim(-3.5, y_max if y_max > 0 else 10)
    for spine in ax2.spines.values():
        spine.set_color(grid_color)

    legend = ax2.legend(facecolor=panel_color, edgecolor=grid_color, fontsize=9.5)
    for text in legend.get_texts():
        text.set_color(text_color)

    plt.tight_layout(rect=[0, 0.03, 1, 0.94])
    plt.savefig(file_path, dpi=300, facecolor=bg_color, bbox_inches="tight")
    plt.close()
    print(f"Grafik visual tersimpan di: {file_path}")


def print_table(results):
    """Mencetak tabel ringkasan benchmark ke stdout."""
    col_formats = [
        ("Client", "{:<8}"),
        ("Total Req", "{:<11}"),
        ("Durasi (s)", "{:<12}"),
        ("Throughput (req/s)", "{:<20}"),
        ("Avg (ms)", "{:<10}"),
        ("p50 (ms)", "{:<10}"),
        ("p95 (ms)", "{:<10}"),
        ("p99 (ms)", "{:<10}"),
        ("Min (ms)", "{:<10}"),
        ("Max (ms)", "{:<10}"),
        ("Error (%)", "{:<10}"),
    ]
    header_str = " | ".join(fmt.format(title) for title, fmt in col_formats)
    separator = "-" * len(header_str)

    print("\n" + "=" * len(header_str))
    print("RINGKASAN HASIL PENGUJIAN KINERJA BEBAN (gRPC BENCHMARK)")
    print("=" * len(header_str))
    print(header_str)
    print(separator)

    for r in results:
        row = [
            f"{r['concurrency']}",
            f"{r['total_requests']}",
            f"{r['duration_seconds']:.3f}",
            f"{r['throughput_req_per_sec']:.2f}",
            f"{r['latency_avg_ms']:.2f}",
            f"{r['latency_p50_ms']:.2f}",
            f"{r['latency_p95_ms']:.2f}",
            f"{r['latency_p99_ms']:.2f}",
            f"{r['latency_min_ms']:.2f}",
            f"{r['latency_max_ms']:.2f}",
            f"{r['error_rate_pct']:.1f}%",
        ]
        row_str = " | ".join(fmt.format(val) for val, (_, fmt) in zip(row, col_formats))
        print(row_str)

    print(separator + "\n")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Kinerja gRPC Sistem Bioskop")
    parser.add_argument("--target", type=str, default="", help="Target gRPC host:port (misal 127.0.0.1:50051)")
    parser.add_argument("--requests", type=int, default=160, help="Jumlah request per skenario concurrency")
    args = parser.parse_args()

    bench_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(bench_dir, exist_ok=True)

    server_process = None
    if args.target:
        target_addr = args.target
        print(f"Menghubungkan ke server target yang sudah berjalan: {target_addr}")
    else:
        print("Menjalankan instance server gRPC terisolasi untuk benchmark...")
        server_process, assigned_port = start_local_server()
        target_addr = f"127.0.0.1:{assigned_port}"
        print(f"Server benchmark berjalan pada: {target_addr}")

    concurrency_levels = [1, 5, 20]
    results = []

    try:
        for c in concurrency_levels:
            print(f"Menjalankan benchmark untuk {c} concurrent client...")
            scenario_res = run_benchmark_scenario(target_addr, concurrency=c, total_requests=args.requests)
            results.append(scenario_res)

        print_table(results)

        csv_path = os.path.join(bench_dir, "hasil_benchmark.csv")
        json_path = os.path.join(bench_dir, "hasil_benchmark.json")
        plot_path = os.path.join(bench_dir, "grafik_kinerja_kpt.png")

        export_csv(results, csv_path)
        export_json(results, json_path)
        generate_plot(results, plot_path)
        print("Seluruh rangkaian benchmark berhasil diselesaikan 100%!")

    finally:
        if server_process:
            server_process.stop(grace=None)


if __name__ == "__main__":
    main()

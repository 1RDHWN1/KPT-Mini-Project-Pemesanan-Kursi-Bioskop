import os
import sys
from concurrent import futures
import pytest
import grpc

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from proto import bioskop_pb2 as pb
from proto import bioskop_pb2_grpc as rpc
from server import LayananBioskop


@pytest.fixture
def grpc_test_server():
    """Menjalankan server gRPC terisolasi pada port dinamis untuk setiap sesi pengujian."""
    servicer = LayananBioskop()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=30))
    rpc.add_LayananBioskopServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()

    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    stub = rpc.LayananBioskopStub(channel)

    yield {"stub": stub, "servicer": servicer, "channel": channel, "port": port}

    channel.close()
    server.stop(grace=None)

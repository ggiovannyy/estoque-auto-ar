"""Servidor https: uma conexão parada no meio do caminho não pode travar o sistema para os outros.

Na oficina, um celular que perde o Wi-Fi logo depois de conectar (ou uma varredura de rede de um cliente no
mesmo Wi-Fi) deixa uma conexão aberta sem mandar nada.
"""
import socket
import ssl
import threading
import urllib.request

import pytest

import server
from server import make_server
from tls import ensure_cert


@pytest.fixture
def https_port(app, tmp_path):
    cert, key = str(tmp_path / "cert.pem"), str(tmp_path / "key.pem")
    assert ensure_cert(cert, key, [])
    srv = make_server(app, "127.0.0.1", 0, cert_files=(cert, key))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def state_status(port):
    insecure = ssl._create_unverified_context()  # certificado autoassinado
    with urllib.request.urlopen(f"https://127.0.0.1:{port}/api/state", context=insecure, timeout=3) as r:
        return r.status


def test_conexao_parada_nao_trava_os_outros(https_port):
    with socket.create_connection(("127.0.0.1", https_port)):  # conecta e não começa o https
        assert state_status(https_port) == 200


def test_conexao_parada_e_fechada_depois_do_tempo_limite(https_port, monkeypatch):
    monkeypatch.setattr(server, "CONNECTION_TIMEOUT_SECONDS", 0.5)
    with socket.create_connection(("127.0.0.1", https_port)) as idle:
        idle.settimeout(5)
        assert idle.recv(1) == b""  # o servidor desistiu e fechou a conexão

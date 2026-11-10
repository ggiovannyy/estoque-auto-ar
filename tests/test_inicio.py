"""Início do sistema (run.py rodando de verdade, com dados em pasta temporária)."""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return str(s.getsockname()[1])


def start(data_dir, tmp_path, *args):
    env = {**os.environ, "MAXX_DATA": str(data_dir), "MAXX_BACKUP_DIR": str(tmp_path / "backup"),
           "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen([sys.executable, "run.py", *args], cwd=ROOT, env=env, text=True, encoding="utf-8",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def wait_until_up(port, proc, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert proc.poll() is None, f"o sistema parou ao iniciar:\n{proc.communicate()[0]}"
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1)
            return
        except OSError:
            time.sleep(0.2)
    raise AssertionError("o sistema não respondeu a tempo")


def finish(proc, timeout=20):
    """Saída e código de retorno; se o sistema ainda estiver no ar depois de `timeout`, encerra e devolve None."""
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        return None, out


def test_sem_certificado_o_sistema_nao_abre_em_http(tmp_path):
    data = tmp_path / "dados"
    (data / "cert.pem").mkdir(parents=True)  # uma pasta no lugar do arquivo: o certificado não pode ser gravado
    code, out = finish(start(data, tmp_path, "--port", free_port()))
    assert code == 1, f"o sistema subiu sem https:\n{out}"
    assert "https" in out and "--http" in out


def test_segunda_instancia_com_a_mesma_pasta_de_dados_nao_abre(tmp_path):
    """Ex.: o início automático já abriu o sistema e alguém dá dois cliques no iniciar.bat."""
    data, port = tmp_path / "dados", free_port()
    first = start(data, tmp_path, "--http", "--port", port)
    try:
        wait_until_up(port, first)
        code, out = finish(start(data, tmp_path, "--http", "--port", free_port()))
        assert code == 1, f"a segunda instância abriu:\n{out}"
        assert "já está aberto" in out
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=3).status == 200
    finally:
        finish(first, timeout=0)

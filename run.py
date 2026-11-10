"""Inicia o sistema de estoque da Maxx Auto Ar.

Uso:
    python run.py            # HTTPS na porta 8443 (necessário para a câmera do celular)
    python run.py --http     # HTTP na porta 8000 (sem câmera no celular)
"""
import argparse
import os
import socket
import sys

from app import DATA, DB_PATH, app
from backup import BackupScheduler
from tls import ensure_cert

CERT = os.path.join(DATA, "cert.pem")
KEY = os.path.join(DATA, "key.pem")


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # nao envia nada; so descobre a interface de saida
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="usar HTTP simples (sem câmera no celular)")
    ap.add_argument("--port", type=int)
    a = ap.parse_args()
    ips = lan_ips()
    use_https = not a.http and ensure_cert(CERT, KEY, ips)
    port = a.port or (8443 if use_https else 8000)
    scheme = "https" if use_https else "http"
    app.config["SESSION_COOKIE_SECURE"] = use_https  # cookie de login nunca trafega sem criptografia
    print("\n  Estoque Maxx Auto Ar no ar!")
    print(f"  Neste computador:  {scheme}://localhost:{port}")
    for ip in ips:
        print(f"  No celular (mesmo Wi-Fi):  {scheme}://{ip}:{port}")
    if use_https:
        print("  No 1º acesso o celular avisa 'conexão não segura'. Para continuar:")
        print("    Android: Avançado > Continuar.  iPhone: Mostrar detalhes > visitar este site.")
    print(f"  Backup diário em: {app.config['BACKUP_DIR']}")
    print("  Para parar: Ctrl+C\n")
    BackupScheduler(DB_PATH, app.config["BACKUP_DIR"]).start()
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            ssl_context=(CERT, KEY) if use_https else None)


if __name__ == "__main__":
    sys.exit(main())

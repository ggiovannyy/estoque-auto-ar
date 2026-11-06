"""Inicia o sistema de estoque da Maxx Auto Ar.

Uso:
    python run.py            # HTTPS na porta 8443 (necessário para a câmera do celular)
    python run.py --http     # HTTP na porta 8000 (sem câmera no celular)
"""
import argparse
import os
import socket
import sys

from app import DATA, app

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


def ensure_cert(ips):
    if os.path.exists(CERT) and os.path.exists(KEY):
        return True
    try:
        import datetime
        import ipaddress

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Maxx Auto Ar Estoque")])
        san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
        san += [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=3650))
                .add_extension(x509.SubjectAlternativeName(san), critical=False)
                .sign(key, hashes.SHA256()))
        with open(KEY, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
        with open(CERT, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return True
    except Exception as e:  # noqa: BLE001
        print("Não foi possível gerar o certificado HTTPS:", e)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="usar HTTP simples (sem câmera no celular)")
    ap.add_argument("--port", type=int)
    a = ap.parse_args()
    ips = lan_ips()
    use_https = not a.http and ensure_cert(ips)
    port = a.port or (8443 if use_https else 8000)
    scheme = "https" if use_https else "http"
    app.config["SESSION_COOKIE_SECURE"] = use_https  # cookie de login nunca trafega sem criptografia
    print("\n  Estoque Maxx Auto Ar no ar!")
    print(f"  Neste computador:  {scheme}://localhost:{port}")
    for ip in ips:
        print(f"  No celular (mesmo Wi-Fi):  {scheme}://{ip}:{port}")
    if use_https:
        print("  No 1º acesso o celular avisa 'conexão não segura': toque em Avançado > Continuar.")
    print("  Para parar: Ctrl+C\n")
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            ssl_context=(CERT, KEY) if use_https else None)


if __name__ == "__main__":
    sys.exit(main())

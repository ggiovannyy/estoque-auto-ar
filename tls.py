"""Certificado https autoassinado: o celular só libera a câmera em conexão segura.

O iPhone (todos os navegadores dele usam o motor do Safari) recusa, sem opção de continuar, certificado com mais
de 825 dias de validade ou sem a marcação de uso em servidor. O certificado é refeito quando não segue essas regras,
quando está perto de vencer ou quando o IP do computador mudou.
"""
import ipaddress
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

VALIDITY_DAYS = 800      # limite da Apple: 825
RENEW_BEFORE_DAYS = 30


def load_key(key_path):
    with open(key_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def build_cert(key, ips, now, days=VALIDITY_DAYS, server_auth=True):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Maxx Auto Ar Estoque")])
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in _all_ips(ips)]
    builder = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=days - 1))
               .add_extension(x509.SubjectAlternativeName(san), critical=False)
               .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True))
    if server_auth:
        builder = builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    return builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)


def ensure_cert(cert_path, key_path, ips, now=None):
    """Garante um certificado válido em cert_path/key_path. Devolve False se não conseguir gerar."""
    now = now or datetime.now(timezone.utc)
    if _is_usable(cert_path, key_path, ips, now):
        return True
    try:
        try:
            key = load_key(key_path)
        except (OSError, ValueError, TypeError):
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            with open(key_path, "wb") as f:
                f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                          serialization.NoEncryption()))
        with open(cert_path, "wb") as f:
            f.write(build_cert(key, ips, now))
        return True
    except Exception as e:  # noqa: BLE001
        print("Não foi possível gerar o certificado HTTPS:", e)
        return False


def _all_ips(ips):
    return sorted({"127.0.0.1", *ips})


def _is_usable(cert_path, key_path, ips, now):
    try:
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        load_key(key_path)
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except (OSError, ValueError, TypeError, x509.ExtensionNotFound):
        return False
    cert_ips = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
    return (ExtendedKeyUsageOID.SERVER_AUTH in eku
            and cert.not_valid_after_utc - cert.not_valid_before_utc <= timedelta(days=825)
            and cert.not_valid_before_utc <= now < cert.not_valid_after_utc - timedelta(days=RENEW_BEFORE_DAYS)
            and set(_all_ips(ips)) <= cert_ips)

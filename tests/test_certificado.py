"""Certificado https: precisa seguir as regras da Apple, senão o iPhone recusa o acesso sem dar opção de continuar."""
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

import tls

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
IP = "192.168.237.77"


def paths(tmp_path):
    return tmp_path / "cert.pem", tmp_path / "key.pem"


def load(cert_path):
    return x509.load_pem_x509_certificate(cert_path.read_bytes())


def ips_of(cert):
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return {str(i) for i in san.get_values_for_type(x509.IPAddress)}


def test_certificado_novo_segue_as_regras_da_apple(tmp_path):
    cert_path, key_path = paths(tmp_path)
    assert tls.ensure_cert(cert_path, key_path, [IP], now=T0)

    cert = load(cert_path)
    # iOS 13+: no máximo 825 dias de validade e uso marcado como servidor
    assert cert.not_valid_after_utc - cert.not_valid_before_utc <= timedelta(days=825)
    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    assert cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.DNSName) == ["localhost"]
    assert ips_of(cert) == {"127.0.0.1", IP}
    assert cert.not_valid_before_utc <= T0 < cert.not_valid_after_utc


def test_certificado_em_dia_e_reaproveitado(tmp_path):
    cert_path, key_path = paths(tmp_path)
    tls.ensure_cert(cert_path, key_path, [IP], now=T0)
    before = cert_path.read_bytes()

    assert tls.ensure_cert(cert_path, key_path, [IP], now=T0 + timedelta(days=300))

    assert cert_path.read_bytes() == before  # o celular não precisa aceitar o aviso de novo


@pytest.mark.parametrize("days, server_auth", [(3650, True), (800, False), (3650, False)],
                         ids=["validade-longa", "sem-uso-em-servidor", "versao-anterior-do-sistema"])
def test_certificado_fora_das_regras_da_apple_e_trocado(tmp_path, days, server_auth):
    cert_path, key_path = paths(tmp_path)
    tls.ensure_cert(cert_path, key_path, [IP], now=T0)
    old = tls.build_cert(tls.load_key(key_path), [IP], T0, days=days, server_auth=server_auth)
    cert_path.write_bytes(old)

    tls.ensure_cert(cert_path, key_path, [IP], now=T0)

    cert = load(cert_path)
    assert cert.not_valid_after_utc - cert.not_valid_before_utc <= timedelta(days=825)
    assert cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)


def test_ip_novo_do_computador_gera_certificado_novo(tmp_path):
    cert_path, key_path = paths(tmp_path)
    tls.ensure_cert(cert_path, key_path, [IP], now=T0)

    tls.ensure_cert(cert_path, key_path, ["192.168.0.10"], now=T0)

    assert "192.168.0.10" in ips_of(load(cert_path))


def test_certificado_perto_de_vencer_e_renovado(tmp_path):
    cert_path, key_path = paths(tmp_path)
    tls.ensure_cert(cert_path, key_path, [IP], now=T0)
    expires = load(cert_path).not_valid_after_utc

    later = expires - timedelta(days=10)
    tls.ensure_cert(cert_path, key_path, [IP], now=later)

    assert load(cert_path).not_valid_after_utc > later + timedelta(days=300)


def test_certificado_estragado_e_refeito(tmp_path):
    cert_path, key_path = paths(tmp_path)
    cert_path.write_text("lixo")
    key_path.write_text("lixo")

    assert tls.ensure_cert(cert_path, key_path, [IP], now=T0)

    assert ips_of(load(cert_path)) == {"127.0.0.1", IP}

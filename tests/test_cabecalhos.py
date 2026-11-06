"""Cabeçalhos HTTP que protegem o navegador (clickjacking, sniffing, scripts de fora)."""
import pytest


@pytest.mark.parametrize("path", ["/", "/api/state", "/static/app.js"])
def test_toda_resposta_tem_cabecalhos_de_seguranca(app, path):
    h = app.test_client().get(path).headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "same-origin"
    assert h["Permissions-Policy"] == "camera=(self), microphone=(), geolocation=()"


def test_csp_so_permite_scripts_do_proprio_sistema(app):
    csp = app.test_client().get("/").headers["Content-Security-Policy"]
    diretivas = dict(d.strip().split(" ", 1) for d in csp.split(";"))
    assert diretivas["default-src"] == "'self'"
    assert diretivas["script-src"] == "'self'"          # nada de inline nem de CDN
    assert diretivas["frame-ancestors"] == "'none'"
    assert diretivas["object-src"] == "'none'"


def test_api_nao_fica_em_cache_mas_arquivos_estaticos_podem(app):
    c = app.test_client()
    assert c.get("/api/state").headers["Cache-Control"] == "no-store"
    assert c.get("/static/app.js").headers.get("Cache-Control") != "no-store"

"""Ícones para instalar o sistema na tela de início (Android pelo manifesto, iPhone pelo apple-touch-icon)."""
import re
import struct


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "não é PNG"
    return struct.unpack(">II", data[16:24])


def test_manifesto_tem_icones_png_de_192_e_512(app):
    c = app.test_client()
    icons = c.get("/manifest.webmanifest").get_json()["icons"]
    pngs = {i["sizes"]: i["src"] for i in icons if i["type"] == "image/png"}
    assert set(pngs) >= {"192x192", "512x512"}
    for size, src in pngs.items():
        w, h = png_size(c.get(src).data)
        assert f"{w}x{h}" == size


def test_pagina_aponta_o_icone_do_iphone(app):
    c = app.test_client()
    html = c.get("/").get_data(as_text=True)
    m = re.search(r'<link rel="apple-touch-icon" href="([^"]+)"', html)
    assert m, "falta o apple-touch-icon"
    assert png_size(c.get(m.group(1)).data) == (180, 180)

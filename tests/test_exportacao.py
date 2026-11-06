"""Planilha exportada: abre no Excel sem executar fórmulas vindas de dados digitados."""
import csv
import io

import pytest

import app as appmod
from conftest import new_product


def export_rows(client):
    r = client.get("/api/export.csv")
    assert r.status_code == 200
    text = r.get_data(as_text=True).lstrip("\ufeff")
    return list(csv.reader(io.StringIO(text), delimiter=";"))


@pytest.mark.parametrize("perigoso", ['=HYPERLINK("http://x.test","clique")', "+1+1", "-2+3", "@SUM(1+1)"])
def test_texto_que_parece_formula_sai_como_texto(owner, perigoso):
    new_product(owner, name=perigoso, code=perigoso, brand=perigoso)
    header, row = export_rows(owner)
    cols = dict(zip(header, row))
    for campo in ("Nome", "Código", "Marca"):
        assert cols[campo] == "'" + perigoso, campo


def test_valores_normais_nao_mudam(owner):
    new_product(owner, name="Filtro de cabine Onix", code="FC-210", barcode="7891234567895", ncm="84213990", qty=3)
    header, row = export_rows(owner)
    cols = dict(zip(header, row))
    assert cols["Nome"] == "Filtro de cabine Onix"
    assert cols["Código"] == "FC-210"
    assert cols["Código de barras"] == "7891234567895"
    assert cols["NCM"] == "84213990"
    assert cols["Quantidade"] == "3"


def test_exportacao_exige_login(app):
    assert app.test_client().get("/api/export.csv").status_code == 401


@pytest.mark.parametrize("valor, esperado", [("\t=1+1", "'\t=1+1"), ("\r=1+1", "'\r=1+1"), ("=A1", "'=A1"),
                                             ("Filtro", "Filtro"), ("", ""), (3, 3), (None, None)])
def test_csv_safe(valor, esperado):
    assert appmod.csv_safe(valor) == esperado

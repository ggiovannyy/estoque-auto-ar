"""Movimentação em lote (leitura contínua): entradas ou contagens de várias peças, tudo ou nada."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import app as appmod
from conftest import move, new_product


def batch(client, mtype, items, **extra):
    return client.post("/api/products/moves", json={"type": mtype, "items": items, **extra})


def qty_of(client, pid):
    return client.get(f"/api/products/{pid}").get_json()["qty"]


def test_entrada_em_lote_soma_cada_peca_e_registra_o_historico(owner):
    a, b = new_product(owner, qty=1), new_product(owner, qty=0)
    r = batch(owner, "in", [{"product_id": a["id"], "qty": 3}, {"product_id": b["id"], "qty": 2}], note="NF 123")
    assert r.status_code == 200, r.get_json()
    assert {p["id"]: p["qty"] for p in r.get_json()["products"]} == {a["id"]: 4, b["id"]: 2}
    last = owner.get(f"/api/products/{a['id']}").get_json()["movements"][0]
    assert (last["type"], last["delta"], last["balance"], last["note"]) == ("in", 3, 4, "NF 123")


def test_atendente_pode_dar_entrada_em_lote(owner, attendant):
    p = new_product(owner, qty=0)
    assert batch(attendant, "in", [{"product_id": p["id"], "qty": 1}]).status_code == 200
    assert qty_of(owner, p["id"]) == 1


def test_contagem_em_lote_define_o_saldo_e_e_so_do_dono(owner, attendant):
    a, b = new_product(owner, qty=5), new_product(owner, qty=5)
    items = [{"product_id": a["id"], "qty": 2}, {"product_id": b["id"], "qty": 0}]
    assert batch(attendant, "adjust", items).status_code == 403
    assert batch(owner, "adjust", items).status_code == 200
    assert (qty_of(owner, a["id"]), qty_of(owner, b["id"])) == (2, 0)


def test_saida_em_lote_nao_existe(owner):
    p = new_product(owner, qty=5)
    assert batch(owner, "out", [{"product_id": p["id"], "qty": 1}]).status_code == 400
    assert qty_of(owner, p["id"]) == 5


def test_um_item_invalido_recusa_o_lote_inteiro(owner):
    a = new_product(owner, qty=1)
    r = batch(owner, "in", [{"product_id": a["id"], "qty": 2}, {"product_id": 999999, "qty": 1}])
    assert r.status_code == 400
    assert "não encontrada" in r.get_json()["error"]
    assert qty_of(owner, a["id"]) == 1  # a primeira entrada também foi desfeita


def test_passar_do_teto_recusa_o_lote_e_diz_qual_peca(owner):
    a = new_product(owner, name="Compressor", qty=appmod.MAX_QTY)
    r = batch(owner, "in", [{"product_id": a["id"], "qty": 1}])
    assert r.status_code == 400
    assert "Compressor" in r.get_json()["error"]


def test_lote_mal_formado_e_recusado(owner):
    p = new_product(owner, qty=1)
    pid = p["id"]
    for items in ([], "abc", [{"product_id": pid}], [{"product_id": pid, "qty": 0}],
                  [{"product_id": pid, "qty": appmod.MAX_QTY + 1}], [{"product_id": "x", "qty": 1}],
                  [{"product_id": pid, "qty": 1}, {"product_id": pid, "qty": 2}],
                  [{"product_id": pid, "qty": 1}] * (appmod.MAX_BATCH + 1)):
        assert batch(owner, "in", items).status_code == 400, items
    assert qty_of(owner, pid) == 1


def test_reenvio_do_mesmo_lote_nao_grava_de_novo(owner):
    p = new_product(owner, qty=0)
    items = [{"product_id": p["id"], "qty": 2}]
    assert batch(owner, "in", items, request_id="lote-1").status_code == 200
    r = batch(owner, "in", items, request_id="lote-1")
    assert r.status_code == 200
    assert r.get_json()["products"][0]["qty"] == 2
    assert qty_of(owner, p["id"]) == 2


def test_identificador_do_lote_invalido_e_recusado(owner):
    p = new_product(owner, qty=0)
    for rid in ("", 123, "x" * 61):
        assert batch(owner, "in", [{"product_id": p["id"], "qty": 1}], request_id=rid).status_code == 400
    assert qty_of(owner, p["id"]) == 0


def test_contagem_em_lote_recusada_se_alguma_peca_mudou(owner):
    a, b = new_product(owner, name="Filtro A", qty=5), new_product(owner, name="Filtro B", qty=5)
    move(owner, b["id"], "out", 1)  # vendeu uma enquanto o dono contava
    r = batch(owner, "adjust", [{"product_id": a["id"], "qty": 7, "expected": 5},
                                {"product_id": b["id"], "qty": 7, "expected": 5}])
    assert r.status_code == 409
    body = r.get_json()
    assert "Filtro B" in body["error"] and "de 5 para 4" in body["error"]
    assert body["changed"] == [{"product_id": b["id"], "qty": 4}]
    assert (qty_of(owner, a["id"]), qty_of(owner, b["id"])) == (5, 4)


def test_lotes_simultaneos_nao_perdem_quantidade(owner, login_client):
    a, b = new_product(owner, qty=0), new_product(owner, qty=0)
    clients = [login_client("dono", "senha-do-dono") for _ in range(6)]
    items = [{"product_id": a["id"], "qty": 1}, {"product_id": b["id"], "qty": 2}]
    with ThreadPoolExecutor(6) as pool:
        codes = list(pool.map(lambda c: [batch(c, "in", items).status_code for _ in range(20)], clients))
    assert all(code == 200 for per in codes for code in per)
    assert (qty_of(owner, a["id"]), qty_of(owner, b["id"])) == (120, 240)
    conn = sqlite3.connect(appmod.DB_PATH)
    total, = conn.execute("SELECT SUM(delta) FROM movements WHERE product_id=?", (b["id"],)).fetchone()
    conn.close()
    assert total == 240


def test_corpo_ou_observacao_fora_do_formato_e_recusado(owner):
    p = new_product(owner, qty=0)
    item = [{"product_id": p["id"], "qty": 1}]
    assert owner.post("/api/products/moves", json=[1, 2]).status_code == 400
    assert batch(owner, "in", item, note=123).status_code == 400
    assert batch(owner, "in", item, note="x" * 501).status_code == 400
    assert batch(owner, "in", [{"product_id": p["id"], "qty": True}]).status_code == 400
    assert qty_of(owner, p["id"]) == 0


def test_lote_maximo_cabe_no_limite_do_corpo(owner):
    """MAX_BATCH peças com contagem e a observação mais longa ainda cabem em MAX_CONTENT_LENGTH."""
    ids = [new_product(owner, qty=appmod.MAX_QTY)["id"] for _ in range(appmod.MAX_BATCH)]
    items = [{"product_id": pid, "qty": appmod.MAX_QTY, "expected": appmod.MAX_QTY} for pid in ids]
    r = batch(owner, "adjust", items, note="x" * 500, request_id="r" * 60)
    assert r.status_code == 200, r.get_json()

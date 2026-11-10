"""Corridas entre dois usuários: a gravação do "outro" acontece no meio da requisição (fixture interleave)."""
import sqlite3

import app as appmod
from conftest import new_product


def one(sql, *args):
    conn = sqlite3.connect(appmod.DB_PATH)
    try:
        return conn.execute(sql, args).fetchone()
    finally:
        conn.close()


def test_excluir_categoria_nunca_tira_a_categoria_de_peca_cadastrada_no_mesmo_instante(owner, interleave):
    cid = owner.post("/api/categories", json={"name": "Sensor de pressão"}).get_json()["id"]
    log = interleave("UPDATE products SET category_id=NULL", lambda other: other.execute(
        "INSERT INTO products(name, category_id, created_at) VALUES ('Peça nova', ?, '2026-11-10 10:00:00')", (cid,)))
    r = owner.delete(f"/api/categories/{cid}")
    orphan = one("SELECT COUNT(*) FROM products WHERE name='Peça nova' AND category_id IS NULL")[0]
    assert orphan == 0, f"a peça nova perdeu a categoria ({log})"
    if log == ["gravou no meio"]:
        assert r.status_code == 400


def test_categoria_com_peca_ativa_nao_e_excluida(owner):
    cid = owner.post("/api/categories", json={"name": "Válvula TXV"}).get_json()["id"]
    p = new_product(owner, category_id=cid)
    r = owner.delete(f"/api/categories/{cid}")
    assert r.status_code == 400 and "Há peças" in r.get_json()["error"]
    assert owner.get(f"/api/products/{p['id']}").get_json()["category_id"] == cid


def test_categoria_so_com_pecas_excluidas_pode_ser_excluida(owner):
    cid = owner.post("/api/categories", json={"name": "Correia dentada"}).get_json()["id"]
    p = new_product(owner, category_id=cid)
    assert owner.delete(f"/api/products/{p['id']}").status_code == 200
    assert owner.delete(f"/api/categories/{cid}").status_code == 200
    assert one("SELECT category_id FROM products WHERE id=?", p["id"])[0] is None

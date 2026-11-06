"""Vários atendentes mexendo na mesma peça ao mesmo tempo não podem perder quantidade."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import app as appmod
from conftest import move, new_product

THREADS = 8
MOVES_PER_THREAD = 25


def _run_parallel(login_client, fn):
    """Roda fn(cliente, numero_da_thread) MOVES_PER_THREAD vezes em cada thread; devolve os status HTTP."""
    clients = [login_client("dono", "senha-do-dono") for _ in range(THREADS)]
    with ThreadPoolExecutor(THREADS) as pool:
        per_thread = pool.map(lambda i: [fn(clients[i], i) for _ in range(MOVES_PER_THREAD)], range(THREADS))
        return [code for codes in per_thread for code in codes]


def test_entradas_simultaneas_somam_todas(owner, login_client):
    p = new_product(owner, qty=0)
    codes = _run_parallel(login_client, lambda c, _: move(c, p["id"], "in", 1).status_code)
    assert codes.count(200) == THREADS * MOVES_PER_THREAD
    assert owner.get(f"/api/products/{p['id']}").get_json()["qty"] == THREADS * MOVES_PER_THREAD


def test_saidas_simultaneas_nunca_vendem_mais_que_o_estoque(owner, login_client):
    estoque = 50
    p = new_product(owner, qty=estoque)
    codes = _run_parallel(login_client, lambda c, _: move(c, p["id"], "out", 1).status_code)
    assert codes.count(200) == estoque
    assert set(codes) <= {200, 400}
    assert owner.get(f"/api/products/{p['id']}").get_json()["qty"] == 0


def test_saldo_do_historico_bate_com_o_estoque(owner, login_client):
    p = new_product(owner, qty=100)
    _run_parallel(login_client, lambda c, i: move(c, p["id"], "in" if i % 2 else "out", 1).status_code)
    qty = owner.get(f"/api/products/{p['id']}").get_json()["qty"]
    conn = sqlite3.connect(appmod.DB_PATH)
    total, = conn.execute("SELECT SUM(delta) FROM movements WHERE product_id=?", (p["id"],)).fetchone()
    last, = conn.execute("SELECT balance FROM movements WHERE product_id=? ORDER BY id DESC LIMIT 1",
                         (p["id"],)).fetchone()
    conn.close()
    assert qty == total == last == 100

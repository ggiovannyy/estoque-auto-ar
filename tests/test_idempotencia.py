"""Reenvio de uma movimentação: com Wi-Fi ruim, a baixa é gravada, a resposta se perde e o atendente toca de novo."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import app as appmod
from conftest import move, new_product


def qty_of(client, pid):
    return client.get(f"/api/products/{pid}").get_json()["qty"]


def moves_with(request_id):
    conn = sqlite3.connect(appmod.DB_PATH)
    try:
        return conn.execute("SELECT COUNT(*) FROM movements WHERE request_id=?", (request_id,)).fetchone()[0]
    finally:
        conn.close()


def test_mesmo_pedido_enviado_duas_vezes_baixa_uma_vez_so(owner):
    p = new_product(owner, qty=5)
    first = move(owner, p["id"], "out", 1, request_id="pedido-1")
    again = move(owner, p["id"], "out", 1, request_id="pedido-1")
    assert first.status_code == again.status_code == 200
    assert again.get_json()["qty"] == 4
    assert qty_of(owner, p["id"]) == 4
    assert moves_with("pedido-1") == 1


def test_pedidos_diferentes_valem_cada_um(owner):
    p = new_product(owner, qty=5)
    assert move(owner, p["id"], "out", 1, request_id="pedido-a").status_code == 200
    assert move(owner, p["id"], "out", 1, request_id="pedido-b").status_code == 200
    assert qty_of(owner, p["id"]) == 3


def test_sem_identificador_continua_funcionando(owner):
    p = new_product(owner, qty=5)
    assert move(owner, p["id"], "out", 1).status_code == 200
    assert move(owner, p["id"], "out", 1).status_code == 200
    assert qty_of(owner, p["id"]) == 3


def test_pedido_recusado_pode_ser_reenviado_com_o_mesmo_identificador(owner):
    p = new_product(owner, qty=1)
    assert move(owner, p["id"], "out", 2, request_id="pedido-x").status_code == 400
    assert moves_with("pedido-x") == 0
    assert move(owner, p["id"], "in", 2, request_id="pedido-x").status_code == 200
    assert qty_of(owner, p["id"]) == 3


def test_identificador_invalido_e_recusado(owner):
    p = new_product(owner, qty=5)
    for bad in ("x" * 65, 123, ""):
        assert move(owner, p["id"], "out", 1, request_id=bad).status_code == 400, bad
    assert qty_of(owner, p["id"]) == 5


def test_reenvios_simultaneos_do_mesmo_pedido_gravam_uma_vez(owner, login_client):
    p = new_product(owner, qty=50)
    clients = [login_client("dono", "senha-do-dono") for _ in range(8)]
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda c: move(c, p["id"], "out", 1, request_id="pedido-z").status_code, clients))
    assert codes == [200] * 8
    assert qty_of(owner, p["id"]) == 49
    assert moves_with("pedido-z") == 1

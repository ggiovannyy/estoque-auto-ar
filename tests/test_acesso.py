"""Login, primeiro acesso e permissões de dono e atendente."""
import pytest

from conftest import new_product


def test_api_exige_login(app):
    c = app.test_client()
    assert c.get("/api/products").status_code == 401
    assert c.post("/api/products", json={"name": "x"}).status_code == 401


def test_setup_so_funciona_uma_vez(app, owner):
    r = app.test_client().post("/api/setup", json={"name": "Intruso", "username": "x", "password": "qualquer-senha"})
    assert r.status_code == 403


def test_senha_errada_e_recusada(app, owner):
    r = app.test_client().post("/api/login", json={"username": "dono", "password": "errada"})
    assert r.status_code == 401


def test_atendente_movimenta_mas_nao_exclui_peca_nem_gerencia_usuarios(attendant):
    p = new_product(attendant)
    assert attendant.post(f"/api/products/{p['id']}/move", json={"type": "out", "qty": 1}).status_code == 200
    assert attendant.delete(f"/api/products/{p['id']}").status_code == 403
    assert attendant.get("/api/users").status_code == 403
    assert attendant.put("/api/settings", json={"min_default": 9}).status_code == 403


def test_usuario_desativado_perde_o_acesso_na_hora(owner, attendant):
    ana = next(u for u in owner.get("/api/users").get_json() if u["username"] == "ana")
    assert owner.put(f"/api/users/{ana['id']}", json={"active": False}).status_code == 200
    assert attendant.get("/api/products").status_code == 401


# ---------------------------------------------------------------- primeiro acesso
DONO_NOVO = {"name": "Dono", "username": "dono", "password": "senha-do-dono"}


def client_from(app, ip):
    c = app.test_client()
    c.environ_base["REMOTE_ADDR"] = ip
    return c


def test_primeiro_acesso_pela_rede_e_recusado(app):
    c = client_from(app, "192.168.0.50")
    assert c.get("/api/state").get_json()["setup_here"] is False
    r = c.post("/api/setup", json=DONO_NOVO)
    assert r.status_code == 403
    assert "computador" in r.get_json()["error"]
    assert c.get("/api/state").get_json()["setup_needed"] is True  # ninguem virou dono


@pytest.mark.parametrize("ip", ["127.0.0.1", "::1"])
def test_primeiro_acesso_no_proprio_computador_funciona(app, ip):
    c = client_from(app, ip)
    assert c.get("/api/state").get_json()["setup_here"] is True
    assert c.post("/api/setup", json=DONO_NOVO).status_code == 200


def test_depois_do_primeiro_acesso_o_login_funciona_pela_rede(app, owner):
    r = client_from(app, "192.168.0.50").post("/api/login", json={"username": "dono", "password": "senha-do-dono"})
    assert r.status_code == 200

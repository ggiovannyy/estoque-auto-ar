"""Entradas fora do formato: o servidor responde 400 com mensagem, nunca 500."""
import pytest

from conftest import new_product

NOT_AN_OBJECT = [[1], "texto", 5, True]


def routes(pid, uid):
    """(método, rota) de todas as rotas que leem JSON."""
    return [("post", "/api/login"), ("post", "/api/categories"), ("post", "/api/products"),
            ("put", f"/api/products/{pid}"), ("post", f"/api/products/{pid}/move"), ("put", "/api/settings"),
            ("post", "/api/users"), ("put", f"/api/users/{uid}"), ("post", "/api/password")]


@pytest.fixture
def ids(owner):
    pid = new_product(owner, qty=5)["id"]
    uid = owner.get("/api/state").get_json()["user"]["id"]
    return pid, uid


@pytest.mark.parametrize("body", NOT_AN_OBJECT)
def test_corpo_que_nao_e_objeto_json_e_recusado(owner, ids, body):
    for method, route in routes(*ids):
        r = getattr(owner, method)(route, json=body)
        assert r.status_code == 400, (route, body, r.status_code)
        assert r.get_json()["error"]


def test_primeiro_acesso_com_corpo_que_nao_e_objeto_e_recusado(app):
    r = app.test_client().post("/api/setup", json=["x"])
    assert r.status_code == 400 and r.get_json()["error"]


@pytest.mark.parametrize("route, body", [
    ("/api/login", {"username": 5, "password": "x"}),
    ("/api/login", {"username": "dono", "password": 12345678}),
    ("/api/categories", {"name": ["Filtro"]}),
    ("/api/products", {"name": {"a": 1}}),
    ("/api/products", {"name": "Filtro", "barcode": 789}),
    ("/api/users", {"name": "Ana", "username": "ana", "password": 12345678}),
    ("/api/password", {"current": "senha-do-dono", "new": 12345678}),
])
def test_campo_de_texto_com_outro_tipo_e_recusado(owner, route, body):
    r = owner.post(route, json=body)
    assert r.status_code == 400, r.status_code
    assert r.get_json()["error"]


def test_movimentacao_com_observacao_que_nao_e_texto_e_recusada(owner, ids):
    pid, _ = ids
    r = owner.post(f"/api/products/{pid}/move", json={"type": "out", "qty": 1, "note": 5})
    assert r.status_code == 400
    assert owner.get(f"/api/products/{pid}").get_json()["qty"] == 5


@pytest.mark.parametrize("bad", ["false", 0, None])
def test_ativar_ou_desativar_exige_verdadeiro_ou_falso(owner, attendant, bad):
    ana = next(u for u in owner.get("/api/users").get_json() if u["username"] == "ana")
    assert owner.put(f"/api/users/{ana['id']}", json={"active": bad}).status_code == 400
    assert attendant.get("/api/summary").status_code == 200   # continua ativa


def test_quantidade_verdadeiro_ou_falso_e_recusada(owner, ids):
    pid, _ = ids
    assert owner.post(f"/api/products/{pid}/move", json={"type": "in", "qty": True}).status_code == 400

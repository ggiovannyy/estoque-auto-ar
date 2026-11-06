"""Proteção contra adivinhação de senha: bloqueio após erros seguidos e senha mínima."""
import pytest

import app as appmod

DONO = {"username": "dono", "password": "senha-do-dono"}


def login(client, username, password):
    return client.post("/api/login", json={"username": username, "password": password})


@pytest.fixture
def clock(monkeypatch):
    """Relógio controlado pelo teste para os dois limitadores."""
    now = [1000.0]
    for t in (appmod.user_throttle, appmod.ip_throttle):
        monkeypatch.setattr(t, "clock", lambda: now[0])
    return now


def test_bloqueia_depois_de_5_erros_mesmo_com_a_senha_certa(app, owner, clock):
    c = app.test_client()
    assert [login(c, "dono", f"errada{i}").status_code for i in range(5)] == [401] * 5
    r = login(c, **DONO)
    assert r.status_code == 429
    assert "Muitas tentativas" in r.get_json()["error"]


def test_bloqueio_expira_depois_de_alguns_minutos(app, owner, clock):
    c = app.test_client()
    for i in range(5):
        login(c, "dono", f"errada{i}")
    clock[0] += appmod.LoginThrottle.LOCK_SECONDS + 1
    assert login(c, **DONO).status_code == 200


def test_login_certo_zera_a_contagem_de_erros(app, owner, clock):
    c = app.test_client()
    for i in range(4):
        login(c, "dono", f"errada{i}")
    assert login(c, **DONO).status_code == 200
    assert [login(c, "dono", f"errada{i}").status_code for i in range(4)] == [401] * 4


def test_erros_antigos_fora_da_janela_nao_contam(app, owner, clock):
    c = app.test_client()
    for i in range(4):
        login(c, "dono", f"errada{i}")
    clock[0] += appmod.LoginThrottle.WINDOW_SECONDS + 1
    assert login(c, "dono", "errada-de-novo").status_code == 401
    assert login(c, **DONO).status_code == 200


def test_bloqueio_de_um_usuario_nao_trava_outro(app, owner, attendant, clock):
    c = app.test_client()
    for i in range(5):
        login(c, "dono", f"errada{i}")
    assert login(c, "ana", "senha-da-ana").status_code == 200


def test_muitos_erros_do_mesmo_ip_em_usuarios_diferentes_bloqueiam_o_ip(app, owner, clock):
    c = app.test_client()
    limite = appmod.ip_throttle.max_failures
    for i in range(limite):
        assert login(c, f"usuario{i}", "x").status_code == 401
    assert login(c, **DONO).status_code == 429


@pytest.mark.parametrize("pw", ["", "1234", "1234567"])
def test_senha_curta_e_recusada_ao_criar_usuario_e_ao_trocar_a_propria(app, owner, pw):
    assert owner.post("/api/users", json={"name": "B", "username": "b", "password": pw}).status_code == 400
    assert owner.post("/api/password", json={"current": "senha-do-dono", "new": pw}).status_code == 400
    assert login(app.test_client(), **DONO).status_code == 200  # senha do dono nao mudou


def test_senha_com_8_caracteres_e_aceita(owner):
    assert owner.post("/api/users", json={"name": "B", "username": "b", "password": "12345678"}).status_code == 201


def test_setup_recusa_senha_curta(app):
    r = app.test_client().post("/api/setup", json={"name": "Dono", "username": "dono", "password": "1234567"})
    assert r.status_code == 400
    assert "8" in r.get_json()["error"]


def test_redefinir_senha_curta_e_recusada(owner):
    uid = owner.get("/api/users").get_json()[0]["id"]
    assert owner.put(f"/api/users/{uid}", json={"password": "1234567"}).status_code == 400

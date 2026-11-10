"""Sessões: trocar a senha derruba as sessões abertas com a senha antiga (ex.: celular perdido ou roubado)."""
from conftest import _login_client


def copy_session(app, client):
    """Outro aparelho com uma cópia do cookie de login de `client`."""
    with client.session_transaction() as s:
        stolen = dict(s)
    other = app.test_client()
    with other.session_transaction() as s:
        s.update(stolen)
    return other


def test_trocar_a_propria_senha_derruba_as_outras_sessoes_e_mantem_a_atual(app, owner):
    lost_phone = copy_session(app, owner)
    r = owner.post("/api/password", json={"current": "senha-do-dono", "new": "senha-nova-do-dono"})
    assert r.status_code == 200
    assert lost_phone.get("/api/summary").status_code == 401
    assert owner.get("/api/summary").status_code == 200


def test_dono_redefinir_a_senha_do_atendente_derruba_a_sessao_dele(app, owner, attendant):
    ana_id = next(u["id"] for u in owner.get("/api/users").get_json() if u["username"] == "ana")
    assert owner.put(f"/api/users/{ana_id}", json={"password": "senha-nova-da-ana"}).status_code == 200
    assert attendant.get("/api/summary").status_code == 401
    assert _login_client(app, "ana", "senha-nova-da-ana").get("/api/summary").status_code == 200


def test_dono_redefinir_a_propria_senha_pela_lista_mantem_a_sessao(owner):
    me = owner.get("/api/state").get_json()["user"]["id"]
    assert owner.put(f"/api/users/{me}", json={"password": "senha-nova-do-dono"}).status_code == 200
    assert owner.get("/api/summary").status_code == 200


def test_sessao_sem_a_marca_da_senha_pede_login_de_novo(app, owner):
    """Cookies emitidos antes desta versão só tinham o uid."""
    me = owner.get("/api/state").get_json()["user"]["id"]
    old = app.test_client()
    with old.session_transaction() as s:
        s["uid"] = me
    assert old.get("/api/summary").status_code == 401


def test_estado_nao_expoe_a_senha(owner):
    assert set(owner.get("/api/state").get_json()["user"]) == {"id", "name", "username", "role", "active"}

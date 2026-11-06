import os
import sys
import tempfile

import pytest

# O app cria a chave secreta e o banco na pasta de dados ao ser importado:
# aponte para uma pasta temporária antes de importar.
os.environ["MAXX_DATA"] = tempfile.mkdtemp(prefix="maxx-test-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DB_PATH", str(tmp_path / "estoque.db"))
    appmod.init_db()
    appmod.app.config.update(TESTING=True)
    return appmod.app


def _login_client(app, username, password):
    c = app.test_client()
    r = c.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.get_json()
    return c


@pytest.fixture
def owner(app):
    """Cliente logado como dono (o primeiro usuário, criado pelo setup)."""
    c = app.test_client()
    r = c.post("/api/setup", json={"name": "Dono", "username": "dono", "password": "senha-do-dono"})
    assert r.status_code == 200, r.get_json()
    return c


@pytest.fixture
def attendant(app, owner):
    r = owner.post("/api/users", json={"name": "Ana", "username": "ana", "password": "senha-da-ana"})
    assert r.status_code == 201, r.get_json()
    return _login_client(app, "ana", "senha-da-ana")


@pytest.fixture
def login_client(app):
    return lambda u, p: _login_client(app, u, p)


def new_product(client, **fields):
    body = {"name": "Filtro de cabine", "qty": 5, **fields}
    r = client.post("/api/products", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def move(client, pid, type_, qty, **extra):
    return client.post(f"/api/products/{pid}/move", json={"type": type_, "qty": qty, **extra})

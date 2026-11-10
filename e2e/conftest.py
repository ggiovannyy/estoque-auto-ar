"""Testes de interface: sobem o sistema de verdade (run.py) e usam um navegador (Playwright).

Rodar:  python -m playwright install chromium   (uma vez)
        pytest -q e2e
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from dados import unique
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNER = {"name": "Dono", "username": "dono", "password": "senha-do-dono"}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until_up(url, proc, log, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"o servidor parou ao iniciar:\n{log.read_text(encoding='utf-8')}")
        try:
            urllib.request.urlopen(url + "/api/state", timeout=1)
            return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("o servidor não respondeu a tempo")


@pytest.fixture(scope="session")
def playwright():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def base_url(tmp_path_factory, playwright):
    """Sistema rodando com dados e backup em pastas temporárias (nunca no OneDrive real)."""
    port = free_port()
    env = {**os.environ,
           "MAXX_DATA": str(tmp_path_factory.mktemp("dados")),
           "MAXX_BACKUP_DIR": str(tmp_path_factory.mktemp("backup")),
           "PYTHONIOENCODING": "utf-8"}
    # A saída vai para um arquivo: um pipe que ninguém lê enche e trava o servidor.
    log = tmp_path_factory.mktemp("log") / "servidor.log"
    with open(log, "w", encoding="utf-8") as out:
        proc = subprocess.Popen([sys.executable, "run.py", "--http", "--port", str(port)], cwd=ROOT, env=env,
                                stdout=out, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        wait_until_up(url, proc, log)
        req = playwright.request.new_context(base_url=url)  # primeiro acesso: só de 127.0.0.1, como na oficina
        assert req.post("/api/setup", data=OWNER).ok
        req.dispose()
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser(playwright):
    b = playwright.chromium.launch()
    yield b
    b.close()


def _logged_context(browser, base_url, **options):
    ctx = browser.new_context(base_url=base_url, **options)
    assert ctx.request.post("/api/login", data={"username": OWNER["username"], "password": OWNER["password"]}).ok
    return ctx


@pytest.fixture
def page(browser, base_url):
    """Computador da oficina (com mouse), já logado como dono."""
    ctx = _logged_context(browser, base_url, viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    yield pg
    ctx.close()
    assert not errors, f"erro de JavaScript na página: {errors}"


@pytest.fixture
def phone(browser, base_url):
    """Celular (tela de toque), já logado como dono."""
    ctx = _logged_context(browser, base_url, viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    yield pg
    ctx.close()


@pytest.fixture
def api(page):
    """Cria dados pela API, com a mesma sessão do navegador."""
    class Api:
        @staticmethod
        def product(**fields):
            body = {"name": unique("Peça"), "qty": 5, **fields}
            r = page.request.post("/api/products", data=body)
            assert r.ok, r.text()
            return r.json()

        @staticmethod
        def category(name):
            r = page.request.post("/api/categories", data={"name": name})
            assert r.ok, r.text()
            return r.json()
    return Api


@pytest.fixture
def attendant_page(browser, base_url, page):
    """Computador da oficina, logado como um atendente novo (criado pelo dono)."""
    user = {"name": "Atendente", "username": unique("atendente").lower().replace(" ", ""), "password": "senha-do-atendente"}
    assert page.request.post("/api/users", data=user).ok
    ctx = browser.new_context(base_url=base_url, viewport={"width": 1280, "height": 800})
    assert ctx.request.post("/api/login", data={"username": user["username"], "password": user["password"]}).ok
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    yield pg
    ctx.close()
    assert not errors, f"erro de JavaScript na página: {errors}"

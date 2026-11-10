"""Migrações do banco: versão em PRAGMA user_version, passos numerados e atômicos."""
import sqlite3

import pytest

import app as appmod
import migrations
from migrations import MIGRATIONS, SchemaTooNewError, migrate, schema_version

# Banco criado pela versão anterior às migrações (user_version 0), como está hoje na oficina.
LEGACY_SCHEMA = """
CREATE TABLE users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'atendente',
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
CREATE TABLE products (
  id INTEGER PRIMARY KEY, barcode TEXT UNIQUE, code TEXT, name TEXT NOT NULL,
  category_id INTEGER REFERENCES categories(id), ncm TEXT, brand TEXT,
  qty INTEGER NOT NULL DEFAULT 0 CHECK (qty >= 0), min_qty INTEGER,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE movements (
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
  type TEXT NOT NULL CHECK (type IN ('in','out','adjust')), qty INTEGER NOT NULL,
  delta INTEGER NOT NULL, balance INTEGER NOT NULL,
  note TEXT, user_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX idx_mov_product ON movements(product_id, id DESC);
INSERT INTO users(name, username, password_hash, role) VALUES ('Dono', 'dono', 'hash', 'dono');
INSERT INTO categories(name) VALUES ('Filtro de cabine'), ('Compressor');
INSERT INTO products(barcode, name, category_id, qty, created_at)
  VALUES ('7891234567890', 'Filtro Tecfil', 1, 7, '2026-11-01 10:00:00');
INSERT INTO movements(product_id, type, qty, delta, balance, user_id, created_at)
  VALUES (1, 'in', 7, 7, 7, 1, '2026-11-01 10:00:00');
INSERT INTO settings(key, value) VALUES ('min_default', '5');
"""


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "estoque.db")
    yield c
    c.close()


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_banco_novo_fica_na_ultima_versao(conn):
    migrate(conn)
    assert schema_version(conn) == len(MIGRATIONS)
    assert {"users", "categories", "products", "movements", "settings"} <= tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 11
    assert conn.execute("SELECT value FROM settings WHERE key='min_default'").fetchone()[0] == "2"


def test_banco_antigo_sobe_de_versao_sem_perder_dados(conn):
    conn.executescript(LEGACY_SCHEMA)
    assert schema_version(conn) == 0

    migrate(conn)

    assert schema_version(conn) == len(MIGRATIONS)
    assert conn.execute("SELECT name, qty FROM products").fetchall() == [("Filtro Tecfil", 7)]
    assert conn.execute("SELECT COUNT(*) FROM movements").fetchone()[0] == 1
    assert conn.execute("SELECT username FROM users").fetchall() == [("dono",)]
    # categorias e mínimo configurados na oficina continuam como estavam
    assert [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY id")] == ["Filtro de cabine", "Compressor"]
    assert conn.execute("SELECT value FROM settings WHERE key='min_default'").fetchone()[0] == "5"


def test_rodar_de_novo_nao_repete_nada(conn):
    migrate(conn)
    migrate(conn)
    assert schema_version(conn) == len(MIGRATIONS)
    assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 11


def test_aplica_so_as_migracoes_pendentes_em_ordem(conn):
    calls = []

    def v2(c):
        calls.append(2)
        c.execute("ALTER TABLE products ADD COLUMN cost_cents INTEGER")

    def v3(c):
        calls.append(3)
        c.execute("UPDATE products SET cost_cents = 0")

    migrate(conn)                                   # versão 1
    migrate(conn, MIGRATIONS + [v2, v3])
    migrate(conn, MIGRATIONS + [v2, v3])            # já está em dia: não roda de novo

    assert calls == [2, 3]
    assert schema_version(conn) == len(MIGRATIONS) + 2
    assert "cost_cents" in [r[1] for r in conn.execute("PRAGMA table_info(products)")]


def test_migracao_com_erro_nao_deixa_nada_pela_metade(conn):
    migrate(conn)

    def quebrada(c):
        c.execute("CREATE TABLE suppliers (id INTEGER PRIMARY KEY)")
        raise RuntimeError("falhou no meio")

    with pytest.raises(RuntimeError):
        migrate(conn, MIGRATIONS + [quebrada])

    assert schema_version(conn) == len(MIGRATIONS)
    assert "suppliers" not in tables(conn)


def test_recusa_banco_de_versao_mais_nova(conn):
    migrate(conn)
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")

    with pytest.raises(SchemaTooNewError):
        migrate(conn)

    assert schema_version(conn) == len(MIGRATIONS) + 1


def test_init_db_migra_o_banco_do_sistema(tmp_path, monkeypatch):
    path = tmp_path / "estoque.db"
    legacy = sqlite3.connect(path)
    legacy.executescript(LEGACY_SCHEMA)
    legacy.close()
    monkeypatch.setattr(appmod, "DB_PATH", str(path))

    appmod.init_db()

    c = sqlite3.connect(path)
    assert schema_version(c) == len(migrations.MIGRATIONS)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("SELECT qty FROM products").fetchone()[0] == 7
    c.close()

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


def v1_with_products(conn, *barcodes):
    migrate(conn, MIGRATIONS[:1])
    conn.executemany("INSERT INTO products(barcode, name, created_at) VALUES (?, ?, '2026-11-10 10:00:00')",
                     [(b, f"Peça {i}") for i, b in enumerate(barcodes, start=1)])
    conn.commit()


def test_v2_grava_codigos_upc_a_com_13_digitos(conn):
    v1_with_products(conn, "036000291452", "7891234567895", "ABC-12345678", "12345670", None)

    migrate(conn)

    assert schema_version(conn) == len(MIGRATIONS)
    assert [r[0] for r in conn.execute("SELECT barcode FROM products ORDER BY id")] == [
        "0036000291452", "7891234567895", "ABC-12345678", "12345670", None]


def test_v2_para_e_avisa_se_o_upc_a_e_o_ean_13_ja_sao_pecas_diferentes(conn):
    v1_with_products(conn, "036000291452", "0036000291452")

    with pytest.raises(RuntimeError, match="Peça 1.*Peça 2"):
        migrate(conn)

    assert schema_version(conn) == 1
    assert [r[0] for r in conn.execute("SELECT barcode FROM products ORDER BY id")] == [
        "036000291452", "0036000291452"]


def columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_v3_tira_movements_qty_sem_perder_o_historico(conn):
    migrate(conn, MIGRATIONS[:2])
    conn.execute("INSERT INTO products(barcode, name, qty, created_at) VALUES ('1', 'Filtro', 4, '2026-11-10 10:00:00')")
    conn.executemany("""INSERT INTO movements(product_id, type, qty, delta, balance, created_at)
                        VALUES (1, ?, ?, ?, ?, '2026-11-10 10:00:00')""",
                     [("in", 7, 7, 7), ("out", 2, -2, 5), ("adjust", 4, -1, 4)])
    conn.commit()

    migrate(conn)

    assert schema_version(conn) == len(MIGRATIONS)
    assert "qty" not in columns(conn, "movements")
    assert conn.execute("SELECT type, delta, balance FROM movements ORDER BY id").fetchall() == [
        ("in", 7, 7), ("out", -2, 5), ("adjust", -1, 4)]


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


def test_v4_cria_o_identificador_unico_do_pedido(conn):
    migrate(conn, MIGRATIONS[:3])
    conn.execute("INSERT INTO products(barcode, name, qty, created_at) VALUES ('1', 'Filtro', 4, '2026-11-10 10:00:00')")
    conn.execute("""INSERT INTO movements(product_id, type, delta, balance, created_at)
                    VALUES (1, 'in', 4, 4, '2026-11-10 10:00:00')""")
    conn.commit()

    migrate(conn)

    assert schema_version(conn) == len(MIGRATIONS)
    assert conn.execute("SELECT request_id FROM movements").fetchall() == [(None,)]
    insert = "INSERT INTO movements(product_id, type, delta, balance, request_id, created_at) VALUES (1, 'in', 1, 5, ?, 'x')"
    conn.execute(insert, ("pedido-1",))
    conn.execute(insert, (None,))
    conn.execute(insert, (None,))                    # vários movimentos sem identificador continuam valendo
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("pedido-1",))

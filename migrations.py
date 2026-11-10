"""Migrações do banco: cada mudança de esquema é um passo numerado.

A versão do banco fica em PRAGMA user_version (0 = banco novo ou criado antes deste módulo).
Ao abrir, o sistema aplica em ordem só os passos que faltam, cada um em uma transação junto
com a troca de versão: se um passo falha, o banco fica exatamente como estava.

Para mudar o esquema, acrescente uma função ao fim de MIGRATIONS. Nunca altere, remova nem
reordene um passo que já foi para a oficina: ele já rodou lá e não vai rodar de novo.
"""

_INITIAL_TABLES = [
    """CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'atendente',
      active INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS categories (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE
    )""",
    """CREATE TABLE IF NOT EXISTS products (
      id INTEGER PRIMARY KEY,
      barcode TEXT UNIQUE,
      code TEXT,                       -- codigo/referencia do fabricante
      name TEXT NOT NULL,
      category_id INTEGER REFERENCES categories(id),
      ncm TEXT, brand TEXT,
      qty INTEGER NOT NULL DEFAULT 0 CHECK (qty >= 0),
      min_qty INTEGER,                 -- NULL = usa o minimo padrao
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS movements (
      id INTEGER PRIMARY KEY,
      product_id INTEGER NOT NULL REFERENCES products(id),
      type TEXT NOT NULL CHECK (type IN ('in','out','adjust')),
      qty INTEGER NOT NULL,            -- sempre positivo; 'adjust' guarda a diferenca em delta
      delta INTEGER NOT NULL,
      balance INTEGER NOT NULL,
      note TEXT, user_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL
    )""",
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_mov_product ON movements(product_id, id DESC)",
]

_SEED_CATEGORIES = [
    "Filtro de cabine", "Válvula", "Compressor", "Condensador", "Evaporador",
    "Mangueira", "Gás refrigerante", "Óleo", "Sensor", "Correia", "Outros",
]


def _v1_initial_schema(conn):
    """Esquema da primeira versão. Usa IF NOT EXISTS porque os bancos criados antes das
    migrações (versão 0) já têm essas tabelas, com dados que precisam ficar intactos."""
    for statement in _INITIAL_TABLES:
        conn.execute(statement)
    if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        conn.executemany("INSERT INTO categories(name) VALUES (?)", [(c,) for c in _SEED_CATEGORIES])
    conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('min_default', '2')")


def _is_upc_a(column):
    return f"length({column}) = 12 AND {column} NOT GLOB '*[^0-9]*'"


def _v2_upc_a_to_ean_13(conn):
    """Grava os códigos UPC-A (12 dígitos) como EAN-13, com um 0 na frente, que é como o leitor
    USB costuma mandar. A regra fica escrita aqui, e não importada do app, para este passo nunca
    mudar depois de rodar na oficina."""
    clashes = conn.execute(f"""
        SELECT upc.name, ean.name, ean.barcode FROM products upc
        JOIN products ean ON ean.barcode = '0' || upc.barcode
        WHERE {_is_upc_a('upc.barcode')}""").fetchall()
    if clashes:
        pairs = "; ".join(f"'{a}' e '{b}' (código {code})" for a, b, code in clashes)
        raise RuntimeError(
            "Estas peças têm o mesmo código de barras, uma com 12 e outra com 13 dígitos: "
            f"{pairs}. Na versão anterior do sistema, exclua uma delas e passe o estoque para a outra; "
            "depois atualize de novo.")
    conn.execute(f"UPDATE products SET barcode = '0' || barcode WHERE {_is_upc_a('barcode')}")


MIGRATIONS = [
    _v1_initial_schema,
    _v2_upc_a_to_ean_13,
]


class SchemaTooNewError(RuntimeError):
    """O banco foi atualizado por uma versão mais nova do sistema do que a que está rodando."""


def schema_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn, steps=MIGRATIONS):
    """Leva o banco até a última versão de `steps`, aplicando só os passos pendentes."""
    current = schema_version(conn)
    if current > len(steps):
        raise SchemaTooNewError(
            f"O banco está na versão {current}, mas este sistema só conhece até a {len(steps)}. "
            "Atualize o sistema antes de abrir este banco."
        )
    previous_isolation = conn.isolation_level
    conn.isolation_level = None  # transações explícitas: o sqlite3 não abre nem fecha nenhuma sozinho
    try:
        for number, step in enumerate(steps[current:], start=current + 1):
            conn.execute("BEGIN IMMEDIATE")
            try:
                step(conn)
                conn.execute(f"PRAGMA user_version = {number:d}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.isolation_level = previous_isolation

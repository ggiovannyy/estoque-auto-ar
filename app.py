"""Maxx Auto Ar - Sistema de Estoque.

Backend Flask + SQLite. Toda a interface fica em /static (mobile-first).
"""
import csv
import io
import math
import os
import secrets
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, Response, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from backup import DEFAULT_KEEP, default_backup_dir, last_backup_at, make_backup, prune_backups
from security import SECURITY_HEADERS, LoginThrottle, csv_safe, password_error

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("MAXX_DATA", os.path.join(BASE, "data"))
os.makedirs(DATA, exist_ok=True)
DB_PATH = os.path.join(DATA, "estoque.db")

DEFAULT_MIN = 2  # aviso de estoque baixo: quantidade <= 2 (configuravel)

# O primeiro acesso cria o dono: so pode ser feito no computador onde o sistema roda,
# para ninguem no Wi-Fi da oficina se cadastrar como dono antes dele.
LOCAL_ADDRESSES = {"127.0.0.1", "::1"}

user_throttle = LoginThrottle(max_failures=5)   # por IP + usuario
ip_throttle = LoginThrottle(max_failures=20)    # por IP, em qualquer usuario

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'atendente',
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS products (
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
);
CREATE TABLE IF NOT EXISTS movements (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id),
  type TEXT NOT NULL CHECK (type IN ('in','out','adjust')),
  qty INTEGER NOT NULL,            -- sempre positivo; 'adjust' guarda a diferenca em delta
  delta INTEGER NOT NULL,
  balance INTEGER NOT NULL,
  note TEXT, user_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_mov_product ON movements(product_id, id DESC);
"""

SEED_CATEGORIES = [
    "Filtro de cabine", "Válvula", "Compressor", "Condensador", "Evaporador",
    "Mangueira", "Gás refrigerante", "Óleo", "Sensor", "Correia", "Outros",
]


def get_secret():
    path = os.path.join(DATA, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    with open(path) as f:
        return f.read().strip()


app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = get_secret()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
                  BACKUP_DIR=str(default_backup_dir(DATA)))


def db():
    if "db" not in g:
        # timeout: quem chega enquanto outro grava espera em vez de falhar com "database is locked"
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")  # leituras nao bloqueiam durante uma gravacao
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        conn.executemany("INSERT INTO categories(name) VALUES (?)", [(c,) for c in SEED_CATEGORIES])
    conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('min_default', ?)", (str(DEFAULT_MIN),))
    conn.commit()
    conn.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def min_default():
    row = db().execute("SELECT value FROM settings WHERE key='min_default'").fetchone()
    return int(row["value"]) if row else DEFAULT_MIN


def err(msg, code=400):
    return jsonify(error=msg), code


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    u = db().execute("SELECT id,name,username,role,active FROM users WHERE id=?", (uid,)).fetchone()
    return u if u and u["active"] else None


def login_required(owner=False):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                return err("Faça login para continuar.", 401)
            if owner and u["role"] != "dono":
                return err("Apenas o dono pode fazer isso.", 403)
            g.user = u
            return fn(*a, **kw)
        return wrapper
    return deco


PRODUCT_SQL = """
SELECT p.*, c.name AS category,
       COALESCE(p.min_qty, :dmin) AS min_effective,
       (p.qty <= COALESCE(p.min_qty, :dmin)) AS low
FROM products p LEFT JOIN categories c ON c.id = p.category_id
"""


def product_dict(row):
    d = dict(row)
    d["low"] = bool(d["low"])
    return d


def clean(v):
    v = (v or "").strip() if isinstance(v, str) else v
    return v or None


def to_int(v, default=None, minimum=0):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if n >= minimum else default


# ---------------------------------------------------------------- pages
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(app.static_folder, "manifest.webmanifest",
                               mimetype="application/manifest+json")


@app.after_request
def add_response_headers(resp):
    resp.headers.update(SECURITY_HEADERS)
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------- auth
@app.get("/api/state")
def state():
    users = db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
    u = current_user()
    return jsonify(setup_needed=users == 0,
                   setup_here=request.remote_addr in LOCAL_ADDRESSES,
                   user=dict(u) if u else None,
                   min_default=min_default())


@app.post("/api/setup")
def setup():
    if db().execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return err("O sistema já foi configurado.", 403)
    if request.remote_addr not in LOCAL_ADDRESSES:
        return err("Faça o primeiro acesso no computador onde o sistema está instalado.", 403)
    d = request.get_json(silent=True) or {}
    name, username, pw = clean(d.get("name")), clean(d.get("username")), d.get("password") or ""
    if not (name and username):
        return err("Informe nome e usuário.")
    if error := password_error(pw):
        return err(error)
    cur = db().execute("INSERT INTO users(name,username,password_hash,role) VALUES (?,?,?,'dono')",
                       (name, username.lower(), generate_password_hash(pw)))
    db().commit()
    session.permanent = True
    session["uid"] = cur.lastrowid
    return jsonify(ok=True)


@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip().lower()
    ip, user_key = request.remote_addr, (request.remote_addr, username)
    wait = max(ip_throttle.retry_after(ip), user_throttle.retry_after(user_key))
    if wait:
        return err(f"Muitas tentativas de senha. Tente de novo em {math.ceil(wait / 60)} min.", 429)
    u = db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not u or not u["active"] or not check_password_hash(u["password_hash"], d.get("password") or ""):
        ip_throttle.failure(ip)
        user_throttle.failure(user_key)
        return err("Usuário ou senha incorretos.", 401)
    user_throttle.success(user_key)
    session.permanent = True
    session["uid"] = u["id"]
    return jsonify(ok=True)


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


# ---------------------------------------------------------------- categories
@app.get("/api/categories")
@login_required()
def categories():
    rows = db().execute("""SELECT c.id, c.name, COUNT(p.id) AS products
                           FROM categories c LEFT JOIN products p ON p.category_id=c.id AND p.active=1
                           GROUP BY c.id ORDER BY c.name""").fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/categories")
@login_required()
def add_category():
    name = clean((request.get_json(silent=True) or {}).get("name"))
    if not name:
        return err("Informe o nome da categoria.")
    try:
        cur = db().execute("INSERT INTO categories(name) VALUES (?)", (name,))
        db().commit()
    except sqlite3.IntegrityError:
        return err("Essa categoria já existe.")
    return jsonify(id=cur.lastrowid, name=name)


@app.delete("/api/categories/<int:cid>")
@login_required(owner=True)
def del_category(cid):
    if db().execute("SELECT 1 FROM products WHERE category_id=? AND active=1", (cid,)).fetchone():
        return err("Há peças nessa categoria. Mova-as antes de excluir.")
    db().execute("UPDATE products SET category_id=NULL WHERE category_id=?", (cid,))
    db().execute("DELETE FROM categories WHERE id=?", (cid,))
    db().commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- products
@app.get("/api/products")
@login_required()
def products():
    where, args = ["p.active=1"], {"dmin": min_default()}
    q = clean(request.args.get("q"))
    if q:
        where.append("(p.name LIKE :q OR p.code LIKE :q OR p.barcode LIKE :q OR p.brand LIKE :q OR p.ncm LIKE :q)")
        args["q"] = f"%{q}%"
    cat = to_int(request.args.get("category"))
    if cat:
        where.append("p.category_id = :cat")
        args["cat"] = cat
    sql = PRODUCT_SQL + " WHERE " + " AND ".join(where)
    if request.args.get("low") == "1":
        sql = f"SELECT * FROM ({sql}) WHERE low=1"
        sql += " ORDER BY qty, name COLLATE NOCASE"
    else:
        sql += " ORDER BY c.name COLLATE NOCASE, p.name COLLATE NOCASE"
    rows = db().execute(sql, args).fetchall()
    return jsonify([product_dict(r) for r in rows])


def fetch_product(pid=None, barcode=None):
    sql = PRODUCT_SQL + (" WHERE p.id=:k" if pid else " WHERE p.barcode=:k") + " AND p.active=1"
    return db().execute(sql, {"dmin": min_default(), "k": pid or barcode}).fetchone()


@app.get("/api/products/barcode/<path:code>")
@login_required()
def by_barcode(code):
    r = fetch_product(barcode=code.strip())
    if not r:
        return err("Peça não cadastrada.", 404)
    return jsonify(product_dict(r))


@app.get("/api/products/<int:pid>")
@login_required()
def product_detail(pid):
    r = fetch_product(pid=pid)
    if not r:
        return err("Peça não encontrada.", 404)
    moves = db().execute("""SELECT m.*, u.name AS user FROM movements m
                            LEFT JOIN users u ON u.id=m.user_id
                            WHERE m.product_id=? ORDER BY m.id DESC LIMIT 15""", (pid,)).fetchall()
    d = product_dict(r)
    d["movements"] = [dict(m) for m in moves]
    return jsonify(d)


def read_product_fields(d):
    name = clean(d.get("name"))
    if not name:
        return None, "Informe o nome da peça."
    min_raw = d.get("min_qty")
    return {
        "barcode": clean(d.get("barcode")),
        "code": clean(d.get("code")),
        "name": name,
        "category_id": to_int(d.get("category_id")),
        "ncm": clean(d.get("ncm")),
        "brand": clean(d.get("brand")),
        "min_qty": to_int(min_raw) if min_raw not in (None, "") else None,
    }, None


def record_move(pid, mtype, qty, note, uid):
    """Aplica uma movimentacao. Retorna (saldo, erro).

    Precisa rodar dentro de uma transacao de escrita ja aberta (BEGIN IMMEDIATE,
    ou depois de um INSERT na mesma transacao): assim nenhum outro atendente
    altera o saldo entre a leitura abaixo e a gravacao.
    """
    conn = db()
    assert conn.in_transaction, "record_move exige uma transacao de escrita aberta"
    row = conn.execute("SELECT qty FROM products WHERE id=? AND active=1", (pid,)).fetchone()
    if not row:
        return None, "Peça não encontrada."
    cur = row["qty"]
    if mtype == "in":
        delta = qty
    elif mtype == "out":
        if qty > cur:
            return None, f"Estoque insuficiente: há apenas {cur} em estoque."
        delta = -qty
    else:  # adjust: qty = nova contagem
        delta = qty - cur
    new = cur + delta
    conn.execute("UPDATE products SET qty=? WHERE id=?", (new, pid))
    conn.execute("""INSERT INTO movements(product_id,type,qty,delta,balance,note,user_id,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""", (pid, mtype, abs(delta) if mtype != "adjust" else qty,
                                                    delta, new, note, uid, now()))
    return new, None


@app.post("/api/products")
@login_required()
def create_product():
    d = request.get_json(silent=True) or {}
    f, e = read_product_fields(d)
    if e:
        return err(e)
    initial = to_int(d.get("qty"), 0)
    try:
        cur = db().execute("""INSERT INTO products(barcode,code,name,category_id,ncm,brand,qty,min_qty,created_at)
                              VALUES (:barcode,:code,:name,:category_id,:ncm,:brand,0,:min_qty,:now)""",
                           {**f, "now": now()})
        pid = cur.lastrowid
        if initial:
            record_move(pid, "in", initial, "Estoque inicial", g.user["id"])
        db().commit()
    except sqlite3.IntegrityError:
        db().rollback()
        return err("Já existe uma peça com esse código de barras.")
    return jsonify(product_dict(fetch_product(pid=pid))), 201


@app.put("/api/products/<int:pid>")
@login_required()
def update_product(pid):
    f, e = read_product_fields(request.get_json(silent=True) or {})
    if e:
        return err(e)
    try:
        db().execute("""UPDATE products SET barcode=:barcode, code=:code, name=:name, category_id=:category_id,
                        ncm=:ncm, brand=:brand, min_qty=:min_qty WHERE id=:id AND active=1""", {**f, "id": pid})
        db().commit()
    except sqlite3.IntegrityError:
        return err("Já existe outra peça com esse código de barras.")
    r = fetch_product(pid=pid)
    return jsonify(product_dict(r)) if r else err("Peça não encontrada.", 404)


@app.delete("/api/products/<int:pid>")
@login_required(owner=True)
def delete_product(pid):
    # Exclusao logica: o historico de movimentacoes continua valido.
    db().execute("UPDATE products SET active=0, barcode=NULL WHERE id=?", (pid,))
    db().commit()
    return jsonify(ok=True)


@app.post("/api/products/<int:pid>/move")
@login_required()
def move(pid):
    d = request.get_json(silent=True) or {}
    mtype = d.get("type")
    if mtype not in ("in", "out", "adjust"):
        return err("Tipo de movimentação inválido.")
    qty = to_int(d.get("qty"), None, 0 if mtype == "adjust" else 1)
    if qty is None:
        return err("Informe uma quantidade válida.")
    db().execute("BEGIN IMMEDIATE")  # trava escritas concorrentes ate o commit
    new, e = record_move(pid, mtype, qty, clean(d.get("note")), g.user["id"])
    if e:
        db().rollback()
        return err(e)
    db().commit()
    return jsonify(product_dict(fetch_product(pid=pid)))


# ---------------------------------------------------------------- reports
@app.get("/api/summary")
@login_required()
def summary():
    r = db().execute("""SELECT COUNT(*) AS items, COALESCE(SUM(qty),0) AS units,
                        COALESCE(SUM(qty <= COALESCE(min_qty, :d)),0) AS low,
                        COALESCE(SUM(qty = 0),0) AS empty
                        FROM products WHERE active=1""", {"d": min_default()}).fetchone()
    return jsonify(dict(r))


@app.get("/api/movements")
@login_required()
def movements():
    limit = min(to_int(request.args.get("limit"), 100, 1) or 100, 500)
    rows = db().execute("""SELECT m.*, p.name AS product, p.code, u.name AS user
                           FROM movements m JOIN products p ON p.id=m.product_id
                           LEFT JOIN users u ON u.id=m.user_id
                           ORDER BY m.id DESC LIMIT ?""", (limit,)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/export.csv")
@login_required()
def export_csv():
    rows = db().execute(PRODUCT_SQL + " WHERE p.active=1 ORDER BY c.name, p.name",
                        {"dmin": min_default()}).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Categoria", "Nome", "Código", "Código de barras", "NCM", "Marca", "Quantidade", "Mínimo", "Situação"])
    for r in rows:
        w.writerow([csv_safe(v) for v in (
            r["category"] or "", r["name"], r["code"] or "", r["barcode"] or "", r["ncm"] or "",
            r["brand"] or "", r["qty"], r["min_effective"], "BAIXO" if r["low"] else "ok")])
    out = "\ufeff" + buf.getvalue()  # BOM para o Excel abrir com acentos
    return Response(out, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=estoque-{datetime.now():%Y-%m-%d}.csv"})


# ---------------------------------------------------------------- settings / users
@app.put("/api/settings")
@login_required(owner=True)
def set_settings():
    n = to_int((request.get_json(silent=True) or {}).get("min_default"))
    if n is None:
        return err("Informe um número válido.")
    db().execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('min_default', ?)", (str(n),))
    db().commit()
    return jsonify(min_default=n)


def backup_status():
    last = last_backup_at(app.config["BACKUP_DIR"])
    return {"dir": app.config["BACKUP_DIR"], "last_at": last.strftime("%Y-%m-%d %H:%M:%S") if last else None}


@app.get("/api/backup")
@login_required(owner=True)
def get_backup():
    return jsonify(backup_status())


@app.post("/api/backup")
@login_required(owner=True)
def backup_now():
    try:
        make_backup(DB_PATH, app.config["BACKUP_DIR"])
        prune_backups(app.config["BACKUP_DIR"], DEFAULT_KEEP)
    except (OSError, sqlite3.Error) as e:
        return err(f"Não foi possível salvar o backup: {e}", 500)
    return jsonify(backup_status())


@app.get("/api/users")
@login_required(owner=True)
def users():
    rows = db().execute("SELECT id,name,username,role,active FROM users ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/users")
@login_required(owner=True)
def add_user():
    d = request.get_json(silent=True) or {}
    name, username, pw = clean(d.get("name")), clean(d.get("username")), d.get("password") or ""
    role = "dono" if d.get("role") == "dono" else "atendente"
    if not (name and username):
        return err("Informe nome e usuário.")
    if error := password_error(pw):
        return err(error)
    try:
        db().execute("INSERT INTO users(name,username,password_hash,role) VALUES (?,?,?,?)",
                     (name, username.lower(), generate_password_hash(pw), role))
        db().commit()
    except sqlite3.IntegrityError:
        return err("Esse usuário já existe.")
    return jsonify(ok=True), 201


@app.put("/api/users/<int:uid>")
@login_required(owner=True)
def edit_user(uid):
    d = request.get_json(silent=True) or {}
    if "active" in d:
        if uid == g.user["id"] and not d["active"]:
            return err("Você não pode desativar o próprio usuário.")
        db().execute("UPDATE users SET active=? WHERE id=?", (1 if d["active"] else 0, uid))
    if d.get("password"):
        if error := password_error(d["password"]):
            return err(error)
        db().execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(d["password"]), uid))
    db().commit()
    return jsonify(ok=True)


@app.post("/api/password")
@login_required()
def change_password():
    d = request.get_json(silent=True) or {}
    u = db().execute("SELECT password_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
    if not check_password_hash(u["password_hash"], d.get("current") or ""):
        return err("Senha atual incorreta.")
    if error := password_error(d.get("new")):
        return err(error)
    db().execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(d["new"]), g.user["id"]))
    db().commit()
    return jsonify(ok=True)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)

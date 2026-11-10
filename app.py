"""Maxx Auto Ar - Sistema de Estoque.

Backend Flask + SQLite. Toda a interface fica em /static (mobile-first).
"""
import csv
import hmac
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
from migrations import migrate
from paths import DATA, DB_PATH
from security import SECURITY_HEADERS, LoginThrottle, csv_safe, password_error, password_mark

os.makedirs(DATA, exist_ok=True)

DEFAULT_MIN = 2  # aviso de estoque baixo: quantidade <= 2 (configuravel)
# Teto de quantidade: o leitor USB "digita" o codigo de barras e um Enter no campo em foco, inclusive no de quantidade.
MAX_QTY = 100_000
QTY_HINT = "Se o leitor estava no campo de quantidade, o código de barras pode ter entrado ali."

# O primeiro acesso cria o dono: so pode ser feito no computador onde o sistema roda,
# para ninguem no Wi-Fi da oficina se cadastrar como dono antes dele.
LOCAL_ADDRESSES = {"127.0.0.1", "::1"}

user_throttle = LoginThrottle(max_failures=5)   # por IP + usuario
ip_throttle = LoginThrottle(max_failures=20)    # por IP, em qualquer usuario


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
    try:
        conn.execute("PRAGMA journal_mode=WAL")  # leituras nao bloqueiam durante uma gravacao
        migrate(conn)
    finally:
        conn.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def min_default():
    row = db().execute("SELECT value FROM settings WHERE key='min_default'").fetchone()
    return int(row["value"]) if row else DEFAULT_MIN


def err(msg, code=400):
    return jsonify(error=msg), code


USER_FIELDS = ("id", "name", "username", "role", "active")


def start_session(user_id, password_hash):
    session.clear()
    session.permanent = True
    session["uid"] = user_id
    session["pw"] = password_mark(password_hash)


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    u = db().execute("SELECT id,name,username,role,active,password_hash FROM users WHERE id=?", (uid,)).fetchone()
    if not u or not u["active"] or not hmac.compare_digest(session.get("pw", ""), password_mark(u["password_hash"])):
        return None
    return {k: u[k] for k in USER_FIELDS}


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


def normalize_barcode(v):
    """A câmera pode ler um UPC-A (12 dígitos) e o leitor USB o mesmo código como EAN-13 (com um 0
    na frente). Grava e busca sempre com 13 dígitos para os dois acharem a mesma peça."""
    code = clean(v)
    if code and len(code) == 12 and code.isascii() and code.isdigit():
        return "0" + code
    return code


def to_int(v, default=None, minimum=0, maximum=None):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if n >= minimum and (maximum is None or n <= maximum) else default


def read_min(v):
    """Mínimo para o alerta: (valor, erro)."""
    n = to_int(v, maximum=MAX_QTY)
    return (n, None) if n is not None else (None, f"Mínimo inválido: informe um número inteiro de 0 a {MAX_QTY}.")


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
                   user=u,
                   min_default=min_default())


def users_exist():
    return db().execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


@app.post("/api/setup")
def setup():
    if users_exist():
        return err("O sistema já foi configurado.", 403)
    if request.remote_addr not in LOCAL_ADDRESSES:
        return err("Faça o primeiro acesso no computador onde o sistema está instalado.", 403)
    d = request.get_json(silent=True) or {}
    name, username, pw = clean(d.get("name")), clean(d.get("username")), d.get("password") or ""
    if not (name and username):
        return err("Informe nome e usuário.")
    if error := password_error(pw):
        return err(error)
    pw_hash = generate_password_hash(pw)
    db().execute("BEGIN IMMEDIATE")  # dois primeiros acessos ao mesmo tempo: o segundo espera e é recusado
    if users_exist():
        db().rollback()
        return err("O sistema já foi configurado.", 403)
    cur = db().execute("INSERT INTO users(name,username,password_hash,role) VALUES (?,?,?,'dono')",
                       (name, username.lower(), pw_hash))
    db().commit()
    start_session(cur.lastrowid, pw_hash)
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
    start_session(u["id"], u["password_hash"])
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
    db().execute("BEGIN IMMEDIATE")  # ninguém cadastra peça nessa categoria enquanto ela é excluída
    db().execute("UPDATE products SET category_id=NULL WHERE category_id=? AND active=0", (cid,))
    try:
        db().execute("DELETE FROM categories WHERE id=?", (cid,))
    except sqlite3.IntegrityError:  # chave estrangeira: ainda há peça ativa nela
        db().rollback()
        return err("Há peças nessa categoria. Mova-as antes de excluir.")
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
        sql += " ORDER BY c.name COLLATE NOCASE, p.name COLLATE NOCASE, p.id"
    limit = to_int(request.args.get("limit"), minimum=1)
    if limit:  # a tela pede de página em página; sem limit vem a lista inteira
        sql += " LIMIT :limit OFFSET :offset"
        args.update(limit=limit, offset=to_int(request.args.get("offset"), 0))
    rows = db().execute(sql, args).fetchall()
    return jsonify([product_dict(r) for r in rows])


def fetch_product(pid=None, barcode=None):
    sql = PRODUCT_SQL + (" WHERE p.id=:k" if pid else " WHERE p.barcode=:k") + " AND p.active=1"
    return db().execute(sql, {"dmin": min_default(), "k": pid or barcode}).fetchone()


@app.get("/api/products/barcode/<path:code>")
@login_required()
def by_barcode(code):
    r = fetch_product(barcode=normalize_barcode(code))
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
    min_qty, error = read_min(d["min_qty"]) if d.get("min_qty") not in (None, "") else (None, None)
    if error:
        return None, error
    return {
        "barcode": normalize_barcode(d.get("barcode")),
        "code": clean(d.get("code")),
        "name": name,
        "category_id": to_int(d.get("category_id")),
        "ncm": clean(d.get("ncm")),
        "brand": clean(d.get("brand")),
        "min_qty": min_qty,
    }, None


def record_move(pid, mtype, qty, note, uid, request_id=None):
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
    if new > MAX_QTY:
        return None, f"O estoque passaria de {MAX_QTY} unidades. {QTY_HINT}"
    conn.execute("UPDATE products SET qty=? WHERE id=?", (new, pid))
    conn.execute("""INSERT INTO movements(product_id,type,delta,balance,note,user_id,request_id,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""", (pid, mtype, delta, new, note, uid, request_id, now()))
    return new, None


@app.post("/api/products")
@login_required()
def create_product():
    d = request.get_json(silent=True) or {}
    f, e = read_product_fields(d)
    if e:
        return err(e)
    qty_raw = d.get("qty")
    initial = 0 if qty_raw in (None, "") else to_int(qty_raw, maximum=MAX_QTY)
    if initial is None:
        return err(f"Quantidade inicial inválida: informe um número inteiro de 0 a {MAX_QTY}. {QTY_HINT}")
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
    if mtype == "adjust" and g.user["role"] != "dono":  # a contagem define o saldo direto, sem venda nem compra
        return err("Apenas o dono pode fazer a contagem.", 403)
    qty = to_int(d.get("qty"), None, 0 if mtype == "adjust" else 1, MAX_QTY)
    if qty is None:
        return err(f"Informe uma quantidade válida, até {MAX_QTY}. {QTY_HINT}")
    request_id = d.get("request_id")  # gerado pela tela: o mesmo pedido reenviado não grava de novo
    if request_id is not None and not (isinstance(request_id, str) and 0 < len(request_id) <= 64):
        return err("Identificador do pedido inválido.")
    expected = None  # na contagem: o saldo que o dono via ao contar
    if mtype == "adjust" and d.get("expected") is not None:
        expected = to_int(d["expected"], maximum=MAX_QTY)
        if expected is None:
            return err("Saldo anterior inválido.")
    db().execute("BEGIN IMMEDIATE")  # trava escritas concorrentes ate o commit
    if request_id and db().execute("SELECT 1 FROM movements WHERE request_id=?", (request_id,)).fetchone():
        db().rollback()  # reenvio de um pedido já gravado: responde com a peça como está
        return jsonify(product_dict(fetch_product(pid=pid)))
    if expected is not None:
        row = db().execute("SELECT qty FROM products WHERE id=? AND active=1", (pid,)).fetchone()
        if row and row["qty"] != expected:  # vendeu ou entrou peça enquanto se contava: a contagem apagaria isso
            db().rollback()
            return jsonify(error=f"O estoque mudou de {expected} para {row['qty']} enquanto você contava. "
                                 "Confira e salve de novo.", qty=row["qty"]), 409
    new, e = record_move(pid, mtype, qty, clean(d.get("note")), g.user["id"], request_id)
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
    n, error = read_min((request.get_json(silent=True) or {}).get("min_default"))
    if error:
        return err(error)
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
    deactivate = "active" in d and not d["active"]
    if deactivate and uid == g.user["id"]:
        return err("Você não pode desativar o próprio usuário.")
    pw_hash = None
    if d.get("password"):
        if error := password_error(d["password"]):
            return err(error)
        pw_hash = generate_password_hash(d["password"])
    db().execute("BEGIN IMMEDIATE")  # dois donos mexendo ao mesmo tempo: um espera o outro
    if deactivate and not db().execute("SELECT 1 FROM users WHERE role='dono' AND active=1 AND id<>?",
                                       (uid,)).fetchone():
        db().rollback()
        return err("O sistema precisa de ao menos um dono ativo.")
    if "active" in d:
        db().execute("UPDATE users SET active=? WHERE id=?", (0 if deactivate else 1, uid))
    if pw_hash:
        db().execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, uid))
        if uid == g.user["id"]:
            session["pw"] = password_mark(pw_hash)  # quem redefiniu a propria senha continua logado aqui
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
    pw_hash = generate_password_hash(d["new"])
    db().execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, g.user["id"]))
    db().commit()
    session["pw"] = password_mark(pw_hash)  # este aparelho continua logado; os outros saem
    return jsonify(ok=True)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)

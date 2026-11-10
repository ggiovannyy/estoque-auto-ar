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
from werkzeug.exceptions import HTTPException, InternalServerError, RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash

from backup import DEFAULT_KEEP, default_backup_dir, last_backup_at, make_backup, prune_backups
from inputs import (MAX_NOTE, MAX_QTY, QTY_HINT, BadInput, clean, json_body, normalize_barcode, read_min, secret,
                    text, to_int)
from migrations import migrate
from paths import DATA, DB_PATH
from security import SECURITY_HEADERS, LoginThrottle, csv_safe, password_error, password_mark

os.makedirs(DATA, exist_ok=True)

DEFAULT_MIN = 2  # aviso de estoque baixo: quantidade <= 2 (configuravel)

# O primeiro acesso cria o dono: so pode ser feito no computador onde o sistema roda,
# para ninguem no Wi-Fi da oficina se cadastrar como dono antes dele.
LOCAL_ADDRESSES = {"127.0.0.1", "::1"}

user_throttle = LoginThrottle(max_failures=5)   # por IP + usuario (e por usuario logado, na troca de senha)
ip_throttle = LoginThrottle(max_failures=20)    # por IP, em qualquer usuario
# Usuario que nao existe tambem passa pelo calculo do hash: sem isso a resposta sai bem mais rapido e revela
# quais usuarios existem.
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_hex(16))


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
                  MAX_CONTENT_LENGTH=64 * 1024,  # a maior requisição da tela tem poucas centenas de bytes
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


@app.errorhandler(BadInput)
def bad_input(e):
    return err(str(e))


@app.errorhandler(RequestEntityTooLarge)
def too_large(_):
    return err("Os dados enviados são grandes demais.", 413)


@app.errorhandler(InternalServerError)
def internal_error(_):
    # O Flask já registrou o traceback no log; quem usa o sistema vê só uma mensagem genérica.
    return err("Erro inesperado no servidor. Tente de novo; se continuar, avise o responsável.", 500)


API_HTTP_ERRORS = {404: "Endereço não encontrado.", 405: "Método não permitido."}


@app.errorhandler(HTTPException)
def http_error(e):
    """Na API, os erros do próprio Flask (rota inexistente, método errado...) também respondem em JSON."""
    if request.path.startswith("/api/"):
        return err(API_HTTP_ERRORS.get(e.code, "Requisição inválida."), e.code)
    return e


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


def read_new_user(d):
    """Usuário novo (primeiro acesso ou cadastro pelo dono): ((nome, usuário, hash da senha), erro)."""
    name, username, pw = text(d, "name"), text(d, "username"), secret(d, "password")
    if not (name and username):
        return None, "Informe nome e usuário."
    if error := password_error(pw):
        return None, error
    return (name, username.lower(), generate_password_hash(pw)), None


def users_exist():
    return db().execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


@app.post("/api/setup")
def setup():
    if users_exist():
        return err("O sistema já foi configurado.", 403)
    if request.remote_addr not in LOCAL_ADDRESSES:
        return err("Faça o primeiro acesso no computador onde o sistema está instalado.", 403)
    user, error = read_new_user(json_body())
    if error:
        return err(error)
    db().execute("BEGIN IMMEDIATE")  # dois primeiros acessos ao mesmo tempo: o segundo espera e é recusado
    if users_exist():
        db().rollback()
        return err("O sistema já foi configurado.", 403)
    cur = db().execute("INSERT INTO users(name,username,password_hash,role) VALUES (?,?,?,'dono')", user)
    db().commit()
    start_session(cur.lastrowid, user[2])
    return jsonify(ok=True)


def too_many_attempts(wait):
    return err(f"Muitas tentativas de senha. Tente de novo em {math.ceil(wait / 60)} min.", 429)


@app.post("/api/login")
def login():
    d = json_body()
    username = (text(d, "username") or "").lower()
    ip, user_key = request.remote_addr, (request.remote_addr, username)
    wait = max(ip_throttle.retry_after(ip), user_throttle.retry_after(user_key))
    if wait:
        return too_many_attempts(wait)
    u = db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    password_ok = check_password_hash(u["password_hash"] if u else DUMMY_PASSWORD_HASH, secret(d, "password"))
    if not u or not u["active"] or not password_ok:
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
    name = text(json_body(), "name")
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


def integrity_error(e, duplicate_msg):
    """Mensagem para o IntegrityError de cadastro/edição de peça: categoria que não existe ou código repetido."""
    return err("Categoria não encontrada." if "FOREIGN KEY" in str(e) else duplicate_msg)


def read_product_fields(d):
    name = text(d, "name")
    if not name:
        return None, "Informe o nome da peça."
    min_qty, error = read_min(d["min_qty"]) if d.get("min_qty") not in (None, "") else (None, None)
    if error:
        return None, error
    return {
        "barcode": normalize_barcode(text(d, "barcode")),
        "code": text(d, "code"),
        "name": name,
        "category_id": to_int(d.get("category_id")),
        "ncm": text(d, "ncm"),
        "brand": text(d, "brand"),
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
    d = json_body()
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
    except sqlite3.IntegrityError as e:
        db().rollback()
        return integrity_error(e, "Já existe uma peça com esse código de barras.")
    return jsonify(product_dict(fetch_product(pid=pid))), 201


@app.put("/api/products/<int:pid>")
@login_required()
def update_product(pid):
    f, e = read_product_fields(json_body())
    if e:
        return err(e)
    try:
        db().execute("""UPDATE products SET barcode=:barcode, code=:code, name=:name, category_id=:category_id,
                        ncm=:ncm, brand=:brand, min_qty=:min_qty WHERE id=:id AND active=1""", {**f, "id": pid})
        db().commit()
    except sqlite3.IntegrityError as e:
        db().rollback()
        return integrity_error(e, "Já existe outra peça com esse código de barras.")
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
    d = json_body()
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
    new, e = record_move(pid, mtype, qty, text(d, "note", MAX_NOTE), g.user["id"], request_id)
    if e:
        db().rollback()
        return err(e)
    db().commit()
    return jsonify(product_dict(fetch_product(pid=pid)))


MAX_BATCH = 500  # peças por lote: um dia de contagem cabe com folga


def read_batch_items(items, mtype):
    """Itens do lote: ([(product_id, qty, expected)], erro)."""
    if not isinstance(items, list) or not 0 < len(items) <= MAX_BATCH:
        return None, f"Informe de 1 a {MAX_BATCH} peças."
    out, seen = [], set()
    for it in items:
        it = it if isinstance(it, dict) else {}
        pid = to_int(it.get("product_id"), minimum=1)
        qty = to_int(it.get("qty"), None, 0 if mtype == "adjust" else 1, MAX_QTY)
        seen_qty = it.get("expected") if mtype == "adjust" else None  # na contagem: o saldo que o dono via
        expected = None if seen_qty is None else to_int(seen_qty, maximum=MAX_QTY)
        if pid is None or qty is None or (seen_qty is not None and expected is None):
            return None, f"Peça ou quantidade inválida no lote (até {MAX_QTY} por peça). {QTY_HINT}"
        if pid in seen:
            return None, "A mesma peça aparece duas vezes no lote."
        seen.add(pid)
        out.append((pid, qty, expected))
    return out, None


@app.post("/api/products/moves")
@login_required()
def move_batch():
    """Leitura contínua: entradas ou contagens de várias peças numa transação só (tudo ou nada)."""
    d = request.get_json(silent=True) or {}
    mtype = d.get("type")
    if mtype not in ("in", "adjust"):
        return err("Tipo de movimentação inválido para o lote.")
    if mtype == "adjust" and g.user["role"] != "dono":
        return err("Apenas o dono pode fazer a contagem.", 403)
    items, e = read_batch_items(d.get("items"), mtype)
    if e:
        return err(e)
    request_id = d.get("request_id")  # cada item grava "<id>#<n>": o índice único de movements aceita um por linha
    if request_id is not None and not (isinstance(request_id, str) and 0 < len(request_id) <= 60):
        return err("Identificador do pedido inválido.")
    ids = [pid for pid, _, _ in items]

    def products():
        return [product_dict(fetch_product(pid=pid)) for pid in ids]

    db().execute("BEGIN IMMEDIATE")  # trava escritas concorrentes ate o commit
    if request_id and db().execute("SELECT 1 FROM movements WHERE request_id=?", (f"{request_id}#0",)).fetchone():
        db().rollback()  # reenvio de um lote já gravado
        return jsonify(products=products())
    rows = db().execute(f"SELECT id, name, qty FROM products WHERE active=1 AND id IN ({','.join('?' * len(ids))})",
                        ids).fetchall()
    found = {r["id"]: r for r in rows}
    changed = [(found[pid], exp) for pid, _, exp in items if exp is not None and pid in found and found[pid]["qty"] != exp]
    if changed:  # vendeu ou entrou peça enquanto se contava: a contagem apagaria isso
        db().rollback()
        names = "; ".join(f"{r['name']} (de {exp} para {r['qty']})" for r, exp in changed)
        return jsonify(error=f"O estoque mudou enquanto você contava: {names}. Confira e salve de novo.",
                       changed=[{"product_id": r["id"], "qty": r["qty"]} for r, _ in changed]), 409
    note = clean(d.get("note"))
    for n, (pid, qty, _) in enumerate(items):
        _, e = record_move(pid, mtype, qty, note, g.user["id"], request_id and f"{request_id}#{n}")
        if e:
            db().rollback()
            return err(f"{found[pid]['name']}: {e}" if pid in found else e)
    db().commit()
    return jsonify(products=products())


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
    n, error = read_min(json_body().get("min_default"))
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
    d = json_body()
    user, error = read_new_user(d)
    if error:
        return err(error)
    role = "dono" if d.get("role") == "dono" else "atendente"
    try:
        db().execute("INSERT INTO users(name,username,password_hash,role) VALUES (?,?,?,?)", (*user, role))
        db().commit()
    except sqlite3.IntegrityError:
        return err("Esse usuário já existe.")
    return jsonify(ok=True), 201


@app.put("/api/users/<int:uid>")
@login_required(owner=True)
def edit_user(uid):
    d = json_body()
    if "active" in d and not isinstance(d["active"], bool):
        raise BadInput("O campo active precisa ser verdadeiro ou falso.")
    deactivate = d.get("active") is False
    new_pw = secret(d, "password")
    if deactivate and uid == g.user["id"]:
        return err("Você não pode desativar o próprio usuário.")
    pw_hash = None
    if new_pw:
        if error := password_error(new_pw):
            return err(error)
        pw_hash = generate_password_hash(new_pw)
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
    d = json_body()
    current, new_pw = secret(d, "current"), secret(d, "new")
    key = ("troca de senha", g.user["id"])  # com um cookie roubado, nao da para chutar a senha atual sem limite
    if wait := user_throttle.retry_after(key):
        return too_many_attempts(wait)
    u = db().execute("SELECT password_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
    if not check_password_hash(u["password_hash"], current):
        user_throttle.failure(key)
        return err("Senha atual incorreta.")
    user_throttle.success(key)
    if error := password_error(new_pw):
        return err(error)
    pw_hash = generate_password_hash(new_pw)
    db().execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, g.user["id"]))
    db().commit()
    session["pw"] = password_mark(pw_hash)  # este aparelho continua logado; os outros saem
    return jsonify(ok=True)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)

"""Leitura e validação dos dados que chegam nas requisições.

Tudo que vem de fora passa por aqui: texto com tamanho e tipo conferidos, números inteiros dentro dos limites e o
código de barras normalizado. Dado fora do formato vira BadInput, que o app responde como 400 com a mensagem.
"""
from flask import request

# Teto de quantidade: o leitor USB "digita" o codigo de barras e um Enter no campo em foco, inclusive no de quantidade.
MAX_QTY = 100_000
QTY_HINT = "Se o leitor estava no campo de quantidade, o código de barras pode ter entrado ali."


class BadInput(Exception):
    """Dados fora do formato (corpo que não é objeto, número no lugar de texto...): vira 400 com a mensagem."""


MAX_TEXT = 200  # nome, código, marca, usuário, senha...
MAX_NOTE = 500  # observação da movimentação


def json_body():
    """Corpo JSON da requisição como dicionário ({} se não houver corpo JSON)."""
    d = request.get_json(silent=True)
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise BadInput("Envie os dados como um objeto JSON.")
    return d


def _str_field(d, key, max_len):
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise BadInput(f"O campo {key} precisa ser texto.")
    if len(v) > max_len:
        raise BadInput(f"O campo {key} aceita no máximo {max_len} caracteres.")
    return v


def text(d, key, max_len=MAX_TEXT):
    """Campo de texto sem espaços nas pontas; None se vier vazio ou faltar."""
    v = _str_field(d, key, max_len)
    return None if v is None else (v.strip() or None)


def secret(d, key):
    """Senha como foi digitada (espaços contam); "" se faltar."""
    return _str_field(d, key, MAX_TEXT) or ""


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
    if isinstance(v, bool):  # em Python, True == 1: "qty": true não pode virar 1
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if n >= minimum and (maximum is None or n <= maximum) else default


def read_min(v):
    """Mínimo para o alerta: (valor, erro)."""
    n = to_int(v, maximum=MAX_QTY)
    return (n, None) if n is not None else (None, f"Mínimo inválido: informe um número inteiro de 0 a {MAX_QTY}.")

"""Registro de erros e avisos: no console (janela do iniciar.bat) e em data/logs/sistema.log.

Na oficina a janela fica minimizada ou é fechada; o arquivo guarda o que aconteceu para quem for dar suporte.
"""
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE = Path("logs") / "sistema.log"
MAX_BYTES = 1_000_000
BACKUPS = 5  # até ~6 MB no total
ANSI_COLOR = re.compile(r"\x1b\[[0-9;]*m")


class _PlainFormatter(logging.Formatter):
    """Tira as cores do terminal (o Werkzeug colore as linhas de acesso): no arquivo elas só atrapalham."""

    def format(self, record):
        return ANSI_COLOR.sub("", super().format(record))


def setup_logging(data_dir):
    """Liga o log do sistema inteiro (raiz do logging). Chame antes de importar o app, para o Flask não criar o
    próprio handler e cada erro sair duas vezes no console. Devolve o caminho do arquivo."""
    path = Path(data_dir) / LOG_FILE
    root = logging.getLogger()
    if any(getattr(h, "baseFilename", None) == str(path.absolute()) for h in root.handlers):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    to_file = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    to_file.setFormatter(_PlainFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    to_console = logging.StreamHandler()
    to_console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(to_file)
    root.addHandler(to_console)
    root.setLevel(logging.INFO)
    return path

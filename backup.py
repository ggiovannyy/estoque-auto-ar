"""Copias de seguranca automaticas do banco de dados.

As copias vao para uma pasta que o proprio Windows sincroniza com a nuvem
(OneDrive, detectado sozinho, ou Google Drive / outra pasta via MAXX_BACKUP_DIR).
Assim o sistema nao precisa guardar senha nem chave de nenhum servico.
"""
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

CLOUD_FOLDER_NAME = "Backup Estoque Maxx"
FILE_PREFIX = "estoque-"
FILE_SUFFIX = ".db"
TIMESTAMP_FORMAT = "%Y-%m-%d_%H%M%S"
ONEDRIVE_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")  # definidas pelo Windows
DEFAULT_KEEP = 30  # uma copia por dia: um mes de historico
SYNCED_FOLDER_NAMES = ("Google Drive", "Meu Drive", "My Drive", "Dropbox")


def default_backup_dir(data_dir, env=os.environ):
    """Pasta configurada > OneDrive do Windows > data/backups (so local, sem nuvem)."""
    if env.get("MAXX_BACKUP_DIR"):
        return Path(env["MAXX_BACKUP_DIR"])
    for var in ONEDRIVE_VARS:
        onedrive = env.get(var)
        if onedrive and Path(onedrive).is_dir():
            return Path(onedrive) / CLOUD_FOLDER_NAME
    return Path(data_dir) / "backups"


def synced_folder(path, env=os.environ):
    """Pasta sincronizada com a nuvem (OneDrive, Google Drive, Dropbox) que contem `path`, ou None.

    O lugar do backup e numa pasta assim; o do banco em uso, nao: a sincronizacao mexe nos arquivos -wal/-shm
    enquanto o SQLite grava, e a chave da sessao (secret.key) iria para a nuvem.
    """
    path = Path(path).absolute()
    for var in ONEDRIVE_VARS:
        if env.get(var):
            root = Path(env[var]).absolute()
            if path == root or root in path.parents:
                return root
    return next((p for p in (path, *path.parents) if p.name in SYNCED_FOLDER_NAMES), None)


def make_backup(db_path, dest_dir, now=None):
    """Grava uma copia consistente do banco (inclusive com o sistema em uso) e devolve o caminho."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime(TIMESTAMP_FORMAT)
    target = dest_dir / f"{FILE_PREFIX}{stamp}{FILE_SUFFIX}"
    partial = target.with_name(target.name + ".tmp")
    if not Path(db_path).is_file():  # sqlite3.connect criaria um banco vazio e o "backup" sairia vazio
        raise FileNotFoundError(f"Banco de dados não encontrado: {db_path}")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(partial)
    try:
        src.backup(dst)  # API de backup do SQLite: inclui o que ainda esta no arquivo -wal
    finally:
        dst.close()
        src.close()
    os.replace(partial, target)  # a pasta da nuvem nunca ve uma copia pela metade
    return target


def _backups(dest_dir):
    """Copias feitas por este sistema, da mais antiga para a mais nova."""
    dest_dir = Path(dest_dir)
    if not dest_dir.is_dir():
        return []
    return sorted(p for p in dest_dir.glob(f"{FILE_PREFIX}*{FILE_SUFFIX}") if _parse_stamp(p))


def _parse_stamp(path):
    try:
        return datetime.strptime(path.name[len(FILE_PREFIX):-len(FILE_SUFFIX)], TIMESTAMP_FORMAT)
    except ValueError:
        return None


def last_backup_at(dest_dir):
    files = _backups(dest_dir)
    return _parse_stamp(files[-1]) if files else None


def prune_backups(dest_dir, keep):
    """Apaga as copias mais antigas, mantendo as `keep` mais recentes. Nao toca em outros arquivos."""
    old = _backups(dest_dir)[:-keep] if keep > 0 else _backups(dest_dir)
    for p in old:
        p.unlink()
    return old


class BackupScheduler:
    """Faz uma copia por dia enquanto o sistema estiver aberto.

    Confere de hora em hora em vez de agendar um horario fixo: se o computador
    ficar desligado no horario, a copia sai assim que ele voltar.
    """
    INTERVAL = timedelta(hours=24)
    CHECK_EVERY_SECONDS = 60 * 60

    def __init__(self, db_path, dest_dir, keep=DEFAULT_KEEP, clock=datetime.now):
        self.db_path = Path(db_path)
        self.dest_dir = Path(dest_dir)
        self.keep = keep
        self.clock = clock
        self._stop = threading.Event()

    def run_if_due(self):
        """Faz a copia se a ultima tiver mais de 24h. Devolve o caminho da copia, ou None."""
        last = last_backup_at(self.dest_dir)
        now = self.clock()
        if last and now - last < self.INTERVAL:
            return None
        try:
            path = make_backup(self.db_path, self.dest_dir, now=now)
            prune_backups(self.dest_dir, self.keep)
        except (OSError, sqlite3.Error) as e:
            print(f"  Falha no backup em {self.dest_dir}: {e}")
            return None
        print(f"  Backup salvo: {path}")
        return path

    def start(self):
        threading.Thread(target=self._loop, name="backup", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            self.run_if_due()
            self._stop.wait(self.CHECK_EVERY_SECONDS)

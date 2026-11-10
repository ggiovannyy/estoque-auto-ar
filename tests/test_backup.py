"""Cópias de segurança automáticas do banco."""
import sqlite3
from datetime import datetime, timedelta

import pytest

import backup
from conftest import new_product

T0 = datetime(2026, 11, 6, 8, 0, 0)


def make_db(path, rows=3):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    return conn  # aberta: os dados ainda estao no arquivo -wal, sem checkpoint


def count_rows(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------- copia
def test_backup_e_uma_copia_completa_mesmo_com_dados_so_no_wal(tmp_path):
    conn = make_db(tmp_path / "estoque.db", rows=5)
    path = backup.make_backup(tmp_path / "estoque.db", tmp_path / "bk", now=T0)
    conn.close()
    assert path.name == "estoque-2026-11-06_080000.db"
    assert count_rows(path) == 5
    assert not list((tmp_path / "bk").glob("*.tmp"))


def test_mantem_so_as_copias_mais_recentes(tmp_path):
    make_db(tmp_path / "estoque.db").close()
    dest = tmp_path / "bk"
    for d in range(5):
        backup.make_backup(tmp_path / "estoque.db", dest, now=T0 + timedelta(days=d))
    (dest / "anotacoes.txt").write_text("arquivo do usuario")
    removed = backup.prune_backups(dest, keep=2)
    assert len(removed) == 3
    assert sorted(p.name for p in dest.iterdir()) == [
        "anotacoes.txt", "estoque-2026-11-09_080000.db", "estoque-2026-11-10_080000.db"]


def test_data_do_ultimo_backup_vem_do_nome_do_arquivo(tmp_path):
    assert backup.last_backup_at(tmp_path / "vazio") is None
    make_db(tmp_path / "estoque.db").close()
    backup.make_backup(tmp_path / "estoque.db", tmp_path / "bk", now=T0)
    backup.make_backup(tmp_path / "estoque.db", tmp_path / "bk", now=T0 + timedelta(hours=3))
    assert backup.last_backup_at(tmp_path / "bk") == T0 + timedelta(hours=3)


# ---------------------------------------------------------------- pasta de destino
def test_pasta_configurada_tem_prioridade(tmp_path):
    env = {"MAXX_BACKUP_DIR": str(tmp_path / "Drive"), "OneDrive": str(tmp_path)}
    assert backup.default_backup_dir(tmp_path / "data", env) == tmp_path / "Drive"


def test_usa_o_onedrive_quando_existe(tmp_path):
    (tmp_path / "OneDrive").mkdir()
    env = {"OneDrive": str(tmp_path / "OneDrive")}
    assert backup.default_backup_dir(tmp_path / "data", env) == tmp_path / "OneDrive" / backup.CLOUD_FOLDER_NAME


# Pasta de dados dentro de pasta sincronizada: o banco em WAL pode corromper e a chave da sessão vai para a nuvem.
def test_pasta_de_dados_dentro_do_onedrive_e_detectada(tmp_path):
    env = {"OneDrive": str(tmp_path / "OneDrive")}
    assert backup.synced_folder(tmp_path / "OneDrive" / "Documentos" / "estoque" / "data", env) == tmp_path / "OneDrive"


@pytest.mark.parametrize("parts", [("Google Drive", "Meu Drive"), ("Meu Drive",), ("My Drive",), ("Dropbox",)])
def test_pasta_de_dados_dentro_de_outras_nuvens_e_detectada(tmp_path, parts):
    root = tmp_path.joinpath(*parts)
    assert backup.synced_folder(root / "estoque" / "data", {}) is not None


def test_pasta_de_dados_fora_da_nuvem_nao_e_detectada(tmp_path):
    env = {"OneDrive": str(tmp_path / "OneDrive")}
    assert backup.synced_folder(tmp_path / "MaxxEstoque" / "data", env) is None
    assert backup.synced_folder(tmp_path / "OneDriveVelho" / "data", env) is None


def test_sem_nuvem_guarda_dentro_da_pasta_de_dados(tmp_path):
    env = {"OneDrive": str(tmp_path / "nao-existe")}
    assert backup.default_backup_dir(tmp_path / "data", env) == tmp_path / "data" / "backups"


# ---------------------------------------------------------------- agendamento
@pytest.fixture
def scheduler(tmp_path):
    make_db(tmp_path / "estoque.db").close()
    now = [T0]
    s = backup.BackupScheduler(tmp_path / "estoque.db", tmp_path / "bk", keep=3, clock=lambda: now[0])
    return s, now


def test_faz_backup_na_primeira_vez(scheduler):
    s, _ = scheduler
    assert s.run_if_due() is not None


def test_nao_repete_antes_de_24_horas(scheduler):
    s, now = scheduler
    s.run_if_due()
    now[0] += timedelta(hours=23)
    assert s.run_if_due() is None


def test_repete_depois_de_24_horas_e_limpa_as_antigas(scheduler):
    s, now = scheduler
    for _ in range(5):
        assert s.run_if_due() is not None
        now[0] += timedelta(hours=24, minutes=1)
    assert len(list(s.dest_dir.glob("estoque-*.db"))) == 3


def test_erro_no_backup_nao_derruba_o_sistema(tmp_path, capsys):
    s = backup.BackupScheduler(tmp_path / "nao-existe" / "estoque.db", tmp_path / "bk", keep=3, clock=lambda: T0)
    assert s.run_if_due() is None
    assert "Falha no backup" in capsys.readouterr().out


# ---------------------------------------------------------------- tela "Mais"
def test_dono_ve_o_status_e_faz_backup_agora(app, owner, tmp_path):
    app.config["BACKUP_DIR"] = str(tmp_path / "bk")
    assert owner.get("/api/backup").get_json() == {"dir": str(tmp_path / "bk"), "last_at": None}
    new_product(owner)
    r = owner.post("/api/backup")
    assert r.status_code == 200 and r.get_json()["last_at"]
    bk = next((tmp_path / "bk").glob("estoque-*.db"))
    assert sqlite3.connect(bk).execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1


def test_atendente_nao_acessa_backup(app, attendant, tmp_path):
    app.config["BACKUP_DIR"] = str(tmp_path / "bk")
    assert attendant.get("/api/backup").status_code == 403
    assert attendant.post("/api/backup").status_code == 403


@pytest.mark.parametrize("falha", [OSError("disco cheio"), sqlite3.OperationalError("disk I/O error")])
def test_falha_no_backup_manual_vira_mensagem_clara(app, owner, tmp_path, monkeypatch, falha):
    import app as appmod

    def quebra(*_a, **_k):
        raise falha
    app.config["BACKUP_DIR"] = str(tmp_path / "bk")
    monkeypatch.setattr(appmod, "make_backup", quebra)
    r = owner.post("/api/backup")
    assert r.status_code == 500
    assert "Não foi possível salvar o backup" in r.get_json()["error"]

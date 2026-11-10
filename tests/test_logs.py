"""Erros registrados em arquivo de log e nunca expostos a quem usa o sistema."""
import logging

import pytest

import app as appmod
import logs


@pytest.fixture
def log_file(tmp_path):
    root = logging.getLogger()
    before = list(root.handlers)
    yield logs.setup_logging(tmp_path)
    for h in root.handlers[:]:
        if h not in before:
            root.removeHandler(h)
            h.close()


def test_registra_em_arquivo_na_pasta_de_dados(log_file, tmp_path):
    assert log_file == tmp_path / "logs" / "sistema.log"
    logging.getLogger("teste").error("algo deu errado")
    assert "algo deu errado" in log_file.read_text(encoding="utf-8")


def test_arquivo_sai_sem_as_cores_do_terminal(log_file):
    """O Werkzeug colore as linhas de acesso com códigos ANSI; no arquivo eles só atrapalham a leitura."""
    logging.getLogger("werkzeug").info('"%s" 404 -', "\x1b[33mGET /api/x HTTP/1.1\x1b[0m")
    content = log_file.read_text(encoding="utf-8")
    assert '"GET /api/x HTTP/1.1" 404' in content and "\x1b[" not in content


def test_configurar_de_novo_nao_duplica_as_linhas(log_file, tmp_path):
    logs.setup_logging(tmp_path)
    logging.getLogger("teste").warning("uma vez")
    assert log_file.read_text(encoding="utf-8").count("uma vez") == 1


def test_erro_inesperado_vira_json_generico_e_vai_para_o_log(app, owner, monkeypatch, caplog):
    monkeypatch.setitem(app.config, "PROPAGATE_EXCEPTIONS", False)
    monkeypatch.setattr(appmod, "min_default", lambda: 1 / 0)
    with caplog.at_level(logging.ERROR):
        r = owner.get("/api/summary")
    assert r.status_code == 500
    assert r.get_json() == {"error": "Erro inesperado no servidor. Tente de novo; se continuar, avise o responsável."}
    assert "ZeroDivisionError" in caplog.text           # o detalhe fica no log, não na resposta
    assert "ZeroDivisionError" not in r.get_data(as_text=True)


def test_rota_da_api_que_nao_existe_responde_json(owner):
    r = owner.get("/api/nao-existe")
    assert r.status_code == 404
    assert r.get_json()["error"]

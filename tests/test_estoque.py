"""Regras de estoque: entrada, saída, contagem, alerta de estoque baixo e cadastro."""
from conftest import move, new_product


def qty_of(client, pid):
    return client.get(f"/api/products/{pid}").get_json()["qty"]


def test_entrada_e_saida_alteram_a_quantidade(owner):
    p = new_product(owner, qty=5)
    assert move(owner, p["id"], "in", 3).status_code == 200
    assert move(owner, p["id"], "out", 2).status_code == 200
    assert qty_of(owner, p["id"]) == 6


def test_saida_maior_que_o_estoque_e_recusada_e_nada_muda(owner):
    p = new_product(owner, qty=2)
    r = move(owner, p["id"], "out", 3)
    assert r.status_code == 400
    assert "insuficiente" in r.get_json()["error"]
    assert qty_of(owner, p["id"]) == 2


def test_saida_de_tudo_deixa_zero(owner):
    p = new_product(owner, qty=2)
    assert move(owner, p["id"], "out", 2).get_json()["qty"] == 0


def test_quantidade_zero_ou_invalida_e_recusada_em_entrada_e_saida(owner):
    p = new_product(owner, qty=2)
    for bad in (0, -1, "abc", None):
        assert move(owner, p["id"], "in", bad).status_code == 400
        assert move(owner, p["id"], "out", bad).status_code == 400
    assert qty_of(owner, p["id"]) == 2


def test_contagem_define_a_quantidade_e_registra_a_diferenca(owner):
    p = new_product(owner, qty=7)
    r = move(owner, p["id"], "adjust", 4)
    assert r.get_json()["qty"] == 4
    last = owner.get(f"/api/products/{p['id']}").get_json()["movements"][0]
    assert (last["type"], last["delta"], last["balance"]) == ("adjust", -3, 4)


def test_historico_registra_estoque_inicial_e_saldo(owner):
    p = new_product(owner, qty=5)
    move(owner, p["id"], "out", 1, note="venda sem nota")
    moves = owner.get(f"/api/products/{p['id']}").get_json()["movements"]
    assert [(m["type"], m["delta"], m["balance"]) for m in moves] == [("out", -1, 4), ("in", 5, 5)]
    assert moves[0]["note"] == "venda sem nota"
    assert "qty" not in moves[0]  # delta e balance bastam; qty tinha um sentido em adjust e outro no resto


# ---------------------------------------------------------------- alerta de estoque baixo
def test_alerta_dispara_com_quantidade_igual_ao_minimo_padrao(owner):
    no_limite = new_product(owner, name="A", qty=2)
    acima = new_product(owner, name="B", qty=3)
    assert no_limite["low"] is True and no_limite["min_effective"] == 2
    assert acima["low"] is False


def test_minimo_proprio_da_peca_tem_prioridade_sobre_o_padrao(owner):
    p = new_product(owner, qty=4, min_qty=5)
    assert p["low"] is True and p["min_effective"] == 5


def test_mudar_o_minimo_padrao_muda_os_alertas(owner):
    p = new_product(owner, qty=4)
    assert p["low"] is False
    assert owner.put("/api/settings", json={"min_default": 4}).status_code == 200
    assert owner.get(f"/api/products/{p['id']}").get_json()["low"] is True


def test_filtro_low_e_resumo_contam_os_mesmos_alertas(owner):
    new_product(owner, name="Baixa", qty=1)
    new_product(owner, name="Zerada", qty=0)
    new_product(owner, name="Ok", qty=10)
    low = owner.get("/api/products?low=1").get_json()
    assert sorted(p["name"] for p in low) == ["Baixa", "Zerada"]
    assert owner.get("/api/summary").get_json()["low"] == 2


# ---------------------------------------------------------------- cadastro
def test_quantidade_inicial_invalida_e_recusada_e_nada_e_cadastrado(owner):
    for bad in (-1, "abc", "2.5", [3]):
        r = owner.post("/api/products", json={"name": f"Peça {bad}", "qty": bad})
        assert r.status_code == 400, bad
        assert "Quantidade inicial" in r.get_json()["error"]
    assert owner.get("/api/products").get_json() == []


def test_quantidade_inicial_vazia_cadastra_com_zero(owner):
    assert new_product(owner, name="Sem qty", qty=None)["qty"] == 0
    assert new_product(owner, name="Qty vazia", qty="")["qty"] == 0
    assert new_product(owner, name="Qty texto", qty="3")["qty"] == 3


def test_lista_de_pecas_pode_vir_em_paginas(owner):
    for i in range(5):
        new_product(owner, name=f"Peça {i}")
    def names(qs):
        return [p["name"] for p in owner.get("/api/products" + qs).get_json()]

    assert names("") == [f"Peça {i}" for i in range(5)]
    assert names("?limit=2") == ["Peça 0", "Peça 1"]
    assert names("?limit=2&offset=2") == ["Peça 2", "Peça 3"]
    assert names("?limit=2&offset=4") == ["Peça 4"]
    assert names("?limit=abc") == names("?limit=0") == names("")  # limite inválido: lista inteira


def test_codigo_de_barras_duplicado_e_recusado(owner):
    new_product(owner, barcode="7891234567895")
    r = owner.post("/api/products", json={"name": "Outra", "barcode": "7891234567895"})
    assert r.status_code == 400


def test_busca_por_codigo_de_barras(owner):
    p = new_product(owner, barcode="7891234567895")
    assert owner.get("/api/products/barcode/7891234567895").get_json()["id"] == p["id"]
    assert owner.get("/api/products/barcode/000").status_code == 404


def test_peca_excluida_libera_o_codigo_de_barras(owner):
    p = new_product(owner, barcode="7891234567895")
    assert owner.delete(f"/api/products/{p['id']}").status_code == 200
    new_product(owner, barcode="7891234567895")


# ---------------------------------------------------------------- UPC-A (12 dígitos) x EAN-13 (13 dígitos)
# A câmera pode ler o código de uma peça como UPC-A e o leitor USB como EAN-13 (o mesmo número com
# um 0 na frente). O sistema grava e busca sempre com 13 dígitos para os dois acharem a mesma peça.
UPC_A = "036000291452"
EAN_13 = "0" + UPC_A


def test_codigo_upc_a_e_gravado_com_13_digitos(owner):
    assert new_product(owner, barcode=UPC_A)["barcode"] == EAN_13


def test_busca_acha_a_peca_pelo_upc_a_ou_pelo_ean_13(owner):
    pela_camera = new_product(owner, name="Cadastrada pela câmera", barcode=UPC_A)
    assert owner.get(f"/api/products/barcode/{EAN_13}").get_json()["id"] == pela_camera["id"]
    assert owner.get(f"/api/products/barcode/{UPC_A}").get_json()["id"] == pela_camera["id"]


def test_upc_a_e_ean_13_do_mesmo_codigo_sao_a_mesma_peca(owner):
    new_product(owner, barcode=EAN_13)
    r = owner.post("/api/products", json={"name": "Duplicada", "barcode": UPC_A})
    assert r.status_code == 400


def test_edicao_tambem_grava_com_13_digitos(owner):
    p = new_product(owner)
    r = owner.put(f"/api/products/{p['id']}", json={"name": p["name"], "barcode": f" {UPC_A} "})
    assert r.get_json()["barcode"] == EAN_13


def test_outros_codigos_ficam_como_foram_lidos(owner):
    for code in ("7891234567895", "12345670", "ABC-12345678", "1234567890123456", "03600029145a"):
        assert new_product(owner, name=code, barcode=code)["barcode"] == code


# Teto de quantidade: o leitor USB "digita" o código de barras e um Enter no campo que estiver em foco.
CODIGO_LIDO_NO_CAMPO = 7891234567895


def test_quantidade_acima_do_teto_e_recusada_na_movimentacao(owner):
    p = new_product(owner, qty=5)
    for type_ in ("in", "out", "adjust"):
        for bad in (100_001, CODIGO_LIDO_NO_CAMPO, 10**20):
            r = move(owner, p["id"], type_, bad)
            assert r.status_code == 400, (type_, bad)
            assert "100000" in r.get_json()["error"]
    assert qty_of(owner, p["id"]) == 5


def test_entrada_que_passaria_do_teto_e_recusada(owner):
    p = new_product(owner, qty=99_999)
    assert move(owner, p["id"], "in", 2).status_code == 400
    assert move(owner, p["id"], "in", 1).status_code == 200
    assert qty_of(owner, p["id"]) == 100_000


def test_quantidade_inicial_acima_do_teto_e_recusada(owner):
    r = owner.post("/api/products", json={"name": "Peça", "qty": CODIGO_LIDO_NO_CAMPO})
    assert r.status_code == 400
    assert owner.get("/api/products").get_json() == []
    assert new_product(owner, qty=100_000)["qty"] == 100_000


def test_minimo_invalido_ou_acima_do_teto_e_recusado(owner):
    for bad in (-1, "abc", 100_001):
        r = owner.post("/api/products", json={"name": "Peça", "qty": 1, "min_qty": bad})
        assert r.status_code == 400, bad
        assert "Mínimo" in r.get_json()["error"]
        assert owner.put("/api/settings", json={"min_default": bad}).status_code == 400
    assert owner.get("/api/products").get_json() == []


# Contagem com o saldo visto: o que foi vendido enquanto o dono contava não pode sumir do estoque.
def test_contagem_e_recusada_se_o_estoque_mudou_enquanto_se_contava(owner):
    p = new_product(owner, qty=5)                 # o dono abre a peça e vê 5
    assert move(owner, p["id"], "out", 2).status_code == 200   # o atendente vende 2 nesse meio-tempo
    r = move(owner, p["id"], "adjust", 5, expected=5)
    assert r.status_code == 409
    assert "de 5 para 3" in r.get_json()["error"]
    assert r.get_json()["qty"] == 3
    assert qty_of(owner, p["id"]) == 3


def test_contagem_com_o_saldo_certo_vale(owner):
    p = new_product(owner, qty=5)
    assert move(owner, p["id"], "adjust", 7, expected=5).status_code == 200
    assert qty_of(owner, p["id"]) == 7


def test_contagem_sem_saldo_visto_continua_valendo(owner):
    p = new_product(owner, qty=5)
    assert move(owner, p["id"], "adjust", 1).status_code == 200
    assert qty_of(owner, p["id"]) == 1


def test_saldo_visto_invalido_e_recusado(owner):
    p = new_product(owner, qty=5)
    assert move(owner, p["id"], "adjust", 1, expected="abc").status_code == 400
    assert qty_of(owner, p["id"]) == 5


def test_categoria_inexistente_tem_mensagem_propria(owner):
    r = owner.post("/api/products", json={"name": "Peça", "category_id": 9999})
    assert r.status_code == 400 and "Categoria" in r.get_json()["error"]
    p = new_product(owner)
    r = owner.put(f"/api/products/{p['id']}", json={"name": "Outro nome", "category_id": 9999})
    assert r.status_code == 400 and "Categoria" in r.get_json()["error"]
    assert owner.get(f"/api/products/{p['id']}").get_json()["name"] == p["name"]

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

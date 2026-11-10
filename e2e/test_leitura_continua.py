"""Leitura em sequência na aba Escanear: várias peças lidas seguidas, gravadas de uma vez (entrada ou contagem)."""
from dados import unique_barcode
from playwright.sync_api import expect


def start(page, mode="in"):
    page.goto("/")
    page.locator('nav.tabs [data-tab="scan"]').click()
    page.get_by_role("button", name="Leitura em sequência").click()
    page.locator(f'[data-batch-type="{mode}"]').click()


def read(page, code):
    page.fill("#code", code)
    page.press("#code", "Enter")


def qty_of(page, p):
    return page.request.get(f"/api/products/{p['id']}").json()["qty"]


def row(page, p):
    return page.locator(f'#batch [data-batch-id="{p["id"]}"]')


def test_entrada_em_sequencia_soma_as_leituras_e_grava_tudo_de_uma_vez(page, api):
    a, b = api.product(qty=1, barcode=unique_barcode()), api.product(qty=0, barcode=unique_barcode())
    unknown = unique_barcode()
    start(page, "in")
    for code in (a["barcode"], b["barcode"], a["barcode"], unknown):
        read(page, code)
    expect(row(page, a).locator("input")).to_have_value("2")
    expect(row(page, b).locator("input")).to_have_value("1")
    expect(page.locator("#batch .unknown", has_text=unknown)).to_contain_text("não cadastrada")
    expect(page.locator("#code")).to_be_focused()  # o leitor USB continua lendo sem clicar
    expect(page.locator(".sheet")).to_have_count(0)  # nada abre no meio da sequência

    row(page, b).locator("input").fill("3")
    page.fill("#batchnote", "NF 4471")
    page.get_by_role("button", name="Registrar entrada de 2 peças (5 unidades)").click()
    expect(page.locator("#toast")).to_contain_text("Entrada registrada: 2 peças")
    assert (qty_of(page, a), qty_of(page, b)) == (3, 3)
    expect(page.locator("#batch [data-batch-id]")).to_have_count(0)
    last = page.request.get(f"/api/products/{b['id']}").json()["movements"][0]
    assert last["note"] == "NF 4471"


def test_contagem_em_sequencia_define_o_saldo_e_avisa_se_mudou(page, api):
    a = api.product(qty=9, barcode=unique_barcode())
    start(page, "adjust")
    for _ in range(3):
        read(page, a["barcode"])
    expect(row(page, a).locator("input")).to_have_value("3")
    page.request.post(f"/api/products/{a['id']}/move", data={"type": "out", "qty": 1})  # vendeu uma no meio

    save = page.get_by_role("button", name="Salvar contagem de 1 peça")
    save.click()
    expect(page.locator("#batcherr .err")).to_contain_text("de 9 para 8")
    save.click()  # conferiu: salva de novo com o saldo novo
    expect(page.locator("#toast")).to_contain_text("Contagem salva: 1 peça")
    assert qty_of(page, a) == 3


def test_atendente_so_ve_a_entrada_em_sequencia(attendant_page):
    attendant_page.goto("/")
    attendant_page.locator('nav.tabs [data-tab="scan"]').click()
    attendant_page.get_by_role("button", name="Leitura em sequência").click()
    expect(attendant_page.locator('[data-batch-type="in"]')).to_be_visible()
    expect(attendant_page.locator('[data-batch-type="adjust"]')).to_have_count(0)


def test_lista_continua_depois_de_recarregar_a_pagina(page, api):
    a = api.product(qty=0, barcode=unique_barcode())
    start(page, "in")
    read(page, a["barcode"])
    expect(row(page, a)).to_be_visible()
    page.reload()
    page.locator('nav.tabs [data-tab="scan"]').click()
    expect(row(page, a).locator("input")).to_have_value("1")


def test_peca_nao_cadastrada_pode_ser_cadastrada_sem_perder_a_lista(page, api):
    a = api.product(qty=0, barcode=unique_barcode())
    code = unique_barcode()
    start(page, "in")
    read(page, a["barcode"])
    read(page, code)
    page.locator("#batch .unknown", has_text=code).get_by_role("button", name="Cadastrar").click()
    expect(page.locator('#newform input[name="barcode"]')).to_have_value(code)
    page.fill('#newform input[name="name"]', "Peça nova da sequência")
    page.locator("#newform button.btn").click()
    expect(page.locator("#batch .unknown")).to_have_count(0)
    expect(row(page, a)).to_be_visible()


def test_remover_e_limpar_a_lista(page, api):
    a, b = api.product(barcode=unique_barcode()), api.product(barcode=unique_barcode())
    start(page, "in")
    read(page, a["barcode"])
    read(page, b["barcode"])
    row(page, a).get_by_role("button", name="Remover").click()
    expect(page.locator("#batch [data-batch-id]")).to_have_count(1)
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Limpar lista").click()
    expect(page.locator("#batch [data-batch-id]")).to_have_count(0)


def test_uma_peca_por_vez_continua_abrindo_a_folha(page, api):
    a = api.product(barcode=unique_barcode())
    start(page, "in")
    page.get_by_role("button", name="Uma peça por vez").click()
    read(page, a["barcode"])
    expect(page.locator(".sheet h3")).to_have_text(a["name"])

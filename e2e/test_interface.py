"""Fluxos da interface no navegador, com o sistema rodando de verdade."""
import re

from dados import unique, unique_barcode
from playwright.sync_api import expect


def open_tab(page, tab):
    page.locator(f'[data-tab="{tab}"]').first.click()


def read_code(page, code):
    """O leitor USB 'digita' o código no campo e manda Enter."""
    page.fill("#code", code)
    page.press("#code", "Enter")


def search(page, text):
    """Digita na busca e espera a lista recarregar."""
    with page.expect_response(lambda r: "/api/products?" in r.url):
        page.fill("#q", text)


# ---------------------------------------------------------------- aba Escanear
def test_peca_nova_lida_no_escanear_abre_o_cadastro_e_depois_abre_a_peca(page):
    code, name = unique_barcode(), unique("Filtro")
    page.goto("/")
    open_tab(page, "scan")
    read_code(page, code)

    expect(page.locator(".sheet h3")).to_have_text("Nova peça")
    expect(page.locator('#newform input[name="barcode"]')).to_have_value(code)
    page.fill('#newform input[name="name"]', name)
    page.fill('#newform input[name="qty"]', "3")
    page.locator("#newform button.btn").click()
    expect(page.locator("#toast")).to_contain_text(f"{name} cadastrada (3 un.)")

    read_code(page, code)
    expect(page.locator(".sheet h3")).to_have_text(name)
    expect(page.locator(".bigqty b")).to_have_text("3")


def test_fechar_a_folha_devolve_o_foco_ao_campo_do_leitor(page, api):
    p = api.product(barcode=unique_barcode())
    page.goto("/")
    open_tab(page, "scan")
    for close in (lambda: page.keyboard.press("Escape"), lambda: page.locator(".sheet button.x").click()):
        read_code(page, p["barcode"])
        expect(page.locator(".sheet h3")).to_have_text(p["name"])
        close()
        expect(page.locator(".sheet")).to_have_count(0)
        expect(page.locator("#code")).to_be_focused()


def test_no_celular_o_campo_do_leitor_nao_recebe_foco_sozinho(phone):
    phone.goto("/")
    open_tab(phone, "scan")
    expect(phone.locator("#code")).to_be_visible()
    expect(phone.locator("#code")).not_to_be_focused()  # o teclado do celular não abre sozinho


def test_peca_nova_e_decidida_pelo_404_e_nao_pelo_texto_do_erro(page):
    page.goto("/")
    open_tab(page, "scan")

    page.route("**/api/products/barcode/**", lambda r: r.fulfill(
        status=404, content_type="application/json", body='{"error": "Qualquer outro texto."}'))
    read_code(page, unique_barcode())
    expect(page.locator(".sheet h3")).to_have_text("Nova peça")
    page.keyboard.press("Escape")

    page.route("**/api/products/barcode/**", lambda r: r.fulfill(
        status=500, content_type="application/json", body='{"error": "Peça não cadastrada (erro do servidor)."}'))
    read_code(page, unique_barcode())
    expect(page.locator("#toast")).to_contain_text("erro do servidor")
    expect(page.locator(".sheet")).to_have_count(0)


# ---------------------------------------------------------------- movimentação
def test_saida_atualiza_a_quantidade_e_aparece_no_historico(page, api):
    p = api.product(qty=5)
    page.goto("/")
    search(page, p["name"])
    page.locator(f'[data-open="{p["id"]}"]').click()

    page.locator('[data-type="out"]').click()
    page.fill("#mqty", "2")
    page.fill("#mnote", "venda sem nota")
    page.locator("#mgo").click()
    expect(page.locator("#toast")).to_contain_text(f"{p['name']}: agora 3 em estoque")

    open_tab(page, "history")
    row = page.locator(".mv", has_text=p["name"]).first
    expect(row).to_contain_text("Saída · venda sem nota")
    expect(row.locator(".d")).to_have_text("-2")


def test_saida_maior_que_o_estoque_mostra_o_erro_na_folha(page, api):
    p = api.product(qty=1)
    page.goto("/")
    search(page, p["name"])
    page.locator(f'[data-open="{p["id"]}"]').click()
    page.fill("#mqty", "2")
    page.locator("#mgo").click()
    expect(page.locator("#merr .err")).to_contain_text("Estoque insuficiente")


# ---------------------------------------------------------------- aba Estoque
def test_busca_recarrega_so_a_lista_de_pecas(page, api):
    p = api.product()
    page.goto("/")
    expect(page.locator("#q")).to_be_visible()
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "/api/" in r.url else None)

    search(page, p["name"])

    expect(page.locator(".item")).to_have_count(1)
    assert [re.sub(r"\?.*", "", u.split("/api")[1]) for u in requests] == ["/products"]
    expect(page.locator("#q")).to_be_focused()


def test_resposta_atrasada_de_uma_busca_antiga_e_descartada(page, api):
    old, new = api.product(name=unique("Antiga")), api.product(name=unique("Nova"))
    page.goto("/")
    expect(page.locator("#q")).to_be_visible()

    def slow(route):
        page.wait_for_timeout(1200)
        route.continue_()
    page.route(re.compile(r".*/api/products\?.*q=Antiga.*"), slow)

    page.fill("#q", old["name"])
    page.wait_for_timeout(400)          # a busca antiga já saiu e está demorando
    search(page, new["name"])
    page.wait_for_timeout(1500)         # a resposta antiga chega depois da nova

    expect(page.locator(".item .t b")).to_have_text([new["name"]])


def test_lista_vem_em_paginas_de_200(page, api):
    cat = api.category(unique("Categoria grande"))
    for i in range(205):
        api.product(name=f"{cat['name']} item {i:03d}", category_id=cat["id"], qty=3)
    page.goto("/")
    with page.expect_response(lambda r: f"category={cat['id']}" in r.url):
        page.locator(f'[data-cat="{cat["id"]}"]').click()

    expect(page.locator(".item")).to_have_count(200)
    page.locator('[data-act="more"]').click()
    expect(page.locator(".item")).to_have_count(205)
    expect(page.locator('[data-act="more"]')).to_have_count(0)
    names = page.locator(".item .t b").all_inner_texts()
    assert len(set(names)) == 205


def test_alertas_mostram_todas_as_pecas_baixas_mesmo_com_busca_ativa(page, api):
    low = api.product(name=unique("Baixa"), qty=1)
    page.goto("/")
    search(page, "nada-com-esse-nome")
    expect(page.locator(".item")).to_have_count(0)

    open_tab(page, "alerts")
    expect(page.locator(f'[data-open="{low["id"]}"]')).to_contain_text("Estoque baixo")


# ---------------------------------------------------------------- permissões
def test_atendente_nao_ve_a_contagem_e_o_dono_ve(page, attendant_page, api):
    p = api.product(qty=5)
    for pg, sees_count in ((attendant_page, False), (page, True)):
        pg.goto("/")
        search(pg, p["name"])
        pg.locator(f'[data-open="{p["id"]}"]').click()
        expect(pg.locator('[data-type="out"]')).to_be_visible()
        expect(pg.locator('[data-type="adjust"]')).to_have_count(1 if sees_count else 0)

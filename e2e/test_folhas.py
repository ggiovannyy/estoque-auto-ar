"""Folhas (janelas) da interface: envio único, rótulos, erros visíveis e foco do teclado."""
from dados import unique, unique_barcode
from playwright.sync_api import expect


def open_product(page, p):
    """Abre a folha da peça pela lista do Estoque."""
    with page.expect_response(lambda r: "/api/products?" in r.url):
        page.fill("#q", p["name"])
    page.locator(f'[data-open="{p["id"]}"]').click()
    expect(page.get_by_role("dialog")).to_be_visible()


def delay(page, pattern, ms=600):
    """Segura as requisições que casam com o padrão, como numa rede lenta."""
    def slow(route):
        page.wait_for_timeout(ms)
        route.continue_()
    page.route(pattern, slow)


# ---------------------------------------------------------------- envio único (FE-01)
def test_duplo_clique_em_cadastrar_cria_uma_peca_so(page):
    name = unique("Duplo clique")
    page.goto("/")
    page.locator('[data-act="new"]').click()
    page.fill('#newform input[name="name"]', name)
    delay(page, "**/api/products")
    page.locator("#newform button.btn").dblclick()
    expect(page.locator("#toast")).to_contain_text(f"{name} cadastrada")

    found = page.request.get("/api/products", params={"q": name}).json()
    assert len(found) == 1


def test_botao_fica_travado_enquanto_envia_e_volta_depois_do_erro(page, api):
    p = api.product(barcode=unique_barcode())
    page.goto("/")
    page.locator('[data-act="new"]').click()
    page.fill('#newform input[name="name"]', unique("Repetida"))
    page.fill('#newform input[name="barcode"]', p["barcode"])
    delay(page, "**/api/products")
    button = page.locator("#newform button.btn")
    button.click()
    expect(button).to_be_disabled()
    expect(page.locator("#ferr .err")).to_contain_text("código de barras")
    expect(button).to_be_enabled()  # dá para corrigir e enviar de novo


# ---------------------------------------------------------------- contagem (FE-02)
def test_contagem_nao_troca_o_rotulo_da_observacao(page, api):
    p = api.product(qty=4)
    page.goto("/")
    open_product(page, p)
    page.locator('[data-type="adjust"]').click()

    expect(page.get_by_label("Quantidade contada")).to_have_value("4")
    expect(page.get_by_label("Observação (opcional)")).to_be_visible()
    expect(page.get_by_text("Quantidade real contada")).to_have_count(0)

    page.locator('[data-type="out"]').click()
    expect(page.get_by_label("Quantidade", exact=True)).to_have_value("1")


# ---------------------------------------------------------------- erro na edição (FE-04)
def test_erro_ao_salvar_a_edicao_aparece_junto_do_formulario(page, api):
    other, p = api.product(barcode=unique_barcode()), api.product()
    page.set_viewport_size({"width": 390, "height": 700})
    page.goto("/")
    open_product(page, p)
    page.get_by_text("Editar dados da peça").click()
    page.fill('#editform input[name="barcode"]', other["barcode"])
    page.locator("#editform button.btn:not(.danger)").click()

    error = page.locator("#editform .err")
    expect(error).to_contain_text("código de barras")
    expect(error).to_be_in_viewport()


# ---------------------------------------------------------------- foco do teclado (FE-07)
def test_folha_tem_nome_e_prende_o_foco_do_teclado(page, api):
    p = api.product()
    page.goto("/")
    open_product(page, p)
    dialog = page.get_by_role("dialog")
    expect(dialog).to_have_accessible_name(p["name"])

    def cycle():
        for i, key in enumerate(["Tab"] * 25 + ["Shift+Tab"] * 25):
            page.keyboard.press(key)
            where = page.evaluate("() => document.activeElement.outerHTML.slice(0, 60)")
            assert dialog.evaluate("(d) => d.contains(document.activeElement)"), f"o foco saiu da folha ({i}, {key}): {where}"
    cycle()
    page.get_by_text("Editar dados da peça").click()  # com a edição aberta, os campos dela entram na volta
    cycle()


def test_fechar_a_folha_devolve_o_foco_a_peca_que_a_abriu(page, api):
    p = api.product(qty=5)
    page.goto("/")
    open_product(page, p)
    page.keyboard.press("Escape")
    expect(page.locator(f'[data-open="{p["id"]}"]')).to_be_focused()

    # Depois de registrar uma saída a lista é redesenhada: o foco volta à mesma peça.
    page.locator(f'[data-open="{p["id"]}"]').click()
    page.locator("#mgo").click()
    expect(page.locator("#toast")).to_contain_text("agora 4 em estoque")
    expect(page.locator(f'[data-open="{p["id"]}"]')).to_be_focused()

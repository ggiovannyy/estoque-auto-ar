"""Desempenho no navegador: a busca não recria a tela e a câmera só carrega quando é usada."""
from playwright.sync_api import expect


def test_busca_atualiza_so_a_lista_sem_recriar_o_campo(page, api):
    p = api.product()
    other = api.product()
    page.goto("/")
    q = page.locator("#q")
    expect(q).to_be_visible()
    q.evaluate("(i) => (i.dataset.original = 'sim')")  # some se o campo for recriado
    q.press_sequentially(p["name"][:6])
    with page.expect_response(lambda r: "/api/products?" in r.url):
        q.press_sequentially(p["name"][6:])
    expect(page.locator(f'[data-open="{p["id"]}"]')).to_be_visible()
    expect(page.locator(f'[data-open="{other["id"]}"]')).to_have_count(0)
    assert q.evaluate("(i) => i.dataset.original") == "sim", "o campo de busca foi recriado"
    expect(q).to_be_focused()
    expect(q).to_have_value(p["name"])


def test_filtro_de_categoria_continua_marcando_o_escolhido(page, api):
    from dados import unique
    cat = api.category(unique("Cat filtro"))
    api.product(category_id=cat["id"])
    page.goto("/")
    chip = page.locator(f'[data-cat="{cat["id"]}"]')
    with page.expect_response(lambda r: f"category={cat['id']}" in r.url):
        chip.click()
    expect(page.locator(f'[data-cat="{cat["id"]}"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator('[data-cat="0"]')).to_have_attribute("aria-pressed", "false")

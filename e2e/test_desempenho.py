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


def test_biblioteca_da_camera_nao_carrega_na_abertura(page):
    loaded = []
    page.on("request", lambda r: loaded.append(r.url) if "html5-qrcode" in r.url else None)
    page.goto("/")
    page.locator('nav.tabs [data-tab="scan"]').click()
    expect(page.locator("#code")).to_be_visible()
    assert not loaded, "a biblioteca da câmera (375 KB) carregou sem a câmera ser usada"


def test_camera_carrega_a_biblioteca_e_abre_no_primeiro_toque(playwright, base_url):
    """Câmera falsa do Chromium: a biblioteca carrega sob demanda e o vídeo aparece, sem erro nem bloqueio da CSP."""
    from conftest import OWNER
    browser = playwright.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
    ctx = browser.new_context(base_url=base_url, viewport={"width": 390, "height": 844}, permissions=["camera"])
    assert ctx.request.post("/api/login", data={"username": OWNER["username"], "password": OWNER["password"]}).ok
    page = ctx.new_page()
    problems = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.goto("/")
    page.locator('nav.tabs [data-tab="scan"]').click()
    with page.expect_request("**/html5-qrcode.min.js"):
        page.get_by_role("button", name="Usar a câmera do celular").click()
    expect(page.locator("#reader video")).to_be_visible(timeout=10000)
    expect(page.get_by_role("button", name="Fechar câmera")).to_be_visible()
    page.get_by_role("button", name="Fechar câmera").click()
    expect(page.locator("#reader")).to_be_hidden()
    browser.close()
    assert not problems, problems


def test_tela_nao_busca_nada_fora_do_proprio_servidor_e_carrega_as_fontes(page, base_url):
    outside = []
    page.on("request", lambda r: outside.append(r.url) if not r.url.startswith(base_url) else None)
    page.goto("/")
    expect(page.locator(".stats")).to_be_visible()
    page.evaluate("document.fonts.ready")
    assert not outside, f"pedidos para fora do sistema: {outside}"
    for font in ("400 16px Barlow", "600 16px Barlow", "700 16px 'Barlow Semi Condensed'"):
        assert page.evaluate(f"document.fonts.check(\"{font}\")"), f"fonte não carregou: {font}"
    loaded = page.evaluate("[...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family + ' ' + f.weight)")
    assert any("Barlow" in f for f in loaded), loaded

"""Sem conexão e resposta lenta: a tela avisa e deixa tentar de novo, em vez de mostrar dado velho calado."""
from playwright.sync_api import expect


def test_sem_conexao_mostra_aviso_fixo_e_tentar_de_novo_recarrega(page, api):
    p = api.product(qty=3)
    page.goto("/")
    expect(page.locator(".item").first).to_be_visible()
    page.context.set_offline(True)
    page.locator('nav.tabs [data-tab="history"]').click()

    banner = page.get_by_role("alert").filter(has_text="Sem conexão com o computador da oficina")
    expect(banner).to_be_visible()
    page.wait_for_timeout(3000)
    expect(banner).to_be_visible()  # não some sozinho como o aviso rápido

    page.context.set_offline(False)
    banner.get_by_role("button", name="Tentar de novo").click()
    expect(banner).to_be_hidden()
    expect(page.locator(".mv", has_text=p["name"]).first).to_be_visible()


def test_aviso_de_conexao_some_quando_qualquer_pedido_volta_a_funcionar(page):
    page.goto("/")
    expect(page.locator(".stats")).to_be_visible()
    page.context.set_offline(True)
    page.locator('nav.tabs [data-tab="alerts"]').click()
    expect(page.locator("#net")).to_be_visible()
    page.context.set_offline(False)
    page.locator('nav.tabs [data-tab="history"]').click()
    expect(page.locator("#net")).to_be_hidden()


def test_resposta_lenta_mostra_carregando(page):
    page.goto("/")
    expect(page.locator(".stats")).to_be_visible()

    def slow(route):
        page.wait_for_timeout(1200)
        route.continue_()
    page.route("**/api/movements*", slow)
    page.locator('nav.tabs [data-tab="history"]').click()
    expect(page.locator("#loading")).to_be_visible()
    expect(page.locator("h2.page")).to_have_text("Histórico")
    expect(page.locator("#loading")).to_be_hidden()


def test_resposta_rapida_nao_pisca_carregando(page):
    page.goto("/")
    expect(page.locator(".stats")).to_be_visible()
    page.evaluate("""() => { window._shown = false;
      new MutationObserver(() => { if (!document.querySelector('#loading').hidden) window._shown = true; })
        .observe(document.querySelector('#loading'), { attributes: true }); }""")
    page.locator('nav.tabs [data-tab="history"]').click()
    expect(page.locator("h2.page")).to_have_text("Histórico")
    assert not page.evaluate("window._shown")


def test_aviso_de_erro_fica_tempo_para_ler(page, api):
    page.goto("/")
    page.route("**/api/movements*", lambda r: r.fulfill(status=500, content_type="application/json",
                                                         body='{"error": "Erro inesperado no servidor."}'))
    page.locator('nav.tabs [data-tab="history"]').click()
    toast = page.locator("#toast")
    expect(toast).to_contain_text("Erro inesperado")
    page.wait_for_timeout(4000)
    expect(toast).to_have_class("show bad")

"""A CSP é rígida (scripts e estilos só do próprio sistema): nenhuma tela pode ser bloqueada por ela."""
from dados import unique_barcode
from playwright.sync_api import expect


def test_nenhuma_tela_e_bloqueada_pela_csp(page, api):
    blocked = []
    page.on("console", lambda m: blocked.append(m.text) if "Content Security Policy" in m.text else None)
    p = api.product(qty=1, barcode=unique_barcode())
    page.goto("/")
    expect(page.locator(".item").first).to_be_visible()
    for tab in ("alerts", "scan", "history", "more", "stock"):
        page.locator(f'nav.tabs [data-tab="{tab}"]').click()
        page.wait_for_load_state("networkidle")
    page.locator(f'[data-open="{p["id"]}"]').click()
    page.get_by_text("Editar dados da peça").click()
    page.keyboard.press("Escape")
    page.locator('nav.tabs [data-tab="scan"]').click()
    page.get_by_role("button", name="Leitura em sequência").click()
    page.fill("#code", p["barcode"])
    page.press("#code", "Enter")
    expect(page.locator("#batch [data-batch-id]")).to_be_visible()
    page.get_by_role("button", name="Uma peça por vez").click()
    assert not blocked, blocked

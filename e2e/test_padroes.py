"""Padrões da interface: áreas de toque, tamanho de texto, semântica e teclado certo para cada campo."""
import pytest
from dados import unique_barcode
from playwright.sync_api import expect

# Controles visíveis menores que 44 x 44 px (o mínimo confortável para o dedo, com luva ou na pressa).
SMALL_TARGETS = """() => [...document.querySelectorAll("button, a[href], input:not([type=hidden]), select, summary")]
  .filter((el) => { const r = el.getBoundingClientRect(); return r.width && r.height && r.bottom > 0 && r.top < innerHeight
    && getComputedStyle(el).visibility !== "hidden" && (r.height < 44 || r.width < 44); })
  .map((el) => `${el.tagName} "${(el.textContent || el.getAttribute("aria-label") || el.name || "").trim().slice(0, 25)}" `
    + `${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`)"""
# Texto visível menor que 13 px.
TINY_TEXT = """() => [...document.querySelectorAll("body *")].filter((el) => {
    if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) return false;
    const r = el.getBoundingClientRect();
    return r.width && r.height && r.bottom > 0 && r.top < innerHeight && !el.closest(".sr, [aria-hidden=true]")
      && parseFloat(getComputedStyle(el).fontSize) < 13;
  }).map((el) => `${el.tagName} "${el.textContent.trim().slice(0, 20)}" ${getComputedStyle(el).fontSize}`)"""


def check(page, where):
    page.wait_for_timeout(250)
    small, tiny = page.evaluate(SMALL_TARGETS), page.evaluate(TINY_TEXT)
    assert not small, f"{where}: área de toque menor que 44 px: {sorted(set(small))}"
    assert not tiny, f"{where}: texto menor que 13 px: {sorted(set(tiny))}"


def test_controles_e_textos_tem_tamanho_confortavel_no_celular(phone):
    page = phone
    r = page.request.post("/api/products", data={"name": "Peça de toque", "qty": 1, "barcode": unique_barcode()})
    p = r.json()
    page.goto("/")
    expect(page.locator(".item").first).to_be_visible()
    check(page, "Estoque")
    for tab in ("alerts", "scan", "history", "more"):
        page.locator(f'nav.tabs [data-tab="{tab}"]').click()
        page.wait_for_load_state("networkidle")
        check(page, tab)
        if tab == "more":
            page.mouse.wheel(0, 2000)
            check(page, "Mais (fim)")
    page.locator('nav.tabs [data-tab="stock"]').click()
    with page.expect_response(lambda resp: "/api/products?" in resp.url):
        page.fill("#q", p["name"])
    page.locator(f'[data-open="{p["id"]}"]').click()
    check(page, "folha da peça")
    page.get_by_text("Editar dados da peça").click()
    page.locator("#editform button.btn").first.scroll_into_view_if_needed()
    check(page, "edição")

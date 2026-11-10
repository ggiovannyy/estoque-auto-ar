"""Contraste (WCAG 2.2 AA) de todo texto visível e da borda dos campos, em cada tela."""
import pytest
from dados import unique_barcode
from playwright.sync_api import expect

# Para cada elemento com texto próprio e visível por cima de tudo: contraste da cor do texto com o primeiro fundo
# opaco atrás dele na tela. Texto grande (24 px, ou 18,66 px em negrito) precisa de 3:1; o resto, de 4,5:1.
# Campos: a borda contra o fundo em volta precisa de 3:1 (componente de interface).
AUDIT = """() => {
  const rgb = (c) => c.match(/[\\d.]+/g).map(Number);
  const opaque = (e) => { const c = rgb(getComputedStyle(e).backgroundColor); return c.length < 4 || c[3] === 1; };
  const lum = ([r, g, b]) => [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
    .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
  const ratio = (a, b) => { const x = lum(rgb(a)), y = lum(rgb(b)); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const bgAt = (el, x, y, skipSelf) => {
    // Fundo do próprio elemento primeiro: elementsFromPoint ignora quem tem pointer-events: none (o aviso rápido).
    if (!skipSelf && opaque(el)) return getComputedStyle(el).backgroundColor;
    const behind = document.elementsFromPoint(x, y).filter((e) => (skipSelf ? e !== el : true) && (e === el || !el.contains(e))).find(opaque);
    return getComputedStyle(behind || document.body).backgroundColor;
  };
  const label = (el) => (el.textContent || el.name || el.id || "").trim().slice(0, 30) || el.className;
  const bad = [];
  for (const el of document.querySelectorAll("body *")) {
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!own || el.closest("[disabled], svg, option, #toast:not(.show)")) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || r.bottom < 0 || r.top > innerHeight) continue;
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (!top || !(top === el || el.contains(top) || top.contains(el))) continue;  // coberto (ex.: pela folha)
    const cs = getComputedStyle(el), size = parseFloat(cs.fontSize), bold = Number(cs.fontWeight) >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const got = ratio(cs.color, bgAt(el, r.left + r.width / 2, r.top + r.height / 2));
    if (got < need) bad.push(`${el.tagName} "${label(el)}" ${got.toFixed(2)} < ${need}`);
  }
  for (const el of document.querySelectorAll("input:not([type=hidden]), select, textarea")) {
    const r = el.getBoundingClientRect();
    if (!r.width || r.bottom < 0 || r.top > innerHeight || document.activeElement === el) continue;
    const top = document.elementFromPoint(r.left + 2, r.top + r.height / 2);
    if (!top || !(top === el || el.contains(top))) continue;
    const got = ratio(getComputedStyle(el).borderLeftColor, bgAt(el, r.left - 3, r.top + r.height / 2, true));
    if (got < 3) bad.push(`borda de ${el.tagName} "${label(el)}" ${got.toFixed(2)} < 3`);
  }
  return [...new Set(bad)];
}"""


def audit(page, where):
    page.wait_for_timeout(300)  # fim das animações de entrada
    bad = page.evaluate(AUDIT)
    assert not bad, f"{where}: contraste insuficiente:\n" + "\n".join(bad)


@pytest.mark.parametrize("width", [390, 1280])
def test_todo_texto_das_telas_tem_contraste_suficiente(page, api, width):
    low, ok = api.product(qty=1), api.product(qty=0)
    api.product(qty=9)
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/")
    expect(page.locator(".item").first).to_be_visible()
    audit(page, "Estoque")
    for tab in ("alerts", "scan", "history", "more"):
        page.locator(f'nav.tabs [data-tab="{tab}"]').click()
        page.wait_for_load_state("networkidle")
        audit(page, tab)
    page.locator('nav.tabs [data-tab="scan"]').click()  # leitura em sequência com peça e código desconhecido
    page.get_by_role("button", name="Leitura em sequência").click()
    for code in (api.product(barcode=unique_barcode())["barcode"], unique_barcode()):
        page.fill("#code", code)
        page.press("#code", "Enter")
    expect(page.locator("#batch .unknown")).to_be_visible()
    page.locator("body").click(position={"x": 2, "y": 2})
    audit(page, "leitura em sequência")
    page.get_by_role("button", name="Uma peça por vez").click()
    page.locator('nav.tabs [data-tab="stock"]').click()
    for p in (low, ok):
        page.locator(f'[data-open="{p["id"]}"]').click()
        for t in ("out", "in", "adjust"):
            page.locator(f'[data-type="{t}"]').click()
            audit(page, f"folha da peça ({t})")
        page.get_by_text("Editar dados da peça").click()
        audit(page, "edição da peça")
        page.keyboard.press("Escape")


def test_login_tem_contraste_suficiente(browser, base_url):
    ctx = browser.new_context(base_url=base_url, viewport={"width": 390, "height": 800})
    page = ctx.new_page()
    page.goto("/")
    page.fill('input[name="username"]', "ninguem")
    page.fill('input[name="password"]', "errada")
    page.get_by_role("button", name="Entrar").click()
    expect(page.locator("#autherr .err")).to_be_visible()
    page.locator("body").click(position={"x": 5, "y": 5})  # tira o foco do campo
    audit(page, "login")
    ctx.close()

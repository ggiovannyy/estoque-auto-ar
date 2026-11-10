"""Identidade visual da oficina: logo no login e no cabeçalho, cores com contraste legível."""
import pytest
from playwright.sync_api import expect

# Contraste WCAG entre a cor do texto e o primeiro fundo opaco que aparece atrás dele na tela
# (pela posição, não pelo elemento pai: a barra lateral é o <header>, desenhado atrás do <nav>).
CONTRAST = """(el) => {
  const rgb = (c) => c.match(/[\\d.]+/g).map(Number);
  const opaque = (e) => { const c = rgb(getComputedStyle(e).backgroundColor); return c.length < 4 || c[3] === 1; };
  const lum = ([r, g, b]) => [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
    .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
  const r = el.getBoundingClientRect();
  const behind = document.elementsFromPoint(r.left + r.width / 2, r.top + r.height / 2)
    .filter((e) => e === el || !el.contains(e)).find(opaque);
  const a = lum(rgb(getComputedStyle(el).color)), b = lum(rgb(getComputedStyle(behind || document.body).backgroundColor));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}"""


def logo_loaded(img):
    expect(img).to_be_visible()
    assert img.evaluate("(i) => i.complete && i.naturalWidth > 0"), "a imagem da logo não carregou"
    return img.evaluate("(i) => new URL(i.currentSrc).pathname")


@pytest.mark.parametrize("width", [390, 1280])
def test_login_mostra_so_a_logo_da_oficina(browser, base_url, width):
    ctx = browser.new_context(base_url=base_url, viewport={"width": width, "height": 800})
    page = ctx.new_page()
    page.goto("/")

    assert logo_loaded(page.locator(".login img[alt='Maxx Auto Ar']")) == "/static/logo.png"
    expect(page.get_by_text("Controle de estoque")).not_to_be_in_viewport()
    # Para o leitor de tela, o título continua dizendo o que é o sistema.
    expect(page.get_by_role("heading", level=1)).to_have_accessible_name("Maxx Auto Ar Controle de estoque")
    ctx.close()


def test_cabecalho_do_celular_usa_a_logo_sem_o_slogan(phone):
    phone.goto("/")
    assert logo_loaded(phone.locator("header.top img[alt='Maxx Auto Ar']")) == "/static/logo-sem-slogan.png"


def test_barra_lateral_do_computador_usa_a_logo_inteira(page):
    page.goto("/")
    assert logo_loaded(page.locator("header.top img[alt='Maxx Auto Ar']")) == "/static/logo.png"


def test_botao_principal_tem_contraste_legivel(page):
    page.goto("/")
    fab = page.locator('[data-act="new"]')
    expect(fab).to_be_visible()
    assert fab.evaluate(CONTRAST) >= 4.5


def test_rotulos_da_barra_lateral_tem_contraste_legivel(page):
    page.goto("/")
    for tab in ("stock", "scan"):  # sem e com aba ativa
        page.locator(f'nav.tabs [data-tab="{tab}"]').click()
        for label in page.locator("nav.tabs button").all():
            text = label.locator("b") if label.locator("b").count() else label
            ratio = text.evaluate(CONTRAST)
            assert ratio >= 4.5, f"'{label.inner_text()}' com contraste {ratio:.2f}"

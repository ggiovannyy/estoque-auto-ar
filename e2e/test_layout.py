"""Layout: nada vaza para os lados no celular e cada tamanho de tela usa bem o espaço."""
import json

import pytest
from playwright.sync_api import expect

# No celular emulado o navegador alarga a área de layout até caber o conteúdo (innerWidth cresce junto):
# compara com a largura da tela.
WIDTH = "() => document.documentElement.scrollWidth"


@pytest.mark.parametrize("tab", ["stock", "alerts", "scan", "history", "more"])
def test_nenhuma_aba_rola_para_os_lados_no_celular(phone, tab):
    phone.set_viewport_size({"width": 360, "height": 740})
    # Pasta de backup como a da oficina: caminho longo, com trechos sem espaço para quebrar a linha.
    long_dir = r"C:\Users\atendimento\OneDrive\Backup_Estoque_Maxx_Auto_Ar_Campo_Mourao_copias_diarias_do_sistema"
    phone.route("**/api/backup", lambda r: r.fulfill(content_type="application/json",
                                                     body=json.dumps({"last_at": None, "dir": long_dir})))
    phone.goto("/")
    phone.locator(f'nav.tabs [data-tab="{tab}"]').click()
    if tab == "more":
        expect(phone.locator("#backupbox small")).to_be_visible()  # o caminho da pasta (longo, sem espaços)
    width = phone.evaluate(WIDTH)
    assert width <= 360, f"a aba {tab} rola para os lados ({width} px numa tela de 360)"


@pytest.mark.parametrize("width", [360, 1280])
def test_nova_peca_fica_na_linha_da_busca_sem_cobrir_a_lista(browser, base_url, page, api, width):
    for _ in range(3):
        api.product(qty=7)
    page.set_viewport_size({"width": width, "height": 700})
    page.goto("/")
    new, search = page.get_by_role("button", name="Nova peça"), page.locator("#q")
    expect(new).to_be_visible()
    assert new.evaluate("(b) => getComputedStyle(b).position") != "fixed", "o botão flutua por cima da lista"
    nb, sb = new.bounding_box(), search.bounding_box()
    assert abs((nb["y"] + nb["height"] / 2) - (sb["y"] + sb["height"] / 2)) < 4, "não está na linha da busca"
    assert nb["height"] >= 44 and nb["x"] + nb["width"] <= width

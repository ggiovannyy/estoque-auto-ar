# Estoque Maxx Auto Ar

Sistema de controle de estoque de peças para a oficina **Maxx Auto Ar** (ar-condicionado automotivo). Roda **localmente
no computador da oficina** e é acessado também pelo celular no mesmo Wi-Fi.

**Antes de qualquer trabalho, leia `docs/CONTEXTO-PROJETO.md`**: requisitos do cliente (com a transcrição dos áudios),
arquitetura, decisões, histórico e a lista de pendências.

## Regras de trabalho

- **Responder sempre em português (pt-BR).**
- **Git:**
  - Branch nova, **um commit por mudança lógica** (refatoração separada de funcionalidade) e PR para a `main`.
  - Merge só quando o desenvolvedor pedir; depois do merge, excluir a branch.
- **Testes primeiro:** escrever o teste, vê-lo falhar, corrigir e vê-lo passar.
- **Verificar de verdade:** para mudança de interface, subir o servidor com `MAXX_DATA` temporário e testar no
  navegador. Dizer com clareza o que foi e o que **não** foi testado.
- **Clean code:** módulos com responsabilidade única, sem código morto, nomes claros. Não inflar o `app.py`: extrair
  módulo quando fizer sentido.

## Stack e arquivos

- Flask + SQLite (`data/estoque.db`, WAL) e HTML/CSS/JS puros, sem build.
- **Módulos:**
  - `app.py`: rotas `/api/*` e permissões.
  - `migrations.py`: esquema do banco em passos numerados (`MIGRATIONS`), versão em `PRAGMA user_version`.
  - `security.py`: senha, limitador de login, CSV e cabeçalhos.
  - `backup.py`: backup diário para a pasta do OneDrive ou do Google Drive.
  - `run.py`: certificado https autoassinado, backup e servidor.
- **Interface:** `static/app.js` e `static/app.css`. A câmera usa `static/vendor/html5-qrcode.min.js`.
- **Testes:** `tests/` (API, pytest) e `e2e/` (interface, Playwright, sobe o `run.py` com dados temporários).
  Mudança de interface ganha teste em `e2e/`.
- **Windows:** `iniciar.bat`, `instalar-inicio-automatico.bat` e `remover-inicio-automatico.bat`. Os `.bat` precisam
  ficar com **CRLF** (ver `.gitattributes`).

## Comandos

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium       # uma vez, para os testes de interface
pytest -q                                   # 87 testes da API (pasta tests/)
pytest -q e2e                               # 10 testes de interface no navegador (pasta e2e/)
python -m pyflakes app.py run.py backup.py security.py migrations.py tests/ e2e/
python run.py                               # https://localhost:8443 (padrão)
python run.py --http --port 8000            # sem https (câmera do celular não funciona)
```

- Variáveis de ambiente: `MAXX_DATA` (pasta de dados; use uma pasta temporária em testes) e `MAXX_BACKUP_DIR`.
- Dependências com versão **exata** em `requirements.txt`. Para atualizar uma, mude a versão, rode os testes e teste
  no navegador.

## Invariantes que não podem quebrar

- Mudança de esquema só por **um passo novo no fim de `MIGRATIONS`**, com teste de banco antigo subindo de versão.
  Nunca alterar, remover ou reordenar um passo existente: ele já rodou nos bancos da oficina.
- Movimentação de estoque roda em `BEGIN IMMEDIATE` (`record_move` exige transação aberta). Sem isso, há perda de
  quantidade com acessos simultâneos (`tests/test_concorrencia.py`).
- Primeiro acesso (`/api/setup`) só de 127.0.0.1/::1.
- A tela de login não exige 8 caracteres: senhas antigas mais curtas continuam valendo. O mínimo vale só para senha
  nova.
- Todo texto do usuário no `app.js` passa por `esc()`. O CSV passa por `csv_safe()`.
- A CSP permite apenas scripts do próprio sistema: não adicionar script inline nem CDN.

# Contexto do projeto: Estoque Maxx Auto Ar

> Documento de passagem de contexto. Resume tudo o que foi feito na primeira fase do projeto (em uma sessão do
> Claude Code na nuvem, em 06/11/2026) para continuar o trabalho em uma nova conversa rodando **no computador do
> desenvolvedor**. Leia inteiro antes de mexer no código.

---

## 1. Quem é quem

- **Desenvolvedor (usuário do Claude):** Giovanny, GitHub `ggiovannyy`. Fala português do Brasil; **sempre responder em
  português (pt-BR)**. Está desenvolvendo o sistema como serviço pago para o cliente.
- **Cliente:** oficina **Maxx Auto Ar** (ar-condicionado automotivo), da cidade do desenvolvedor. Hoje controla o
  estoque de forma desorganizada, sem planilha nem lista.
- **Repositório:** https://github.com/ggiovannyy/estoque-auto-ar (privado/pessoal do desenvolvedor). Branch principal: `main`.

---

## 2. O que o cliente pediu

### 2.1 Transcrição dos áudios do cliente

Transcrição automática feita com Whisper, revisada só onde estava claramente errada. "Like Systemas" pode não ser o nome
exato do sistema de notas.

**Áudio 1 (2 min 33 s):**
> A gente tem um sistema de emissão de nota, que é pela Like Systemas. É um sistema bem simples de emissão de nota, a
> gente usa isso pra peça. E a gente usa um de mão de obra, um sistema de mão de obra. Nesse sistema de peças, a gente
> cadastra o produto através do NCM, que é um código de peças. Normalmente peças que só mudam a marca, mas têm a mesma
> função, têm todas o mesmo NCM.
>
> Eu não sei o nível de complexidade, mas você vê o que dá pra fazer. Nós pagamos pra você, cobramos um valor que você
> achar justo. A ideia é cadastrar peça por peça, pelo código. Vamos por tipo: filtro. Uma aba dentro do sistema,
> "filtro de cabine". Lá eu digito o código do que eu preciso, ou digito o nome. Vendi, eu vou lá e dou baixa. Tenho
> um no estoque, dois no estoque, pra gente ter esse controle.
>
> Eu não tenho muita ideia, mas sei que você manja mais; às vezes você tem alguma ideia bacana. Mas é algo que separe
> **não por marca de carro**, que é muito abrangente — tem peça que serve num carro e noutro — mas **por tipo de peça**.
> Cadastrar por tipo de peça e pelo código dela. Quando chega a mercadoria, eu faço a conferência, o controlezinho,
> anoto e mando pro estoque. Vendeu uma, dou baixa.
>
> Tá muito desorganizado aqui, não tá dando certo. Você vê o que acha melhor: cobrar mensalmente, cobrar uma vez, fechar
> um pacotinho e ir ajudando a administrar. Nada muito difícil. Todas essas peças vêm com **código de barras**, e o
> código de barras já tem o código. É esse código que eu falo.

**Áudio 2 (20 s):**
> Ou, às vezes, não sei se dá pra fazer atrelado ao sistema de notas: quando faz a nota com o produto, já dá baixa. Mas
> acho que o mais certo é **semanalmente**, porque tem muito serviço que a gente vende **sem nota**.

### 2.2 Respostas do desenvolvedor às perguntas de requisito

- **Onde roda:** no **computador da oficina**, com acesso também **pelo celular** (mesmo Wi-Fi).
- **Quem usa:** o **dono e atendentes**, com logins diferentes.
- **Leitura de código de barras:** a oficina **já tem leitor** (USB), e a **câmera do celular** também deve funcionar.
- **Estoque inicial:** **não existe** planilha nem lista. O estoque será cadastrado do zero.
- **Alerta de estoque mínimo:** o cliente não pediu, mas o desenvolvedor quis. **Aviso quando a peça tiver 2 ou menos**,
  valor configurável.
- **Hospedagem:** foi discutido Firebase e hospedagem na nuvem. **Decisão: manter local** (seção 6).

### 2.3 Requisitos resultantes

| Requisito | Situação |
|---|---|
| Cadastro por **tipo de peça** (categoria), não por marca de carro | Feito |
| Código de barras como identificador; NCM como campo | Feito |
| Busca por código ou nome, dentro da categoria | Feito |
| Entrada (conferência da mercadoria) e saída (baixa manual) | Feito |
| Saída **sem depender da nota fiscal** (há venda sem nota) | Feito |
| Integração com o sistema de notas | **Não feito, de propósito** (cliente preferiu baixa manual/semanal) |
| Uso no computador e no celular | Feito |
| Leitor USB e câmera | Feito (câmera **não testada em celular real**) |
| Alerta de estoque baixo (≤ 2) | Feito |
| Vários usuários (dono e atendentes) | Feito |

---

## 3. Arquitetura

### 3.1 Visão geral

```
              Wi-Fi da oficina
┌──────────────────────┐        ┌──────────────┐
│ Computador da oficina│◄───────│ Celulares    │  navegador → https://192.168.x.x:8443
│  run.py (Flask)      │        └──────────────┘
│  data/estoque.db     │◄─────── navegador local → https://localhost:8443
└─────────┬────────────┘
          │ cópia diária automática
          ▼
   Pasta do OneDrive / Google Drive (sincronizada com a nuvem pelo próprio Windows)
```

- **Servidor:** o próprio computador da oficina roda o Flask (servidor embutido, `threaded=True`). Sem hospedagem nem
  custo mensal. Só funciona com o computador ligado e dentro da rede da oficina.
- **Banco:** SQLite, um arquivo em `data/estoque.db`, em modo **WAL**.
- **HTTPS:** obrigatório porque o navegador do celular só libera a câmera em contexto seguro. O `run.py` gera um
  **certificado autoassinado** (biblioteca `cryptography`, válido 10 anos, com o IP da rede no SAN) em `data/cert.pem`
  e `data/key.pem`. No primeiro acesso, o celular mostra "conexão não segura" e é preciso tocar em Avançado → Continuar.
- **Interface:** HTML, CSS e JS puros, sem build e sem framework, mobile-first. É um PWA simples (manifest e ícone),
  sem service worker.

### 3.2 Arquivos

| Arquivo | Linhas | Papel |
|---|---|---|
| `app.py` | ~586 | Aplicação Flask: esquema do banco, rotas `/api/*`, autenticação e permissões |
| `security.py` | ~88 | Regras sem dependência do Flask: senha mínima, `LoginThrottle`, `csv_safe`, cabeçalhos de segurança/CSP |
| `backup.py` | ~120 | Backup diário: `make_backup` (API de backup do SQLite), `prune_backups`, `default_backup_dir`, `BackupScheduler` |
| `run.py` | ~88 | Ponto de entrada: gera certificado, imprime endereços, liga cookie Secure, inicia backup e servidor |
| `static/index.html` | — | Casca da página |
| `static/app.js` | ~373 | Toda a interface (estado global `S`, `render()`, abas, folhas modais, leitura de código) |
| `static/app.css` | ~169 | Estilos (tokens de cor em `:root`) |
| `static/vendor/html5-qrcode.min.js` | — | Biblioteca de leitura por câmera, **v2.3.8, copiada localmente** (sem CDN) |
| `static/icon.svg`, `manifest.webmanifest` | — | Ícone e PWA |
| `iniciar.bat` / `iniciar.sh` | — | Cria `.venv`, instala dependências (reinstala quando `requirements.txt` muda) e roda `run.py` |
| `instalar-inicio-automatico.bat` / `remover-inicio-automatico.bat` | — | Liga ou desliga a abertura automática com o Windows (pasta Inicializar) |
| `requirements.txt` | — | Dependências com **versão exata** (inclusive as indiretas) |
| `requirements-dev.txt` | — | + `pytest==9.2.0`, `pyflakes==4.1.0` |
| `tests/` | ~570 | 69 testes pytest |
| `.claude/` | — | 16 skills, 6 comandos (`/addy-*`) e 3 agentes do Claude Code, adicionados pelo desenvolvedor |
| `.gitattributes` | — | `*.bat -text` (gravados com **CRLF**), `*.sh eol=lf` |
| `.gitignore` | — | `.venv/`, `data/`, `__pycache__/`, `*.pem` (e libera `.claude/`) |

### 3.3 Banco de dados (SQLite)

```sql
users      (id, name, username UNIQUE, password_hash, role 'dono'|'atendente', active)
categories (id, name UNIQUE NOCASE)                 -- tipos de peça; 11 categorias iniciais
products   (id, barcode UNIQUE, code, name, category_id, ncm, brand,
            qty CHECK(qty>=0), min_qty NULL=usa padrão, active, created_at)
movements  (id, product_id, type 'in'|'out'|'adjust', qty, delta, balance, note, user_id, created_at)
settings   (key, value)                             -- min_default = '2'
```

- **Categorias iniciais:** Filtro de cabine, Válvula, Compressor, Condensador, Evaporador, Mangueira, Gás
  refrigerante, Óleo, Sensor, Correia, Outros.
- **Alerta:** `qty <= COALESCE(min_qty, min_default)`.
- **Exclusão de peça é lógica:** `active=0` e `barcode=NULL`, o que libera o código de barras e preserva o histórico.
- **Não há mecanismo de migração:** só `CREATE TABLE IF NOT EXISTS`. Isso está nas pendências (seção 8).
- **Formato de data:** texto `YYYY-MM-DD HH:MM:SS`, hora local.

### 3.4 API (todas JSON; exigem login, exceto `state`, `setup` e `login`)

| Método e rota | Quem | O que faz |
|---|---|---|
| `GET /api/state` | todos | `setup_needed`, `setup_here`, `user`, `min_default` |
| `POST /api/setup` | só de 127.0.0.1/::1 e com o banco sem usuários | Cria o dono (primeiro acesso) |
| `POST /api/login` / `POST /api/logout` | todos | Sessão Flask (cookie assinado) |
| `GET/POST /api/categories`, `DELETE /api/categories/<id>` | logado; DELETE só dono | Categorias |
| `GET /api/products?q=&category=&low=1` | logado | Lista e busca; `low=1` traz só alertas |
| `GET /api/products/barcode/<código>` | logado | Busca por código de barras (404 se não existir) |
| `GET /api/products/<id>` | logado | Detalhe e últimas 15 movimentações |
| `POST /api/products`, `PUT /api/products/<id>` | logado | Cadastro (com `qty` inicial) e edição |
| `DELETE /api/products/<id>` | dono | Exclusão lógica |
| `POST /api/products/<id>/move` | logado | `{type: in|out|adjust, qty, note}` |
| `GET /api/summary` | logado | Totais e quantidade em alerta |
| `GET /api/movements?limit=` | logado | Histórico (máximo 500) |
| `GET /api/export.csv` | logado | Planilha (`;`, BOM UTF-8, protegida contra fórmulas) |
| `PUT /api/settings` | dono | `min_default` |
| `GET/POST /api/backup` | dono | Status do backup / fazer backup agora |
| `GET/POST /api/users`, `PUT /api/users/<id>` | dono | Usuários (criar, ativar/desativar, redefinir senha) |
| `POST /api/password` | logado | Trocar a própria senha |

### 3.5 Interface (abas)

- **Estoque:** resumo (peças, unidades, em alerta), busca, filtros por categoria, lista agrupada por categoria e
  botão "+ Nova peça".
- **Alertas:** peças com estoque ≤ mínimo. Busca **sempre** `/products?low=1`, independente do filtro da aba Estoque.
- **Escanear:** campo para o leitor USB (o leitor "digita" o código e manda Enter) e botão de câmera (`html5-qrcode`
  com `BarcodeDetector` quando disponível). Se a peça existe, abre a folha de movimentação; se não existe, abre o
  cadastro com o código preenchido.
- **Histórico:** últimas 100 movimentações.
- **Mais:** exportar CSV; mínimo padrão (dono); **Backup** (dono: última cópia, pasta, "Fazer backup agora" e aviso
  "Atrasado" com mais de 48 h); categorias; usuários (dono); trocar senha; sair.
- **Folha da peça:** Saída, Entrada ou Contagem, com stepper, observação, últimas movimentações e edição de dados.
- **Design:** azul-petróleo `#0b2b3c`, fundo gelo `#eef5f7`, ação ciano `#0e9db9`, alerta âmbar `#f5a000`, zerado
  vermelho `#c93a26`. Fontes: Barlow Semi Condensed (títulos) e Barlow (texto), do Google Fonts, com fonte do sistema
  como reserva se não houver internet. No desktop (≥ 900px) a navegação vira barra lateral.

---

## 4. Segurança e integridade (o que já está garantido)

- **Concorrência:** movimentações usam `BEGIN IMMEDIATE` antes de ler o saldo (`record_move` exige transação aberta),
  com conexão `timeout=15` e WAL. Antes da correção, 300 entradas em paralelo davam estoque 13, e 400 saídas sobre 50
  peças eram todas aceitas. Testado em `tests/test_concorrencia.py`.
- **Login:** bloqueio de 5 min depois de 5 erros por (IP, usuário) ou 20 erros por IP, com janela de 15 min (resposta
  HTTP 429). Fica em memória (reiniciar o sistema zera).
- **Senha mínima de 8** caracteres para senhas **novas**. Senhas antigas mais curtas continuam entrando, e a tela de
  login **não** exige 8. Houve uma regressão nisso, já corrigida no commit `500cb55`.
- **Primeiro acesso só local:** o `/api/setup` aceita apenas 127.0.0.1/::1. Pela rede, a tela pede para fazer o
  primeiro acesso no computador.
- **CSV:** textos começando com `= + - @ \t \r` recebem `'` na frente (`csv_safe`).
- **Cabeçalhos:**
  - CSP com `script-src 'self'`; `style-src` permite `'unsafe-inline'` porque os templates usam `style="..."`.
  - Fontes do Google liberadas.
  - `X-Frame-Options DENY`, `nosniff`, `Referrer-Policy same-origin` e `Permissions-Policy camera=(self)`.
  - API com `Cache-Control: no-store`.
- **Cookie:** `HttpOnly`, `SameSite=Lax` e `Secure` quando roda em https. A chave secreta fica em `data/secret.key`
  (0600).
- **Escape de HTML** com `esc()` em todo texto vindo do usuário no `app.js`.
- **CSRF:** mitigado por SameSite=Lax mais o corpo JSON (`get_json` exige `Content-Type: application/json`).

---

## 5. Backup

- **Cópia diária automática:** o `BackupScheduler`, iniciado pelo `run.py`, faz uma cópia ao abrir o sistema se a
  última tiver mais de 24 h, e depois confere de hora em hora. Mantém as **30** mais recentes.
- **Arquivos:** `estoque-AAAA-MM-DD_HHMMSS.db`, gerados com a API de backup do SQLite (inclui o conteúdo do `-wal`).
  O arquivo é gravado como `.tmp` e depois renomeado.
- **Destino**, em ordem de prioridade:
  1. `MAXX_BACKUP_DIR`, se definido. No `iniciar.bat` há uma linha comentada para o Google Drive:
     `G:\Meu Drive\Backup Estoque Maxx`.
  2. OneDrive do Windows (variáveis `OneDrive`, `OneDriveConsumer`, `OneDriveCommercial`) → `...\Backup Estoque Maxx`.
  3. `data/backups`, só local. **Não protege contra perda do computador.**
- O sistema **não guarda senha de nuvem**: quem sincroniza é o OneDrive ou o Google Drive instalado no Windows.
- **Restaurar:** fechar o sistema, apagar `data\estoque.db`, `-wal` e `-shm`, copiar o backup para `data\estoque.db` e
  abrir de novo. Restauração testada.
- **Recomendação ao instalar:** usar o OneDrive com uma conta **da oficina** (5 GB grátis bastam, porque o banco tem
  poucos MB).

---

## 6. Decisões tomadas (e por quê)

| Decisão | Motivo |
|---|---|
| **Rodar local** (computador da oficina), não na nuvem | O cliente descreveu uso interno; custo zero; funciona sem internet; menor exposição |
| **Não usar Firebase** | O plano gratuito (Spark) não roda o servidor Python. Seria reescrever o backend (Firestore, Auth, Security Rules), depender de internet, ter cotas diárias (~50 mil leituras / 20 mil gravações por dia, a confirmar) e o backup automático exige plano pago. Fica como possível "fase 2" se o cliente quiser acesso de fora |
| Se precisar de acesso de fora no futuro | Preferir **Tailscale** (mantém tudo local) ou hospedagem Python (ex.: PythonAnywhere). Na nuvem, considerar trocar SQLite por PostgreSQL |
| SQLite em vez de banco servidor | Poucos usuários e poucas mil peças; nada para instalar ou manter |
| Servidor embutido do Flask | Suficiente para a oficina; `waitress` não suporta SSL, e o https é necessário para a câmera |
| JS puro sem build | Manutenção simples, nada para compilar na oficina |
| `html5-qrcode` copiado localmente | Funciona sem CDN e sem internet. A biblioteca está sem manutenção desde 2023; avaliar `BarcodeDetector` nativo no futuro |
| Sem integração com o sistema de notas | O próprio cliente preferiu baixa manual, porque há venda sem nota |
| Categorias por tipo de peça | Pedido explícito do cliente |

---

## 7. Histórico do trabalho (commits na `main`)

```
929a1b5 Merge PR #2: backup na nuvem, início automático, primeiro acesso local e cabeçalhos de segurança
0e1cf7e Trata erro do SQLite no botao de backup manual
670d4eb Abre o sistema sozinho com o Windows e corrige fim de linha dos .bat
fb4f356 Adiciona backup automatico diario para a nuvem
a60992a Fixa as versoes exatas das dependencias
06737b8 Permite o primeiro acesso so no computador da oficina
170d655 Adiciona cabecalhos de seguranca e cookie seguro em https
628afba Extrai regras de seguranca para security.py
7a7e5d4 Merge PR #1: corrige itens críticos da revisão
500cb55 Nao exige 8 caracteres na tela de login
cca6a66 Neutraliza formulas na planilha exportada
706979e Limita tentativas de login e exige senha de 8 caracteres
610a9e8 Mostra todos os alertas mesmo com busca ativa no estoque
e9fc952 Corrige perda de quantidade em movimentacoes simultaneas
7bf9555 Adiciona testes automatizados da API
c8ed1aa Adiciona skills do Claude Code para as sessoes na nuvem   (feito pelo desenvolvedor)
a97e956 Sistema de estoque Maxx Auto Ar
```

**Etapas:**
1. Levantamento de skills; transcrição dos áudios; requisitos.
2. Primeira versão completa (`a97e956`).
3. Revisão com `/addy-review` (5 eixos). Os itens 1 a 5 foram corrigidos no PR #1, com testes escritos antes de cada
   correção e verificação por mutação.
4. "Itens rápidos" no PR #2 (backup, início automático, primeiro acesso local, cabeçalhos, versões fixas, CRLF).

**PRs:** [#1](https://github.com/ggiovannyy/estoque-auto-ar/pull/1) e
[#2](https://github.com/ggiovannyy/estoque-auto-ar/pull/2), ambos juntados à `main`.

---

## 8. Pendências

### 8.1 Imediatas (testes na máquina do desenvolvedor e na oficina)

- [ ] **Rodar na máquina Windows do desenvolvedor.**
  - Ela tem o **Python Install Manager** (instalador novo do python.org, comando `py`), versão 26.4.
  - **Ainda não foi confirmado** se há um runtime instalado: rodar `py list`. Se vier vazio, `py install 3.13`.
  - O `iniciar.bat` usa `python -m venv`. Se o alias `python` não funcionar com o Install Manager, adaptar o `.bat`
    para tentar `py -3.13` como alternativa.
- [ ] **Liberar o Python no Firewall do Windows** ("Redes privadas"), senão o celular não conecta.
- [ ] **Testar os `.bat` no Windows.** Nunca foram executados: `iniciar.bat`, `instalar-inicio-automatico.bat` e
  `remover-inicio-automatico.bat`.
- [ ] **Testar a câmera em celular real** (Android e iPhone). Confirmar o fluxo do certificado autoassinado,
  principalmente no iPhone/Safari.
- [ ] **Testar o leitor USB real.** Confirmar que envia Enter. Ver também a divergência UPC-A (12 dígitos) × EAN-13
  (13 dígitos) entre câmera e leitor (item 15 abaixo).
- [ ] **Configurar o OneDrive ou o Google Drive** no computador da oficina e confirmar o backup indo para a nuvem.
- [ ] **Reservar IP fixo** (reserva DHCP) para o computador da oficina no roteador.
- [ ] **Demonstrar ao cliente e validar.**
- [ ] Na instalação da oficina, usar uma cópia **sem** a pasta `data/` dos testes.
- [ ] **Excluir as branches já juntadas no GitHub** (`fix/revisao-itens-1-5`, `melhorias/itens-rapidos`). A sessão na
  nuvem não tinha permissão; dá para excluir pelo botão "Delete branch" de cada PR.

### 8.2 Itens restantes da revisão de código (Optional / Nit)

Os itens 1 a 8 já estão resolvidos (1-5 no PR #1; 6, 7 e 8 no PR #2). Faltam:

| # | Item | Sugestão |
|---|---|---|
| 9 | **Sem migração de banco** | `PRAGMA user_version` + migrações numeradas, **antes** da primeira atualização com dados reais |
| 10 | `movements.qty` tem dois significados (em `adjust` é a nova contagem) | `delta` + `balance` bastam; simplificar |
| 11 | Quantidade inicial inválida/negativa vira 0 em silêncio (`create_product`) | Retornar 400 |
| 12 | `handleCode` decide "peça nova" comparando o texto `"não cadastrada"` | `api()` expor o status HTTP e checar 404 |
| 13 | Ao fechar a folha (X/Esc) na aba Escanear, o foco não volta ao campo do leitor | Refocar `#code` em `closeSheet` |
| 14 | Busca recarrega 3 endpoints a cada tecla; `/api/products` sem paginação | Recarregar só produtos; paginar se passar de alguns milhares |
| 15 | UPC-A × EAN-13 podem não casar entre câmera e leitor | Normalizar para 13 dígitos ao gravar e buscar |
| Nit | `S.loaded` nunca lido; `tabs` + `order` redundantes; `formBody` sem ganho; HTML da linha de histórico duplicado; linhas muito longas no `app.js` | Limpeza |
| — | A correção da aba Alertas foi verificada com Playwright, mas **não há teste de frontend no repositório** | Adicionar testes e2e (há a skill `playwright-cli`) |
| — | Sem CI | GitHub Actions rodando `pytest` |

### 8.3 Operação e entrega

- Cadastro inicial do estoque (um dia escaneando prateleiras; a função Contagem ajuda).
- Guia de uma página e treinamento rápido dos atendentes.
- Definir como entregar atualizações (git pull, zip ou acesso remoto).

### 8.4 Ideias de fase 2 (o cliente não pediu)

- Relatório de saídas por período (ele falou em baixa "semanal").
- Preço de custo e valor total do estoque.
- Fornecedores e lista de compras gerada a partir dos alertas.
- Etiquetas com código de barras para peças sem código.
- Acesso remoto (Tailscale) ou versão em nuvem.

### 8.5 Comercial (decisão do desenvolvedor)

- Proposta de preço para o cliente: valor único, mensalidade ou pacote com suporte. Não definido.

---

## 9. Como rodar, testar e desenvolver

**Rodar (Windows):** dois cliques em `iniciar.bat`. Abrir `https://localhost:8443`; o primeiro acesso cria o dono.

**Rodar (Linux/Mac):** `./iniciar.sh`.

**Opções do `run.py`:**
- `--http`: HTTP na porta 8000, sem câmera no celular.
- `--port N`: escolhe a porta.

**Variáveis de ambiente:**
- `MAXX_DATA`: pasta de dados (padrão `./data`). Use uma pasta separada para testes.
- `MAXX_BACKUP_DIR`: pasta do backup.

**Testes:**

```bash
pip install -r requirements-dev.txt
pytest -q            # 69 testes, ~10 s
python -m pyflakes app.py run.py backup.py security.py tests/
```

- O `tests/conftest.py` aponta `MAXX_DATA` para uma pasta temporária e cria um banco novo por teste.
- Fixtures disponíveis: `owner`, `attendant`, `login_client`.
- Os limitadores de login são zerados a cada teste.

**Verificação no navegador:** foi feita com Playwright (scripts descartáveis), em celular simulado (390×844) e desktop
(1280×800). Para a câmera foi usado o Chromium com `--use-fake-device-for-media-stream`.

---

## 10. Como trabalhar neste projeto (preferências e práticas combinadas)

- **Idioma:** responder sempre em **português (pt-BR)**. O desenvolvedor reclamou quando a resposta veio em inglês.
- **Fluxo Git:**
  - Criar branch, fazer **um commit por mudança lógica** e abrir PR para a `main`.
  - O desenvolvedor pede o merge explicitamente. Depois do merge, ele quer a branch excluída.
  - Refatoração vai em commit separado de funcionalidade.
- **Mensagens de commit:** em português sem acentos (padrão usado até aqui), imperativo, com corpo explicando o quê e
  o porquê e como foi verificado.
- **Testes primeiro:** escrever o teste, **ver falhar**, corrigir e ver passar. Conferir com mutação nas regras
  críticas.
- **Verificar de verdade:** além do pytest, subir o servidor real (com `MAXX_DATA` temporário) e testar no navegador
  quando a mudança é de interface.
- **Relatar com honestidade:** o que foi testado e o que **não** foi (ex.: `.bat` sem Windows, câmera sem celular real).
- **Clean code:** módulos com responsabilidade única (`security.py`, `backup.py`), nada de código morto, nomes claros,
  comentários só para o porquê não óbvio. O `app.py` não deve crescer sem necessidade: extrair módulos quando fizer
  sentido.
- **Skills do projeto** (`.claude/`):
  - `test-driven-development`, `security-and-hardening`, `code-review-and-quality`, `frontend-ui-engineering`,
    `playwright-cli`, entre outras.
  - Comandos `/addy-spec`, `/addy-plan`, `/addy-build`, `/addy-test`, `/addy-review`, `/addy-code-simplify`.
  - Agentes `code-reviewer`, `security-auditor`, `test-engineer`.

---

## 11. Primeiros passos sugeridos na nova conversa

1. Ler este arquivo e o `README.md`.
2. Conferir o Python no Windows (`py list`; se vazio, `py install 3.13`) e rodar `iniciar.bat`. Adaptar o `.bat` se o
   comando `python` não funcionar com o Install Manager.
3. Rodar `pytest -q` na máquina local (esperado: 69 passed).
4. Fazer os testes da seção 8.1 que forem possíveis na máquina do desenvolvedor (computador e celular no mesmo Wi-Fi).
5. Depois, atacar o item 9 (migrações) antes de qualquer mudança de esquema, e seguir com os demais itens da 8.2.

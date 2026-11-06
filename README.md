# Estoque Maxx Auto Ar

Sistema de controle de estoque de peças, para usar no computador da oficina e no celular (mesmo Wi-Fi).

## Como iniciar

**Windows:** instale o Python (python.org, marcando *Add Python to PATH*) e dê dois cliques em `iniciar.bat`.
**Linux/Mac:** `./iniciar.sh`

Na primeira vez ele instala o que precisa. Depois mostra os endereços:

- no computador: `https://localhost:8443`
- no celular (conectado ao mesmo Wi-Fi): o endereço `https://192.168.x.x:8443` que aparece na tela

No primeiro acesso, crie o usuário do dono. Depois, em **Mais → Usuários**, cadastre os atendentes.

> **Câmera no celular:** navegadores só liberam a câmera em conexão segura (https). O sistema gera um certificado próprio;
> na primeira vez o celular avisa "conexão não segura". Toque em **Avançado → Continuar** (uma vez só).
> Para o computador ligar sozinho o sistema, coloque um atalho do `iniciar.bat` na pasta *Inicializar* do Windows.
> Dica: reserve um IP fixo para o computador no roteador, para o endereço do celular não mudar.

## Como usar

| Ação | Onde |
|---|---|
| Ver estoque, buscar por nome/código/marca, filtrar por tipo de peça | **Estoque** |
| Ler código de barras (leitor USB ou câmera), dar entrada/saída ou cadastrar peça nova | **Escanear** |
| Peças com estoque baixo ou zerado | **Alertas** (aviso quando quantidade ≤ mínimo; padrão **2**) |
| Quem mexeu em quê e quando | **Histórico** |
| Mínimo padrão, categorias, usuários, exportar planilha | **Mais** |

- **Saída** funciona sem nota fiscal (o estoque não depende do sistema de notas).
- **Contagem** serve para corrigir o estoque depois de conferir as prateleiras; fica registrada no histórico.
- O mínimo de cada peça pode ser diferente do padrão (em *Editar dados da peça*).
- Peças são organizadas por **tipo** (filtro de cabine, válvula, etc.), não por marca de carro; o NCM é um campo da peça.

## Backup

Todos os dados ficam na pasta `data/` (arquivo `estoque.db`). Copie essa pasta de vez em quando para um pendrive/nuvem.

## Detalhes técnicos

Flask + SQLite, interface em JavaScript puro (sem build). Leitura por câmera com `html5-qrcode` (incluída em `static/vendor`).
Para testes use um banco separado: `MAXX_DATA=/tmp/teste python run.py`.

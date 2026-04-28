# CDN — Cria da Natureza

Plataforma de gestão interna para o negócio de cosméticos naturais e veganos **Cria da Natureza**.  
Backend em Flask + SQLite com renderização server-side via Jinja2. Sem frameworks de frontend.

---

## Estrutura do projeto

```
criadanatureza-main/
│
├── backend/
│   ├── main.py                      ← Ponto de entrada (python main.py → porta 8000)
│   ├── cdn.db                       ← Banco SQLite (criado automaticamente)
│   ├── .env                         ← Credenciais (ADMIN_USERNAME, ADMIN_PASSWORD, CDN_SECRET_KEY)
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py              ← create_app(): inicializa Flask, DB, blueprints
│       ├── database.py              ← Engine SQLAlchemy, SessionLocal, get_db()
│       ├── models.py                ← Todos os modelos ORM (19 tabelas)
│       └── blueprints/
│           ├── auth.py              ← Login/logout, decoradores login_required / admin_required
│           ├── dashboard.py         ← Dashboard admin: KPIs, alertas de estoque, gráfico mensal
│           ├── estoque.py           ← CRUD de produtos, ajuste de estoque, upload de imagens
│           ├── parceiros.py         ← CRUD de parceiros, envios, devoluções, aprovações
│           ├── financeiro.py        ← Fluxo de caixa, visão admin e visão parceiro
│           ├── configuracoes.py     ← Categorias, QR codes, gerenciamento de usuários
│           ├── loja.py              ← Vitrine pública, carrinho (sessão), geração de PreVenda
│           ├── caixa.py             ← Leitura de QR, aplicação de desconto, confirmação de venda
│           └── parceiro_area.py     ← Área restrita do parceiro: painel, catálogo, financeiro
│
├── frontend/
│   ├── css/                         ← base.css, layout.css, components.css (servidos em /static/css/)
│   └── landing/                     ← Páginas estáticas de divulgação (servidas em /landing/)
│
└── README.md
```

> **Por que os HTML ficam no backend?**  
> Os arquivos em `backend/app/templates/` são **templates Jinja2** — o Flask os processa no servidor,
> substituindo `{{ variavel }}` e `{% for %}` antes de enviar ao navegador.  
> O diretório `frontend/` contém apenas arquivos verdadeiramente estáticos (CSS, landing pages).

---

## Como tudo se conecta

```
Cliente (navegador)
        │
        │  HTTP porta 8000
        ▼
Flask  (backend/main.py → create_app())
        │
        ├── /login, /logout              → auth.py       (sessão Flask)
        ├── /                            → dashboard.py  (admin only)
        ├── /estoque                     → estoque.py    (admin only)
        ├── /parceiros                   → parceiros.py  (admin only)
        ├── /financeiro                  → financeiro.py (admin + parceiro)
        ├── /configuracoes               → configuracoes.py (admin only)
        │
        ├── /loja                        → loja.py       (público, sem login)
        │       └── /loja?p=<id>         → catálogo específico do parceiro
        │
        ├── /caixa                       → caixa.py      (admin + parceiro)
        │       └── /caixa/pedido/<tok>  → confirma PreVenda → cria VendaFinal
        │
        └── /meu-painel, /meu-catalogo   → parceiro_area.py (parceiro only)
                └── /meu-financeiro      → financeiro.py (visão parceiro)
        │
        ▼
SQLite (backend/cdn.db)
```

---

## Fluxo de venda por QR Code

```
1. Cliente acessa /loja?p=<parceiro_id>
2. Monta carrinho → POST /loja/finalizar
3. PreVenda criada com token único (expira em 30 min)
4. Cliente vê QR Code com link /caixa/pedido/<token>
5. Operador (parceiro ou admin) lê o QR no caixa
6. Operador aplica descontos por produto (opcional)
7. POST /caixa/pedido/<token>/confirmar → transação atômica:
   - Cria VendaFinal + ItemVendaFinal (snapshot histórico)
   - Para venda direta: desconta produto.quantidade
   - Para venda de parceiro: NÃO desconta (estoque já foi movido no envio)
   - Cria MovimentacaoFinanceira de entrada
   - Cria MovimentacaoFinanceira de comissão (saída) se parceiro tiver % configurado
8. Redireciona para recibo
```

---

## Modelo consignado (parceiro)

O sistema implementa consignação:

| Evento | Efeito no estoque | Efeito financeiro |
|--------|-------------------|-------------------|
| Admin envia produtos ao parceiro | `produto.quantidade −= qty` (sai do almoxarifado) | Nenhum |
| Parceiro vende via QR + caixa | Nenhum (estoque do almoxarifado não muda) | Entrada de receita + saída de comissão |
| Parceiro devolve produtos | `produto.quantidade += qty` (volta ao almoxarifado) | Nenhum |

**Cálculo de estoque do parceiro (em mãos):**
```
em_maos = total_enviado − total_vendido_via_VendaFinal − total_devolvido_confirmado
```

**Cálculo de comissão:**
```
comissao = valor_total_liquido × comissao_percentual
```
O parceiro fica com `comissao_percentual` % da receita; o admin recebe o restante.

---

## Instalação e execução

### 1. Pré-requisitos

- Python 3.10 ou superior

### 2. Instalar dependências

```bash
cd criadanatureza-main/backend
pip install -r requirements.txt
```

### 3. Configurar variáveis de ambiente

Crie o arquivo `backend/.env`:

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=suasenhaaqui
CDN_SECRET_KEY=chave-aleatoria-longa
```

### 4. Iniciar o servidor

```bash
cd criadanatureza-main/backend
python main.py
```

O banco `cdn.db` é criado automaticamente. Na primeira execução, o usuário admin é criado a partir do `.env`.

### 5. Acessar o sistema

```
http://localhost:8000
```

---

## Rotas disponíveis

| URL | Acesso | Descrição |
|-----|--------|-----------|
| `/login` | Público | Tela de login |
| `/` | Admin | Dashboard com KPIs e gráfico mensal |
| `/estoque` | Admin | Gestão de produtos e estoque |
| `/parceiros` | Admin | Lista e detalhe de parceiros |
| `/financeiro` | Admin + Parceiro | Fluxo de caixa (visão conforme role) |
| `/configuracoes` | Admin | Categorias, usuários, QR codes |
| `/caixa` | Admin + Parceiro | Pedidos pendentes e histórico de vendas |
| `/loja` | Público | Catálogo e carrinho do cliente |
| `/loja?p=<id>` | Público | Catálogo específico de um parceiro |
| `/meu-painel` | Parceiro | Dashboard do parceiro (vendas, estoque) |
| `/meu-catalogo` | Parceiro | Pré-visualização do catálogo + devolução |
| `/meu-financeiro` | Parceiro | Comissões e repasses do parceiro |
| `/minhas-configuracoes` | Parceiro | Alterar senha |

---

## Funcionalidades entregues

- [x] Autenticação com roles: **admin** (acesso total) e **parceiro** (acesso restrito)
- [x] Dashboard admin: KPIs mensais, alertas de estoque mínimo, gráfico 6 meses
- [x] Gestão completa de produtos: criar, editar, excluir, upload de imagem
- [x] Ajuste manual de estoque (entrada / saída / ajuste absoluto)
- [x] Cadastro de parceiros com % de comissão configurável
- [x] Envio de produtos ao parceiro (desconta almoxarifado, adiciona ao catálogo)
- [x] Fluxo QR: cliente monta carrinho → PreVenda → QR Code → caixa confirma
- [x] Caixa com aplicação de desconto por produto em tempo real (JS live)
- [x] Comissão calculada automaticamente ao confirmar venda de parceiro
- [x] Área do parceiro: painel de vendas com filtro por período (hoje / semana / mês / personalizado)
- [x] Catálogo do parceiro: exibe estoque real em mãos (não o total enviado)
- [x] Solicitação de devolução pelo parceiro → aprovação/rejeição pelo admin
- [x] Financeiro admin: margem por venda, breakdown por parceiro
- [x] Financeiro parceiro: suas vendas, sua comissão, repasses à empresa
- [x] Backfill automático: corrige comissões e custos de produção em registros antigos
- [x] Auto-cancelamento de pedidos expirados ao abrir o caixa
- [x] Parceiro vê apenas suas próprias vendas no histórico do caixa

---

## Design

**Paleta:**
- `#38a3a5` — Teal principal
- `#57cc99` — Verde
- `#22577a` — Azul escuro (sidebar)

**Princípios:** inspirado em Apple HIG — tipografia do sistema, espaçamento generoso, sombras sutis, bordas arredondadas, totalmente responsivo.

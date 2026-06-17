# Guia de Estudo — CDN (Cria da Natureza)

> Material para a prova. Foco em **como o sistema está estruturado** e em **como
> funcionam os templates Jinja** (o "Ginger" = **Jinja2**, a engine de templates
> do Flask). Tudo aqui foi extraído do código real do repositório.

---

## 0. O que é o projeto (resumo de 30 segundos)

Plataforma de **gestão interna** da Cria da Natureza (cosméticos naturais/veganos).
Centraliza **estoque, vendas, parceiras em consignação e financeiro**. Dois perfis:
**admin** (vê tudo) e **parceiro** (vê só a própria operação).

Stack: **Python + Flask + Jinja2 + SQLAlchemy + SQLite**, CSRF com Flask-WTF,
senhas com Werkzeug, deploy no **Render** com Gunicorn. Exportações em Excel
(openpyxl).

---

## 1. Arquitetura em camadas (o "desenho" geral)

```
                          NAVEGADOR (admin ou parceiro)
                                     │  HTTP
                                     ▼
        ┌───────────────────────────────────────────────────────────┐
        │                       FLASK  (create_app)                   │
        │                  backend/app/__init__.py                    │
        │                                                             │
        │   secret_key · CSRF · filtros Jinja (brl, localdt)          │
        │   context_processor (injeta usuario_atual em TODO template) │
        │   teardown (fecha a sessão do banco no fim do request)      │
        └───────────────────────────────────────────────────────────┘
              │ registra 12 blueprints (módulos de rotas)
              ▼
   ┌──────────────────────────── BLUEPRINTS ────────────────────────────┐
   │ auth · dashboard · estoque · parceiros · financeiro · configuracoes │
   │ caixa · parceiro_area · vendas · despesas · kpis · historico        │
   └─────────────────────────────────────────────────────────────────────┘
        │ chamam                       │ renderizam                │ leem/escrevem
        ▼                              ▼                           ▼
  ┌──────────────┐          ┌───────────────────┐        ┌──────────────────┐
  │  decorators  │          │  TEMPLATES Jinja  │        │  SQLAlchemy ORM  │
  │ login_req.   │          │  templates/*.html │        │  models.py       │
  │ admin_req.   │          │  (herdam de       │        │  database.py     │
  │ (auth.py)    │          │   base.html)      │        │  (SQLite cdn.db) │
  └──────────────┘          └───────────────────┘        └──────────────────┘
```

### O fluxo de uma requisição (pedido → resposta)

```
1. Navegador pede  GET /historico/vendas
2. Flask casa a URL com o blueprint "historico" (url_prefix="/historico")
3. O decorator @login_required confere a sessão (senão → /login)
4. A view consulta o banco via get_db() → SQLAlchemy
5. A view chama render_template("historico/vendas.html", vendas=..., ...)
6. Jinja monta o HTML: o filho "extends base.html", preenche os blocks
7. context_processor injeta usuario_atual; filtros |brl e |localdt formatam
8. HTML final volta pro navegador
```

---

## 2. Estrutura de pastas

```
criadanatureza/
├── backend/
│   ├── main.py                 ← ENTRYPOINT real: app = create_app()  (Gunicorn roda este)
│   ├── requirements.txt        ← flask, flask-wtf, sqlalchemy, qrcode, openpyxl...
│   └── app/
│       ├── __init__.py         ← create_app(): cria o Flask, filtros, CSRF, registra blueprints
│       ├── database.py         ← engine SQLite, SessionLocal, get_db()
│       ├── models.py           ← TODAS as tabelas (SQLAlchemy ORM)
│       ├── blueprints/         ← a lógica (as "rotas"/controllers)
│       │   ├── auth.py         ← login, logout, decorators de permissão
│       │   ├── dashboard.py    ← /painel (admin) e /apresentacao
│       │   ├── estoque.py      ← CRUD de produtos + movimentações
│       │   ├── parceiros.py    ← parceiras, envios, devoluções, comissão
│       │   ├── vendas.py       ← Nova Venda + recibo
│       │   ├── caixa.py        ← histórico de caixa + export Excel
│       │   ├── financeiro.py   ← entradas/saídas, fluxo de caixa
│       │   ├── despesas.py     ← despesas fixas/variáveis
│       │   ├── historico.py    ← vendas/recebimentos/pagamentos + parcelas
│       │   ├── kpis.py         ← indicadores
│       │   ├── configuracoes.py← categorias, usuários, métodos, pontos
│       │   ├── parceiro_area.py← /meu-painel, /meu-catalogo (visão parceiro)
│       │   └── _excel_export.py← helper p/ gerar planilhas (openpyxl)
│       └── templates/          ← os templates Jinja (a CAMADA DE VIEW)
│           ├── base.html       ← LAYOUT MÃE (sidebar + topbar) — admin/parceiro
│           ├── login.html, 403.html
│           ├── historico/      ← vendas.html, recebimentos.html, pagamentos.html
│           │   └── _filtro_mes.html   ← PARCIAL reutilizável (include)
│           ├── vendas/         ← nova.html, recibo.html
│           ├── caixa/          ← historico.html, recibo.html
│           ├── despesas/, loja/ (base_loja.html)...
│           └── ...
├── frontend/                   ← (LEGADO) HTML/CSS/JS estáticos + landings
│   ├── css/  (base, layout, components)  ← USADOS pelo Flask como /static
│   ├── landing/v1, v2, v3                ← páginas de venda servidas em /landing
│   └── html/, js/                        ← protótipo antigo (FastAPI) — não é o app atual
├── render.yaml                 ← config de deploy no Render (Blueprint)
└── DEPLOY.md / README.md
```

> ⚠️ **Pegadinha de prova:** existe um `backend/app/main.py` que usa **FastAPI** e
> uma pasta `routers/` + `frontend/html/`. **Isso é legado/protótipo.** O app que
> roda em produção é o **Flask** (`backend/main.py` → `create_app()`), conforme o
> `render.yaml` (`startCommand: gunicorn ... main:app`). Os CSS de `frontend/css`
> continuam sendo usados como `/static`.

---

## 3. Jinja2 — como os templates funcionam (o coração da prova)

Jinja é a engine de templates do Flask. Ela mistura **HTML** com **tags Jinja**:

| Sintaxe         | Para quê serve              | Exemplo no projeto                          |
|-----------------|-----------------------------|---------------------------------------------|
| `{{ ... }}`     | **Imprime** um valor        | `{{ usuario_atual.nome }}`                   |
| `{% ... %}`     | **Lógica** (if, for, block) | `{% if usuario_atual.is_admin %}`            |
| `{# ... #}`     | **Comentário** (some no HTML)| `{# Itens só para Admin #}`                  |
| `| filtro`      | **Transforma** o valor      | `{{ venda.valor_total_liquido | brl }}`      |

### 3.1 Herança de templates (`extends` + `block`) — o mecanismo central

A ideia: **um layout mãe** (`base.html`) define a "moldura" (sidebar, topbar,
rodapé) e deixa **buracos** marcados com `{% block %}`. Cada página filha
**preenche** esses buracos. Assim não se repete o menu em 20 arquivos.

```
                     base.html (LAYOUT MÃE)
   ┌──────────────────────────────────────────────────────────┐
   │ <head> {% block title %}{% endblock %} ... </head>        │
   │ ┌──────────┐ ┌─────────────────────────────────────────┐ │
   │ │ SIDEBAR  │ │ topbar: {% block page_title %}{%end%}    │ │
   │ │ (menu    │ │         {% block topbar_actions %}{%end%}│ │
   │ │  varia   │ │ ┌─────────────────────────────────────┐ │ │
   │ │  por     │ │ │  {% block content %}{% endblock %}  │ │ │
   │ │  perfil) │ │ │  ← AQUI entra o conteúdo da página   │ │ │
   │ └──────────┘ │ └─────────────────────────────────────┘ │ │
   │              └─────────────────────────────────────────┘ │
   └──────────────────────────────────────────────────────────┘
                              ▲   preenche os blocks
                              │
        historico/vendas.html (FILHO)
        ┌─────────────────────────────────────────┐
        │ {% extends "base.html" %}                │
        │ {% block title %}Histórico de Vendas{%…%}│
        │ {% block page_title %}…{% endblock %}     │
        │ {% block topbar_actions %}<form>…</form>  │
        │ {% block content %}<table>…</table>{%…%}  │
        └─────────────────────────────────────────┘
```

Exemplo real (`templates/historico/vendas.html`):

```jinja
{% extends "base.html" %}
{% block title %}Histórico de Vendas{% endblock %}
{% block page_title %}Histórico de Vendas{% endblock %}
{% block page_subtitle %}{{ vendas | length }} venda(s) em {{ "%02d"|format(mes) }}/{{ ano }}{% endblock %}

{% block content %}
  {% for venda in vendas %}
    <td>{{ venda.valor_total_liquido | brl }}</td>
  {% endfor %}
{% endblock %}
```

**Blocks definidos em `base.html`:** `title`, `head`, `topbar_left`,
`page_title`, `page_subtitle`, `topbar_actions`, `content`.
Cada página só sobrescreve os que precisa; o resto fica com o padrão.

### 3.2 Dois layouts mãe diferentes

- **`base.html`** → telas internas (admin/parceiro): sidebar + topbar + relógio.
- **`loja/base_loja.html`** → vitrine pública/loja: header com logo e carrinho,
  sem sidebar. (Templates da loja existem mas o fluxo de loja é parcial/legado.)

### 3.3 Parciais reutilizáveis (`{% include %}`)

Pedaços de HTML repetidos viram um arquivo `_nome.html` e são chamados com
`{% include %}`. Convenção: o `_` no início marca "parcial".

Exemplo: `templates/historico/_filtro_mes.html` é um formulário de filtro
mês/ano + botão Excel, reaproveitado em várias telas:

```jinja
{# recebe: action, mes, ano, meses_pt, export_url (opcional), extras (opcional) #}
<form method="GET" action="{{ action }}">
  {% for k, v in (extras or {}).items() %}
    <input type="hidden" name="{{ k }}" value="{{ v }}">
  {% endfor %}
  <select name="mes_num">
    {% for n in range(1, 13) %}
      <option value="{{ n }}" {% if n == mes %}selected{% endif %}>{{ meses_pt[n-1] }}</option>
    {% endfor %}
  </select>
  ...
</form>
```

> `extends` = herdar a moldura inteira. `include` = colar um pedacinho.

### 3.4 Filtros customizados (`|brl` e `|localdt`)

Registrados em `create_app()` (`__init__.py`):

```python
app.jinja_env.filters["brl"]     = _brl       # 1234.5  →  "R$ 1.234,50"
app.jinja_env.filters["localdt"] = _localdt   # datetime UTC → "17/06/2026 14:30" (fuso BRT -3)
```

Uso no template: `{{ valor | brl }}` e `{{ data | localdt }}`.
Além desses, usa-se filtros nativos do Jinja: `| length`, `"%02d"|format(mes)`.

### 3.5 Variáveis globais — `context_processor`

Para `usuario_atual` estar disponível em **todo** template sem precisar passar em
cada `render_template`, há um *context processor*:

```python
@app.context_processor
def _inject_usuario():
    return {"usuario_atual": usuario_para_template(get_usuario_atual())}
```

É por isso que `base.html` consegue fazer `{% if usuario_atual.is_admin %}` em
qualquer página. O `csrf_token()` (do Flask-WTF) também é global.

### 3.6 Menu condicional por perfil (admin vs parceiro)

Em `base.html`, a sidebar inteira é dividida por `if`:

```jinja
{% if usuario_atual and usuario_atual.is_admin %}
   <a href="/painel">Dashboard</a> ... (Estoque, Parceiros, Financeiro, KPIs...)
{% endif %}

{% if usuario_atual and not usuario_atual.is_admin %}
   <a href="/meu-painel">Dashboard</a> ... (Meu estoque, Meu financeiro...)
{% endif %}
```

E o **item ativo** do menu acende comparando uma variável que a view passa:

```jinja
<a href="/estoque" class="nav-item {% if active_page == 'estoque' %}active{% endif %}">
```

A view manda `render_template(..., active_page="estoque")`. Padrão simples e
muito usado na prova.

### 3.7 Mensagens flash

`base.html` exibe avisos de sucesso/erro que as views disparam com `flash()`:

```jinja
{% with messages = get_flashed_messages(with_categories=true) %}
  {% for category, message in messages %}
    <div class="alert alert-{{ category }}">{{ message }}</div>
  {% endfor %}
{% endwith %}
```

### 3.8 Resumo visual da "rede" de templates

```
base.html  ──extends──┬── login.html (na verdade não estende; é standalone)
                      ├── historico/vendas.html ──include──► historico/_filtro_mes.html
                      ├── historico/recebimentos.html ─include─► _filtro_mes.html
                      ├── historico/pagamentos.html  ──include─► _filtro_mes.html
                      ├── vendas/nova.html · vendas/recibo.html
                      ├── caixa/historico.html
                      ├── estoque.html · parceiros.html · financeiro.html
                      ├── despesas/index.html · kpis.html · configuracoes.html
                      └── parceiro_painel.html · parceiro_catalogo.html ...

base_loja.html (layout separado) ──► telas de loja/carrinho (parcial/legado)
```

---

## 4. Blueprints — como as rotas são organizadas

Um **Blueprint** é um "mini-app" Flask que agrupa rotas relacionadas. Cada
arquivo em `blueprints/` cria um `bp = Blueprint(nome, __name__, url_prefix=...)`
e o `create_app()` registra todos com `app.register_blueprint(bp)`.

```python
# historico.py
bp = Blueprint("historico", __name__, url_prefix="/historico")

@bp.route("/vendas")
@login_required
def vendas():
    ...
    return render_template("historico/vendas.html", vendas=..., active_page="historico_vendas")
```

Mapa das principais URLs:

| Blueprint       | prefixo         | exemplos de rota                         |
|-----------------|-----------------|------------------------------------------|
| auth            | (raiz)          | `/login`, `/logout`                      |
| dashboard       | (raiz)          | `/painel`, `/apresentacao`               |
| estoque         | `/estoque`      | `/estoque`, `/estoque/novo`              |
| parceiros       | `/parceiros`    | `/parceiros`, `/parceiros/<id>/envio`    |
| vendas          | `/vendas`       | `/vendas/nova`, `/vendas/<id>/recibo`    |
| caixa           | `/caixa`        | `/caixa`, `/caixa/export.xlsx`           |
| historico       | `/historico`    | `/historico/vendas`, `.../recebimentos`  |
| financeiro      | `/financeiro`   | `/financeiro`, `/financeiro/anual`       |
| despesas        | `/despesas`     | `/despesas`, `/despesas/nova`            |
| kpis            | `/kpis`         | `/kpis`                                  |
| configuracoes   | `/configuracoes`| categorias, usuários, métodos, pontos    |
| parceiro_area   | (raiz)          | `/meu-painel`, `/meu-catalogo`           |

---

## 5. Autenticação e papéis (decorators)

Em `auth.py`, dois "carimbos" protegem as rotas:

```python
@login_required   # exige estar logado (senão → /login)
@admin_required   # exige estar logado E role == "admin" (senão → 403)
```

- A sessão guarda só `usuario_id` (`session["usuario_id"]`).
- `get_usuario_atual()` recarrega o `Usuario` do banco a cada request.
- Senhas: `generate_password_hash` / `check_password_hash` (Werkzeug) — nunca em texto puro.
- O admin é (re)criado no boot a partir de `ADMIN_USERNAME` / `ADMIN_PASSWORD` (`_sync_admin`).
- **Isolamento de dados do parceiro:** nas consultas, quando `role != "admin"`
  filtra-se por `parceiro_id` (ex.: histórico de vendas só mostra as dele).

```
login (POST) → confere hash → session["usuario_id"] = id
            → admin?  redirect /painel
            → parceiro? redirect /caixa
```

---

## 6. Modelo de dados (SQLAlchemy / SQLite)

`models.py` define as tabelas como classes que herdam de `Base`. As relações
(`relationship`) ligam os objetos. Tabelas principais e como se conectam:

```
Usuario ──(parceiro_id)──► Parceiro
                              │
        ┌─────────────────────┼──────────────────────────┐
        ▼                     ▼                            ▼
      Envio               VendaFinal                   Devolucao
        │ itens             │ itens                       │ itens
        ▼                   ▼                             ▼
   ItemEnvio          ItemVendaFinal                 ItemDevolucao
        │                   │                             │
        └────────┐          │            ┌────────────────┘
                 ▼          ▼            ▼
              Produto ◄──(produto_id em todos os itens)
                 ▲  │
   Categoria ────┘  └─ MovimentacaoEstoque (entrada/saída/ajuste)

VendaFinal ──► MetodoRecebimento, PontoVenda, PreVenda (origem QR)
VendaFinal ──► ParcelaRecebimento (1+ parcelas a receber)
Despesa    ──► ParcelaPagamento   (1+ parcelas a pagar) ; DespesaFixa (modelo)
MovimentacaoFinanceira  ← entradas/saídas que alimentam o fluxo de caixa
PreVenda ──► ItemPreVenda  (carrinho gerado no catálogo, vira VendaFinal)
produtos_parceiros = tabela N:N (catálogo de cada parceira)
```

Conceitos-chave do domínio:

- **Estoque "em mãos" da parceira** = Σ enviado − Σ vendido − Σ devolvido
  (calculado em `vendas.py::_em_maos_parceiro`). Separado do almoxarifado central.
- **Comissão** = `valor_total_liquido × comissao_percentual` da parceira,
  lançada automaticamente como **Despesa** ("Comissão Parceiro") no momento da venda.
- **Parcelas:** toda venda gera ≥1 `ParcelaRecebimento`; toda despesa ≥1
  `ParcelaPagamento`. Reparceláveis. Marcar como pago/recebido atualiza o status.
- **Bruto / Desconto / Líquido** guardados na venda e em cada item.

---

## 7. Banco e sessão (database.py)

```python
engine        = create_engine("sqlite:///cdn.db", connect_args={"check_same_thread": False})
SessionLocal  = sessionmaker(bind=engine)
Base          = declarative_base()

def get_db():                      # 1 sessão por request, guardada em flask.g
    if "db" not in g: g.db = SessionLocal()
    return g.db
```

- `@app.teardown_appcontext` fecha a sessão no fim de cada request.
- Suporta também PostgreSQL via `DATABASE_URL` (corrige `postgres://`→`postgresql://`).
- No boot, `create_app()` roda: `create_all` (cria tabelas) → `_migrate_db`
  (ALTER TABLE para colunas novas) → `_sync_admin` → `_backfill_financeiro`
  (corrige dados legados). É uma "migração caseira", sem Alembic.

---

## 8. Fluxos de negócio importantes

### 8.1 Nova Venda (`vendas.py`)

```
GET  /vendas/nova   → lista produtos disponíveis (admin = estoque central;
                       parceiro = "em mãos"), métodos, pontos, parceiros
POST /vendas/nova   → valida estoque → cria VendaFinal + ItemVendaFinal
                    → se venda do almoxarifado: baixa estoque + MovimentacaoEstoque
                    → cria ParcelaRecebimento (1x) + MovimentacaoFinanceira (entrada)
                    → se tem parceira c/ comissão: cria Despesa "Comissão" + parcela
                    → redirect /vendas/<id>/recibo
```

### 8.2 Consignação com parceiras (`parceiros.py`)

```
Envio (admin manda produtos) → aumenta "em mãos" da parceira
Venda da parceira            → diminui "em mãos" + gera comissão
Solicitação de devolução     → parceira pede; admin confirma/rejeita
Devolução confirmada         → volta pro estoque central
```

### 8.3 Financeiro / Histórico

- `financeiro` e `kpis`: receita, custo, despesa, comissão, margem, fluxo de caixa.
- `historico`: três abas — **Vendas**, **Recebimentos** (a receber/recebido),
  **Pagamentos** (a pagar/pago) — todas com filtro por mês e export Excel.

---

## 9. Deploy (render.yaml + DEPLOY.md)

```
git push  →  Render detecta  →  build (pip install)  →  start (gunicorn main:app)
```

- `plan: starter` + **disco persistente** em `/data` (guarda `cdn.db` e uploads).
- Secrets setados no painel (não no arquivo): `CDN_SECRET_KEY`, `ADMIN_PASSWORD`.
- `healthCheckPath: /login`. Plano Free = dados voláteis + dorme após 15 min.

---

## 10. Checklist de revisão (provável cair na prova)

- [ ] Diferença `{{ }}` vs `{% %}` vs `{# #}`.
- [ ] `extends` + `block` (herança) e quais blocks o `base.html` define.
- [ ] `include` e o papel das parciais `_filtro_mes.html`.
- [ ] Filtros customizados `brl` e `localdt` (onde são registrados e o que fazem).
- [ ] `context_processor` injetando `usuario_atual` globalmente.
- [ ] `active_page` para destacar o item de menu.
- [ ] `get_flashed_messages` (mensagens flash).
- [ ] O que é um Blueprint e como `create_app` registra os 12.
- [ ] `@login_required` vs `@admin_required` e o isolamento por `parceiro_id`.
- [ ] Senhas com hash (Werkzeug), sessão guardando só `usuario_id`.
- [ ] Modelo de dados: Produto, Parceiro, VendaFinal/ItemVendaFinal, Parcelas.
- [ ] "Em mãos" = enviado − vendido − devolvido; comissão automática.
- [ ] `get_db()` por request + `teardown` fechando a sessão.
- [ ] Pegadinha: o app real é **Flask** (`backend/main.py`), FastAPI é legado.
```

# CDN — Cria da Natureza

Plataforma de gestão interna para o negócio de cosméticos naturais e veganos **Cria da Natureza**.

---

## Estrutura do projeto

```
CDN/
├── backend/                    ← Python (FastAPI + SQLite)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py             ← Aplicação principal, monta rotas e serve o frontend
│   │   ├── database.py         ← Conexão com o banco SQLite
│   │   ├── models.py           ← Tabelas do banco de dados (SQLAlchemy)
│   │   ├── routers/
│   │   │   ├── dashboard.py    ← Rota GET /api/dashboard
│   │   │   ├── estoque.py      ← Rotas /api/produtos e /api/categorias
│   │   │   ├── parceiros.py    ← Rotas /api/parceiros (envio/venda/devolução)
│   │   │   └── financeiro.py   ← Rotas /api/financeiro
│   │   └── schemas/
│   │       ├── produto.py      ← Validação de entrada/saída de dados de produtos
│   │       ├── parceiro.py     ← Validação de parceiros e movimentações
│   │       └── financeiro.py   ← Validação de transações financeiras
│   ├── cdn.db                  ← Banco de dados SQLite (criado automaticamente)
│   └── requirements.txt        ← Dependências Python
│
├── frontend/                   ← HTML + CSS + JS puro (sem frameworks)
│   ├── html/
│   │   ├── index.html          ← Dashboard principal
│   │   ├── estoque.html        ← Gestão de produtos e estoque
│   │   ├── parceiros.html      ← Listagem de parceiros/revendedores
│   │   ├── parceiro-detalhe.html ← Detalhe + histórico de um parceiro
│   │   ├── financeiro.html     ← Fluxo de caixa e transações
│   │   └── configuracoes.html  ← Categorias e informações do sistema
│   ├── css/
│   │   ├── base.css            ← Reset, variáveis CSS, utilitários
│   │   ├── layout.css          ← Sidebar, topbar, grid, responsividade
│   │   └── components.css      ← Todos os componentes reutilizáveis
│   └── js/
│       ├── api.js              ← Cliente de API centralizado + helpers (toast, modal, formatação)
│       ├── dashboard.js        ← Lógica do dashboard e gráfico de cashflow
│       ├── estoque.js          ← Listagem, criação, edição e ajuste de estoque
│       ├── parceiros.js        ← Listagem e cadastro de parceiros
│       ├── parceiro-detalhe.js ← Detalhe, envios, vendas e devoluções
│       └── financeiro.js       ← Transações e resumo financeiro
│
└── README.md
```

---

## Como conectar as partes

```
Navegador
    │
    │  HTTP (porta 8000)
    ▼
FastAPI (backend/app/main.py)
    │
    ├── /api/...          → Routers Python (JSON)
    ├── /static/css/...   → Serve arquivos CSS do frontend/css/
    ├── /static/js/...    → Serve arquivos JS do frontend/js/
    └── /*.html           → Serve páginas HTML do frontend/html/
    │
    ▼
SQLite (backend/cdn.db)
```

O backend serve **tanto a API quanto os arquivos do frontend**. Não há servidor separado para o frontend.

---

## Instalação e execução

### 1. Pré-requisitos

- Python 3.10 ou superior instalado

### 2. Instalar dependências

```bash
cd CDN/backend
pip install -r requirements.txt
```

### 3. Iniciar o servidor

```bash
cd CDN/backend
python -m uvicorn app.main:app --reload --port 8000
```

O banco de dados `cdn.db` é criado automaticamente na primeira execução.

### 4. Acessar o sistema

Abra o navegador em:

```
http://localhost:8000
```

---

## Páginas disponíveis

| URL                                    | Descrição                          |
|----------------------------------------|------------------------------------|
| `http://localhost:8000/`               | Dashboard principal                |
| `http://localhost:8000/estoque.html`   | Estoque de produtos                |
| `http://localhost:8000/parceiros.html` | Lista de parceiros/revendedores    |
| `http://localhost:8000/parceiro-detalhe.html?id=1` | Detalhe de um parceiro |
| `http://localhost:8000/financeiro.html`| Financeiro e fluxo de caixa       |
| `http://localhost:8000/configuracoes.html` | Categorias e configurações    |
| `http://localhost:8000/api/docs`       | Documentação automática da API     |

---

## API resumida

### Dashboard
| Método | Rota            | Descrição                    |
|--------|-----------------|------------------------------|
| GET    | /api/dashboard  | Resumo geral do sistema      |

### Estoque
| Método | Rota                         | Descrição                        |
|--------|------------------------------|----------------------------------|
| GET    | /api/produtos                | Listar produtos (busca, filtro)  |
| POST   | /api/produtos                | Criar produto                    |
| GET    | /api/produtos/{id}           | Obter produto                    |
| PUT    | /api/produtos/{id}           | Editar produto                   |
| DELETE | /api/produtos/{id}           | Excluir produto                  |
| POST   | /api/produtos/{id}/ajuste    | Ajustar estoque manualmente      |
| GET    | /api/categorias              | Listar categorias                |
| POST   | /api/categorias              | Criar categoria                  |
| DELETE | /api/categorias/{id}         | Excluir categoria                |

### Parceiros
| Método | Rota                             | Descrição                          |
|--------|----------------------------------|------------------------------------|
| GET    | /api/parceiros                   | Listar parceiros                   |
| GET    | /api/parceiros/saldos            | Saldos consolidados de todos       |
| POST   | /api/parceiros                   | Criar parceiro                     |
| GET    | /api/parceiros/{id}              | Obter parceiro                     |
| PUT    | /api/parceiros/{id}              | Editar parceiro                    |
| DELETE | /api/parceiros/{id}              | Excluir parceiro                   |
| GET    | /api/parceiros/{id}/saldo        | Saldo de um parceiro               |
| GET    | /api/parceiros/{id}/historico    | Histórico de movimentações         |
| POST   | /api/parceiros/{id}/envio        | Registrar envio de produtos        |
| POST   | /api/parceiros/{id}/venda        | Registrar venda (cria financeiro)  |
| POST   | /api/parceiros/{id}/devolucao    | Registrar devolução (volta estoque)|

### Financeiro
| Método | Rota                   | Descrição                        |
|--------|------------------------|----------------------------------|
| GET    | /api/financeiro/resumo | Resumo financeiro (total + mês)  |
| GET    | /api/financeiro        | Listar transações                |
| POST   | /api/financeiro        | Criar transação                  |
| DELETE | /api/financeiro/{id}   | Excluir transação                |

---

## Lógica de negócio automática

| Evento                        | O que acontece automaticamente                   |
|-------------------------------|--------------------------------------------------|
| Registrar envio ao parceiro   | Desconta do estoque do produto                   |
| Registrar venda do parceiro   | Cria entrada financeira com o valor informado    |
| Registrar devolução           | Retorna os produtos ao estoque                   |
| Criar produto com quantidade  | Registra movimentação de entrada no histórico    |

---

## Design

**Paleta de cores:**
- `#38a3a5` — Teal principal
- `#57cc99` — Verde
- `#80ed99` — Verde claro
- `#c7f9cc` — Verde pálido
- `#22577a` — Azul escuro (sidebar)

**Princípios visuais:**
- Inspirado em Apple Human Interface Guidelines
- Tipografia do sistema (`-apple-system, BlinkMacSystemFont`)
- Espaçamento generoso, sombras sutis, bordas arredondadas
- Transições suaves em todas as interações
- Totalmente responsivo (desktop e mobile)

---

## MVP entregue

- [x] Dashboard com KPIs e gráfico de fluxo de caixa
- [x] Gestão completa de estoque (criar, editar, ajustar)
- [x] Alertas de estoque mínimo
- [x] Cadastro e gestão de parceiros/revendedores
- [x] Envio, venda e devolução de produtos por parceiro
- [x] Saldo e histórico por parceiro
- [x] Fluxo financeiro (entradas e saídas)
- [x] Categorias de produtos
- [x] Interface 100% em português
- [x] Design premium responsivo

## Próximas evoluções sugeridas

- Autenticação com senha (login simples)
- Upload de fotos de produtos
- Relatórios em PDF
- Notificações por e-mail para estoque baixo
- Backup automático do banco de dados

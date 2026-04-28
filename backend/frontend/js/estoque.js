/* ============================================================
   CDN — Estoque
   ============================================================ */

let todosOsProdutos = [];
let categorias      = [];
let buscaTimer      = null;

async function init() {
  await carregarCategorias();
  await carregarProdutos();
  iniciarFiltros();
}

async function carregarCategorias() {
  try {
    categorias = await Api.categorias.listar();
    preencherSelectCategorias();
  } catch (err) {
    showToast("Erro ao carregar categorias.", "error");
  }
}

function preencherSelectCategorias() {
  const selFilter  = document.getElementById("categoria-filter");
  const selProduto = document.getElementById("produto-categoria");

  const opts = categorias.map(c => `<option value="${c.id}">${c.nome}</option>`).join("");
  selFilter.innerHTML  = `<option value="">Todas as categorias</option>${opts}`;
  selProduto.innerHTML = `<option value="">Sem categoria</option>${opts}`;
}

async function carregarProdutos() {
  const busca   = document.getElementById("busca-input").value.trim();
  const catId   = document.getElementById("categoria-filter").value;

  const tbody = document.getElementById("produtos-tbody");
  tbody.innerHTML = `<tr><td colspan="7" class="loading-state"><div class="spinner"></div> Carregando...</td></tr>`;

  try {
    todosOsProdutos = await Api.produtos.listar(busca || null, catId || null);
    renderTabela(todosOsProdutos);
    document.getElementById("estoque-count").textContent = `${todosOsProdutos.length} produto${todosOsProdutos.length !== 1 ? "s" : ""}`;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="padding:var(--sp-8);text-align:center;color:var(--c-danger)">Erro ao carregar produtos.</td></tr>`;
    showToast("Erro: " + err.message, "error");
  }
}

function renderTabela(produtos) {
  const tbody = document.getElementById("produtos-tbody");

  if (!produtos.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7">
          <div class="empty-state">
            <div class="empty-state-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/></svg>
            </div>
            <h3>Nenhum produto encontrado</h3>
            <p>Tente ajustar os filtros ou cadastre um novo produto.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = produtos.map(p => {
    const isLow    = p.quantidade <= p.estoque_minimo;
    const isEmpty  = p.quantidade === 0;
    const pct      = p.estoque_minimo > 0 ? Math.min(100, (p.quantidade / (p.estoque_minimo * 2)) * 100) : 100;
    const barClass = isEmpty ? "low" : isLow ? "medium" : "";

    const statusBadge = isEmpty
      ? `<span class="badge badge-red badge-dot">Sem estoque</span>`
      : isLow
        ? `<span class="badge badge-yellow badge-dot">Estoque baixo</span>`
        : `<span class="badge badge-green badge-dot">Normal</span>`;

    const catNome = p.categoria?.nome
      ? `<span class="category-tag">${p.categoria.nome}</span>`
      : `<span style="color:var(--c-text-4);font-size:var(--text-xs)">—</span>`;

    return `
      <tr>
        <td>
          <div style="font-weight:500;color:var(--c-text-1)">${p.nome}</div>
          ${p.descricao ? `<div style="font-size:var(--text-xs);color:var(--c-text-3);margin-top:2px" class="truncate" style="max-width:220px">${p.descricao}</div>` : ""}
        </td>
        <td>${catNome}</td>
        <td style="font-size:var(--text-sm)">${formatMoney(p.preco_custo)}</td>
        <td style="font-size:var(--text-sm);font-weight:500">${formatMoney(p.preco_venda)}</td>
        <td>
          <div style="display:flex;align-items:center;gap:var(--sp-3)">
            <div class="qty-stepper">
              <button class="qty-btn" onclick="ajusteRapido(${p.id}, 'saida', 1)" title="Remover 1">−</button>
              <span class="qty-value">${p.quantidade}</span>
              <button class="qty-btn" onclick="ajusteRapido(${p.id}, 'entrada', 1)" title="Adicionar 1">+</button>
            </div>
            <div class="stock-bar" style="width:60px">
              <div class="stock-bar-fill ${barClass}" style="width:${pct}%"></div>
            </div>
          </div>
        </td>
        <td>${statusBadge}</td>
        <td>
          <div style="display:flex;gap:var(--sp-2)">
            <button class="btn btn-secondary btn-sm btn-icon" onclick="abrirModalAjuste(${p.id}, '${p.nome.replace(/'/g, "\\'")}', ${p.quantidade})" title="Ajustar estoque">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
            <button class="btn btn-secondary btn-sm btn-icon" onclick="abrirModalProduto(${p.id})" title="Editar produto">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
            </button>
            <button class="btn btn-ghost btn-sm btn-icon" onclick="deletarProduto(${p.id}, '${p.nome.replace(/'/g, "\\'")}')}" title="Excluir" style="color:var(--c-danger)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function iniciarFiltros() {
  const busca  = document.getElementById("busca-input");
  const catSel = document.getElementById("categoria-filter");

  busca.addEventListener("input", () => {
    clearTimeout(buscaTimer);
    buscaTimer = setTimeout(carregarProdutos, 350);
  });

  catSel.addEventListener("change", carregarProdutos);
}

// ── Ajuste rápido ──────────────────────────────────────────────────────────

async function ajusteRapido(id, tipo, qtd) {
  try {
    await Api.produtos.ajuste(id, { quantidade: qtd, tipo, motivo: tipo === "entrada" ? "Adição rápida" : "Remoção rápida" });
    await carregarProdutos();
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ── Modal de ajuste completo ───────────────────────────────────────────────

function abrirModalAjuste(id, nome, qtdAtual) {
  document.getElementById("ajuste-produto-id").value   = id;
  document.getElementById("ajuste-produto-nome").textContent = nome;
  document.getElementById("ajuste-qtd-atual").textContent    = qtdAtual;
  document.getElementById("ajuste-quantidade").value   = "";
  document.getElementById("ajuste-motivo").value       = "";
  document.getElementById("ajuste-tipo").value         = "entrada";
  openModal("modal-ajuste");
}

async function confirmarAjuste() {
  const id    = document.getElementById("ajuste-produto-id").value;
  const tipo  = document.getElementById("ajuste-tipo").value;
  const qtd   = parseInt(document.getElementById("ajuste-quantidade").value);
  const motivo= document.getElementById("ajuste-motivo").value;

  if (!qtd || qtd <= 0) { showToast("Informe uma quantidade válida.", "warning"); return; }

  try {
    await Api.produtos.ajuste(id, { quantidade: qtd, tipo, motivo: motivo || null });
    showToast("Estoque atualizado com sucesso!");
    closeModal("modal-ajuste");
    await carregarProdutos();
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ── Modal de produto ───────────────────────────────────────────────────────

async function abrirModalProduto(id = null) {
  limparFormProduto();

  if (id) {
    document.getElementById("modal-produto-title").textContent = "Editar produto";
    document.getElementById("btn-salvar-produto").textContent  = "Salvar alterações";
    document.getElementById("grupo-ajuste-tipo").style.display = "flex";

    try {
      const p = await Api.produtos.obter(id);
      document.getElementById("produto-id").value          = p.id;
      document.getElementById("produto-nome").value        = p.nome;
      document.getElementById("produto-categoria").value   = p.categoria_id || "";
      document.getElementById("produto-descricao").value   = p.descricao || "";
      document.getElementById("produto-quantidade").value  = p.quantidade;
      document.getElementById("produto-minimo").value      = p.estoque_minimo;
      document.getElementById("produto-custo").value       = p.preco_custo;
      document.getElementById("produto-venda").value       = p.preco_venda;
    } catch (err) {
      showToast("Erro ao carregar produto.", "error");
      return;
    }
  } else {
    document.getElementById("modal-produto-title").textContent = "Novo produto";
    document.getElementById("btn-salvar-produto").textContent  = "Criar produto";
    document.getElementById("grupo-ajuste-tipo").style.display = "none";
  }

  openModal("modal-produto");
}

function limparFormProduto() {
  ["produto-id","produto-nome","produto-descricao","produto-quantidade","produto-minimo","produto-custo","produto-venda"].forEach(id => {
    document.getElementById(id).value = "";
  });
  document.getElementById("produto-categoria").value = "";
}

async function salvarProduto() {
  const id   = document.getElementById("produto-id").value;
  const nome = document.getElementById("produto-nome").value.trim();
  if (!nome) { showToast("Informe o nome do produto.", "warning"); return; }

  const data = {
    nome,
    categoria_id: document.getElementById("produto-categoria").value || null,
    descricao:    document.getElementById("produto-descricao").value.trim() || null,
    quantidade:   parseInt(document.getElementById("produto-quantidade").value) || 0,
    estoque_minimo: parseInt(document.getElementById("produto-minimo").value) || 5,
    preco_custo:  parseFloat(document.getElementById("produto-custo").value) || 0,
    preco_venda:  parseFloat(document.getElementById("produto-venda").value) || 0,
  };

  const btn = document.getElementById("btn-salvar-produto");
  btn.disabled = true;

  try {
    if (id) {
      const tipo = document.getElementById("produto-ajuste-tipo").value;
      await Api.produtos.atualizar(id, data);
      if (data.quantidade !== undefined) {
        // Se há ajuste de estoque
        const prod = todosOsProdutos.find(p => p.id === parseInt(id));
        if (prod && tipo !== "ajuste" && data.quantidade !== prod.quantidade) {
          const diff = tipo === "entrada"
            ? data.quantidade
            : data.quantidade;
          await Api.produtos.ajuste(id, { quantidade: diff, tipo, motivo: "Edição de produto" });
        } else if (tipo === "ajuste") {
          await Api.produtos.ajuste(id, { quantidade: data.quantidade, tipo: "ajuste", motivo: "Ajuste manual" });
        }
      }
      showToast("Produto atualizado com sucesso!");
    } else {
      await Api.produtos.criar(data);
      showToast("Produto criado com sucesso!");
    }
    closeModal("modal-produto");
    await carregarProdutos();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

async function deletarProduto(id, nome) {
  if (!confirm(`Excluir o produto "${nome}"? Esta ação não pode ser desfeita.`)) return;
  try {
    await Api.produtos.deletar(id);
    showToast(`"${nome}" removido do estoque.`);
    await carregarProdutos();
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ── Init ──
document.addEventListener("DOMContentLoaded", init);

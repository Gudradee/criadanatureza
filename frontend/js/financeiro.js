/* ============================================================
   CDN — Financeiro
   ============================================================ */

let todasTransacoes = [];
let filtroAtivo     = "todos";

async function init() {
  await Promise.all([carregarResumo(), carregarTransacoes()]);
}

async function carregarResumo() {
  try {
    const r = await Api.financeiro.resumo();

    document.getElementById("fin-entradas").textContent  = formatMoney(r.total_entradas);
    document.getElementById("fin-saidas").textContent    = formatMoney(r.total_saidas);
    document.getElementById("fin-lucro").textContent     = formatMoney(r.lucro_estimado);
    document.getElementById("fin-mes-entradas").textContent = `Este mês: ${formatMoney(r.mes_atual_entradas)}`;
    document.getElementById("fin-mes-saidas").textContent   = `Este mês: ${formatMoney(r.mes_atual_saidas)}`;
    document.getElementById("fin-mes-lucro").textContent    = `Este mês: ${formatMoney(r.mes_atual_lucro)}`;

    const lucroEl = document.getElementById("fin-lucro");
    lucroEl.style.color = r.lucro_estimado >= 0 ? "" : "var(--c-danger)";
  } catch (err) {
    showToast("Erro ao carregar resumo financeiro.", "error");
  }
}

async function carregarTransacoes() {
  const tbody = document.getElementById("fin-tbody");
  try {
    todasTransacoes = await Api.financeiro.listar();
    renderTabela(todasTransacoes);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="padding:var(--sp-5);text-align:center;color:var(--c-danger)">Erro ao carregar transações.</td></tr>`;
  }
}

function filtrar(tipo) {
  filtroAtivo = tipo;
  ["todos","entrada","saida"].forEach(t => {
    const id  = t === "todos" ? "f-todos" : t === "entrada" ? "f-entrada" : "f-saida";
    const btn = document.getElementById(id);
    btn.style.color = t === tipo ? "var(--c-teal)" : "";
    btn.style.fontWeight = t === tipo ? "600" : "";
  });
  const lista = tipo === "todos" ? todasTransacoes : todasTransacoes.filter(t => t.tipo === tipo);
  renderTabela(lista);
}

function renderTabela(lista) {
  const tbody = document.getElementById("fin-tbody");

  if (!lista.length) {
    tbody.innerHTML = `
      <tr><td colspan="6">
        <div class="empty-state">
          <div class="empty-state-icon">💰</div>
          <h3>Nenhuma transação encontrada</h3>
          <p>Registre entradas e saídas para visualizar o fluxo de caixa.</p>
        </div>
      </td></tr>
    `;
    return;
  }

  tbody.innerHTML = lista.map(t => {
    const isEntrada = t.tipo === "entrada";
    return `
      <tr>
        <td>
          <span class="badge ${isEntrada ? 'badge-green' : 'badge-red'} badge-dot">
            ${isEntrada ? "Entrada" : "Saída"}
          </span>
        </td>
        <td class="td-name">${t.descricao}</td>
        <td>
          ${t.categoria
            ? `<span class="category-tag">${t.categoria}</span>`
            : `<span style="color:var(--c-text-4);font-size:var(--text-xs)">—</span>`
          }
        </td>
        <td style="font-size:var(--text-sm);color:var(--c-text-3);white-space:nowrap">${formatDate(t.data)}</td>
        <td style="text-align:right;font-weight:600;font-size:var(--text-sm);color:${isEntrada ? 'var(--c-success)' : 'var(--c-danger)'}">
          ${isEntrada ? "+" : "−"}${formatMoney(t.valor)}
        </td>
        <td>
          <button class="btn btn-ghost btn-sm btn-icon" onclick="deletarTransacao(${t.id})" title="Excluir" style="color:var(--c-danger)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
          </button>
        </td>
      </tr>
    `;
  }).join("");
}

// ── Modal ─────────────────────────────────────────────────────────────────

function abrirModal(tipo) {
  document.getElementById("fin-tipo").value       = tipo;
  document.getElementById("modal-fin-title").textContent = tipo === "entrada" ? "Nova entrada" : "Nova saída";
  document.getElementById("fin-descricao").value  = "";
  document.getElementById("fin-valor").value      = "";
  document.getElementById("fin-categoria").value  = "";
  document.getElementById("fin-data").value       = new Date().toISOString().split("T")[0];

  const btn = document.getElementById("btn-salvar-fin");
  btn.className = tipo === "entrada" ? "btn btn-primary" : "btn btn-danger";

  openModal("modal-transacao");
}

async function salvarTransacao() {
  const tipo = document.getElementById("fin-tipo").value;
  const desc = document.getElementById("fin-descricao").value.trim();
  const val  = parseFloat(document.getElementById("fin-valor").value);

  if (!desc) { showToast("Informe a descrição.", "warning"); return; }
  if (!val || val <= 0) { showToast("Informe um valor válido.", "warning"); return; }

  const data = {
    tipo,
    descricao:  desc,
    valor:      val,
    categoria:  document.getElementById("fin-categoria").value.trim() || null,
    data:       document.getElementById("fin-data").value || null,
  };

  const btn = document.getElementById("btn-salvar-fin");
  btn.disabled = true;

  try {
    await Api.financeiro.criar(data);
    showToast(`${tipo === "entrada" ? "Entrada" : "Saída"} registrada com sucesso!`);
    closeModal("modal-transacao");
    await Promise.all([carregarResumo(), carregarTransacoes()]);
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

async function deletarTransacao(id) {
  if (!confirm("Excluir esta transação?")) return;
  try {
    await Api.financeiro.deletar(id);
    showToast("Transação excluída.");
    await Promise.all([carregarResumo(), carregarTransacoes()]);
  } catch (err) {
    showToast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", init);

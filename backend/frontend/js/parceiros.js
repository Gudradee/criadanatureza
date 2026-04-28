/* ============================================================
   CDN — Parceiros (listagem)
   ============================================================ */

async function init() {
  await carregarParceiros();
}

async function carregarParceiros() {
  const grid = document.getElementById("parceiros-grid");
  grid.innerHTML = `<div class="loading-state" style="grid-column:1/-1"><div class="spinner"></div> Carregando...</div>`;

  try {
    const saldos = await Api.parceiros.saldos();
    document.getElementById("parceiros-count").textContent =
      `${saldos.length} parceiro${saldos.length !== 1 ? "s" : ""}`;
    renderCards(saldos);
  } catch (err) {
    grid.innerHTML = `<p style="color:var(--c-danger);grid-column:1/-1">Erro: ${err.message}</p>`;
  }
}

function renderCards(saldos) {
  const grid = document.getElementById("parceiros-grid");

  if (!saldos.length) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column:1/-1">
        <div class="empty-state-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>
        </div>
        <h3>Nenhum parceiro cadastrado</h3>
        <p>Adicione revendedores para acompanhar envios, vendas e devoluções.</p>
      </div>
    `;
    return;
  }

  grid.innerHTML = saldos.map(p => {
    const pctVenda = p.total_enviado > 0 ? Math.round((p.total_vendido / p.total_enviado) * 100) : 0;
    return `
      <div class="partner-card" onclick="window.location='/parceiro-detalhe.html?id=${p.parceiro_id}'">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:var(--sp-3)">
          <div style="display:flex;align-items:center;gap:var(--sp-3)">
            <div class="partner-avatar">${initials(p.nome)}</div>
            <div style="min-width:0">
              <div style="font-size:var(--text-base);font-weight:600;color:var(--c-text-1)" class="truncate">${p.nome}</div>
              <span class="badge ${p.status === 'ativo' ? 'badge-green' : 'badge-gray'} badge-dot">${p.status}</span>
            </div>
          </div>
          <button
            class="btn btn-ghost btn-sm btn-icon"
            onclick="event.stopPropagation();abrirModalParceiro(${p.parceiro_id})"
            title="Editar"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
        </div>

        <div class="partner-meta">
          <div>
            <div class="partner-stat-label">Enviado</div>
            <div class="partner-stat-value">${p.total_enviado}</div>
          </div>
          <div>
            <div class="partner-stat-label">Vendido</div>
            <div class="partner-stat-value" style="color:var(--c-success)">${p.total_vendido}</div>
          </div>
          <div>
            <div class="partner-stat-label">Em mãos</div>
            <div class="partner-stat-value" style="color:${p.em_maos > 0 ? 'var(--c-navy)' : 'var(--c-text-4)'}">${p.em_maos}</div>
          </div>
        </div>

        <div style="margin-top:var(--sp-4)">
          <div style="display:flex;justify-content:space-between;margin-bottom:var(--sp-2)">
            <span style="font-size:var(--text-xs);color:var(--c-text-3)">Taxa de venda</span>
            <span style="font-size:var(--text-xs);font-weight:600;color:var(--c-text-2)">${pctVenda}%</span>
          </div>
          <div class="stock-bar">
            <div class="stock-bar-fill" style="width:${pctVenda}%;background:linear-gradient(90deg,var(--c-teal),var(--c-green))"></div>
          </div>
        </div>

        ${p.valor_em_maos > 0 ? `
          <div style="margin-top:var(--sp-4);padding-top:var(--sp-3);border-top:1px solid var(--c-border-soft);display:flex;justify-content:space-between;align-items:center">
            <span style="font-size:var(--text-xs);color:var(--c-text-3)">Valor em mãos</span>
            <span style="font-size:var(--text-sm);font-weight:700;color:var(--c-navy)">${formatMoney(p.valor_em_maos)}</span>
          </div>
        ` : ""}
      </div>
    `;
  }).join("");
}

// ── Modal parceiro ────────────────────────────────────────────────────────

async function abrirModalParceiro(id = null) {
  limparFormParceiro();

  if (id) {
    document.getElementById("modal-parceiro-title").textContent = "Editar parceiro";
    document.getElementById("btn-salvar-parceiro").textContent  = "Salvar alterações";
    try {
      const p = await Api.parceiros.obter(id);
      document.getElementById("parceiro-id").value       = p.id;
      document.getElementById("parceiro-nome").value     = p.nome;
      document.getElementById("parceiro-contato").value  = p.contato || "";
      document.getElementById("parceiro-telefone").value = p.telefone || "";
      document.getElementById("parceiro-email").value    = p.email || "";
      document.getElementById("parceiro-status").value   = p.status;
      document.getElementById("parceiro-obs").value      = p.observacoes || "";
    } catch (err) {
      showToast("Erro ao carregar parceiro.", "error");
      return;
    }
  } else {
    document.getElementById("modal-parceiro-title").textContent = "Novo parceiro";
    document.getElementById("btn-salvar-parceiro").textContent  = "Criar parceiro";
  }

  openModal("modal-parceiro");
}

function limparFormParceiro() {
  ["parceiro-id","parceiro-nome","parceiro-contato","parceiro-telefone","parceiro-email","parceiro-obs"].forEach(id => {
    document.getElementById(id).value = "";
  });
  document.getElementById("parceiro-status").value = "ativo";
}

async function salvarParceiro() {
  const id   = document.getElementById("parceiro-id").value;
  const nome = document.getElementById("parceiro-nome").value.trim();
  if (!nome) { showToast("Informe o nome do parceiro.", "warning"); return; }

  const data = {
    nome,
    contato:     document.getElementById("parceiro-contato").value.trim() || null,
    telefone:    document.getElementById("parceiro-telefone").value.trim() || null,
    email:       document.getElementById("parceiro-email").value.trim() || null,
    status:      document.getElementById("parceiro-status").value,
    observacoes: document.getElementById("parceiro-obs").value.trim() || null,
  };

  const btn = document.getElementById("btn-salvar-parceiro");
  btn.disabled = true;

  try {
    if (id) {
      await Api.parceiros.atualizar(id, data);
      showToast("Parceiro atualizado com sucesso!");
    } else {
      await Api.parceiros.criar(data);
      showToast("Parceiro cadastrado com sucesso!");
    }
    closeModal("modal-parceiro");
    await carregarParceiros();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", init);

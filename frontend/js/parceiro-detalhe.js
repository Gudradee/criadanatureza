/* ============================================================
   CDN — Detalhe do parceiro
   ============================================================ */

const params     = new URLSearchParams(window.location.search);
const parceiroId = parseInt(params.get("id"));
let historico    = [];
let produtos     = [];

async function init() {
  if (!parceiroId) { window.location = "/parceiros.html"; return; }
  await Promise.all([carregarSaldo(), carregarHistorico(), carregarProdutos()]);
}

async function carregarProdutos() {
  try {
    produtos = await Api.produtos.listar();
  } catch (_) {}
}

async function carregarSaldo() {
  try {
    const [parceiro, saldo] = await Promise.all([
      Api.parceiros.obter(parceiroId),
      Api.parceiros.saldo(parceiroId),
    ]);

    document.getElementById("detalhe-nome").textContent = parceiro.nome;
    document.getElementById("detalhe-sub").textContent =
      [parceiro.contato, parceiro.telefone].filter(Boolean).join(" · ") || "Sem contato cadastrado";

    document.getElementById("kpi-enviado").textContent  = saldo.total_enviado;
    document.getElementById("kpi-vendido").textContent  = saldo.total_vendido;
    document.getElementById("kpi-em-maos").textContent  = saldo.em_maos;
    document.getElementById("kpi-devolvido").textContent= saldo.total_devolvido;
    document.getElementById("kpi-valor-maos").textContent =
      saldo.valor_em_maos > 0 ? `≈ ${formatMoney(saldo.valor_em_maos)}` : "com o parceiro agora";

    document.title = `${parceiro.nome} — CDN`;
  } catch (err) {
    showToast("Erro ao carregar parceiro.", "error");
  }
}

async function carregarHistorico() {
  const tbody = document.getElementById("historico-tbody");
  try {
    historico = await Api.parceiros.historico(parceiroId);
    renderHistorico(historico);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" style="padding:var(--sp-5);color:var(--c-danger);text-align:center">Erro ao carregar histórico.</td></tr>`;
  }
}

let filtroAtivo = "todos";

function filtrarHistorico(tipo) {
  filtroAtivo = tipo;
  ["todos","envio","venda","devolucao"].forEach(t => {
    const id = t === "todos" ? "filtro-todos" : t === "envio" ? "filtro-envio" : t === "venda" ? "filtro-venda" : "filtro-dev";
    const btn = document.getElementById(id);
    btn.style.color = t === tipo ? "var(--c-teal)" : "";
    btn.style.fontWeight = t === tipo ? "600" : "";
  });
  const filtrado = tipo === "todos" ? historico : historico.filter(h => h.tipo === tipo);
  renderHistorico(filtrado);
}

const tipoConfig = {
  envio:     { label: "Envio",     cls: "badge-teal",    icon: "↑" },
  venda:     { label: "Venda",     cls: "badge-green",   icon: "✓" },
  devolucao: { label: "Devolução", cls: "badge-yellow",  icon: "↩" },
};

function renderHistorico(lista) {
  const tbody = document.getElementById("historico-tbody");
  if (!lista.length) {
    tbody.innerHTML = `
      <tr><td colspan="4">
        <div class="empty-state">
          <div class="empty-state-icon">📋</div>
          <h3>Nenhuma movimentação encontrada</h3>
          <p>Use os botões acima para registrar envios, vendas ou devoluções.</p>
        </div>
      </td></tr>
    `;
    return;
  }

  tbody.innerHTML = lista.map(h => {
    const cfg = tipoConfig[h.tipo] || { label: h.tipo, cls: "badge-gray", icon: "·" };
    const itensStr = h.itens
      .map(i => `${i.produto} × ${i.quantidade}`)
      .join(", ");
    return `
      <tr>
        <td><span class="badge ${cfg.cls}">${cfg.icon} ${cfg.label}</span></td>
        <td style="font-size:var(--text-sm);color:var(--c-text-3);white-space:nowrap">${formatDateFull(h.data)}</td>
        <td style="font-size:var(--text-sm)">${itensStr || "—"}</td>
        <td style="font-size:var(--text-sm);color:var(--c-text-3)">${h.observacoes || "—"}</td>
      </tr>
    `;
  }).join("");
}

// ── Linhas de produto nos modais ──────────────────────────────────────────

function linhaItem(containerId, index) {
  const opts = produtos.map(p =>
    `<option value="${p.id}" data-venda="${p.preco_venda}">${p.nome} (estoque: ${p.quantidade})</option>`
  ).join("");

  return `
    <div id="linha-${containerId}-${index}" style="display:grid;grid-template-columns:1fr 80px 110px 30px;gap:var(--sp-2);align-items:center">
      <select class="form-select" id="${containerId}-prod-${index}" style="height:36px">
        <option value="">Selecione um produto</option>
        ${opts}
      </select>
      <input class="form-input" id="${containerId}-qtd-${index}" type="number" min="1" value="1" placeholder="Qtd" style="height:36px" />
      <input class="form-input" id="${containerId}-preco-${index}" type="number" min="0" step="0.01" placeholder="Preço un." style="height:36px" />
      <button class="btn btn-ghost btn-sm btn-icon" onclick="removeLinha('linha-${containerId}-${index}')" style="color:var(--c-danger);height:36px">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
  `;
}

function removeLinha(id) { document.getElementById(id)?.remove(); }

let envioCount = 0, vendaCount = 0, devCount = 0;

function addLinhaEnvio() {
  document.getElementById("itens-envio").insertAdjacentHTML("beforeend", linhaItem("envio", envioCount++));
}

function addLinhaVenda() {
  const linha = linhaItem("venda", vendaCount++);
  document.getElementById("itens-venda").insertAdjacentHTML("beforeend", linha);
  // Preencher preço automaticamente ao selecionar produto
  const idx = vendaCount - 1;
  setTimeout(() => {
    const sel = document.getElementById(`venda-prod-${idx}`);
    sel?.addEventListener("change", () => {
      const opt = sel.options[sel.selectedIndex];
      const venda = opt.dataset.venda;
      const precoInput = document.getElementById(`venda-preco-${idx}`);
      if (precoInput && venda) precoInput.value = parseFloat(venda).toFixed(2);
    });
  }, 50);
}

function addLinhaDev() {
  document.getElementById("itens-dev").insertAdjacentHTML("beforeend", linhaItem("dev", devCount++));
}

function coletarItens(prefix, count) {
  const itens = [];
  for (let i = 0; i < count; i++) {
    const prodSel = document.getElementById(`${prefix}-prod-${i}`);
    const qtdInput= document.getElementById(`${prefix}-qtd-${i}`);
    const precoInput = document.getElementById(`${prefix}-preco-${i}`);
    if (!prodSel || !qtdInput) continue;
    const prodId = parseInt(prodSel.value);
    const qtd    = parseInt(qtdInput.value);
    const preco  = parseFloat(precoInput?.value) || 0;
    if (prodId && qtd > 0) itens.push({ produto_id: prodId, quantidade: qtd, preco_unitario: preco });
  }
  return itens;
}

// ── Envio ─────────────────────────────────────────────────────────────────

function abrirModalEnvio() {
  envioCount = 0;
  document.getElementById("itens-envio").innerHTML = "";
  document.getElementById("envio-obs").value = "";
  addLinhaEnvio();
  openModal("modal-envio");
}

async function confirmarEnvio() {
  const itens = coletarItens("envio", envioCount);
  if (!itens.length) { showToast("Adicione ao menos um produto.", "warning"); return; }
  try {
    await Api.parceiros.envio(parceiroId, {
      parceiro_id: parceiroId,
      itens,
      observacoes: document.getElementById("envio-obs").value.trim() || null
    });
    showToast("Envio registrado com sucesso!");
    closeModal("modal-envio");
    await Promise.all([carregarSaldo(), carregarHistorico()]);
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ── Venda ─────────────────────────────────────────────────────────────────

function abrirModalVenda() {
  vendaCount = 0;
  document.getElementById("itens-venda").innerHTML = "";
  document.getElementById("venda-obs").value = "";
  addLinhaVenda();
  openModal("modal-venda");
}

async function confirmarVenda() {
  const itens = coletarItens("venda", vendaCount);
  if (!itens.length) { showToast("Adicione ao menos um produto.", "warning"); return; }
  try {
    await Api.parceiros.venda(parceiroId, {
      parceiro_id: parceiroId,
      itens,
      observacoes: document.getElementById("venda-obs").value.trim() || null
    });
    showToast("Venda registrada e entrada financeira criada!");
    closeModal("modal-venda");
    await Promise.all([carregarSaldo(), carregarHistorico()]);
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ── Devolução ─────────────────────────────────────────────────────────────

function abrirModalDevolucao() {
  devCount = 0;
  document.getElementById("itens-dev").innerHTML = "";
  document.getElementById("dev-obs").value = "";
  addLinhaDev();
  openModal("modal-devolucao");
}

async function confirmarDevolucao() {
  const itens = coletarItens("dev", devCount);
  if (!itens.length) { showToast("Adicione ao menos um produto.", "warning"); return; }
  try {
    await Api.parceiros.devolucao(parceiroId, {
      parceiro_id: parceiroId,
      itens,
      observacoes: document.getElementById("dev-obs").value.trim() || null
    });
    showToast("Devolução registrada e estoque atualizado!");
    closeModal("modal-devolucao");
    await Promise.all([carregarSaldo(), carregarHistorico()]);
  } catch (err) {
    showToast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", init);

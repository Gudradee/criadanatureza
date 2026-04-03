/* ============================================================
   CDN — Dashboard
   ============================================================ */

let cashflowChart = null;

async function loadDashboard() {
  try {
    const data = await Api.dashboard();
    renderKPIs(data);
    renderAlertas(data.estoque.alertas);
    renderCashflow(data.fluxo_mensal);
    loadParceirosResumo();
  } catch (err) {
    showToast("Erro ao carregar dashboard: " + err.message, "error");
  }
}

function renderKPIs(data) {
  const f = data.financeiro;
  const e = data.estoque;

  document.getElementById("kpi-entradas").textContent = formatMoney(f.entradas_mes);
  document.getElementById("kpi-saidas").textContent   = formatMoney(f.saidas_mes);

  const lucroEl = document.getElementById("kpi-lucro");
  lucroEl.textContent = formatMoney(f.lucro_mes);
  lucroEl.style.color = f.lucro_mes >= 0 ? "var(--c-text-1)" : "var(--c-danger)";

  document.getElementById("kpi-estoque").textContent       = e.total_itens.toLocaleString("pt-BR");
  document.getElementById("kpi-estoque-footer").textContent = `${e.total_produtos} produtos · ${e.alertas_estoque_baixo} alertas`;

  const badge = document.getElementById("nav-alerta-badge");
  if (badge) {
    badge.style.display = e.alertas_estoque_baixo > 0 ? "flex" : "none";
    badge.textContent   = e.alertas_estoque_baixo;
  }
}

function renderAlertas(alertas) {
  const container = document.getElementById("alertas-list");
  if (!alertas.length) {
    container.innerHTML = `
      <div style="text-align:center;padding:var(--sp-8) 0;color:var(--c-text-3)">
        <div style="font-size:32px;margin-bottom:var(--sp-3)">✅</div>
        <p style="font-size:var(--text-sm);font-weight:500">Tudo em ordem!</p>
        <p style="font-size:var(--text-xs);color:var(--c-text-4);margin-top:4px">Nenhum produto com estoque crítico.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = alertas.slice(0, 6).map(p => {
    const pct = p.estoque_minimo > 0 ? Math.min(100, (p.quantidade / p.estoque_minimo) * 100) : 0;
    const cls = p.quantidade === 0 ? "low" : p.quantidade <= p.estoque_minimo ? "medium" : "";
    const badge = p.quantidade === 0
      ? `<span class="badge badge-red badge-dot">Sem estoque</span>`
      : `<span class="badge badge-yellow badge-dot">Estoque baixo</span>`;

    return `
      <div style="display:flex;flex-direction:column;gap:var(--sp-2)">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3)">
          <span style="font-size:var(--text-sm);font-weight:500;color:var(--c-text-1);min-width:0" class="truncate">${p.nome}</span>
          ${badge}
        </div>
        <div class="stock-bar-wrap">
          <div class="stock-bar">
            <div class="stock-bar-fill ${cls}" style="width:${pct}%"></div>
          </div>
          <span style="font-size:var(--text-xs);color:var(--c-text-3);white-space:nowrap">${p.quantidade}/${p.estoque_minimo}</span>
        </div>
      </div>
    `;
  }).join('<div class="divider" style="margin:0"></div>');
}

function renderCashflow(fluxo) {
  const ctx = document.getElementById("cashflow-chart");
  if (!ctx) return;

  const labels = fluxo.map(f => f.mes);
  const entradas = fluxo.map(f => f.entradas);
  const saidas   = fluxo.map(f => f.saidas);
  const lucro    = fluxo.map(f => f.lucro);

  if (cashflowChart) cashflowChart.destroy();

  cashflowChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Entradas",
          data: entradas,
          backgroundColor: "rgba(87,204,153,0.7)",
          borderRadius: 6,
          borderSkipped: false,
        },
        {
          label: "Saídas",
          data: saidas,
          backgroundColor: "rgba(239,68,68,0.55)",
          borderRadius: 6,
          borderSkipped: false,
        },
        {
          label: "Lucro",
          data: lucro,
          type: "line",
          borderColor: "var(--c-teal)",
          backgroundColor: "rgba(56,163,165,0.08)",
          borderWidth: 2.5,
          pointBackgroundColor: "var(--c-teal)",
          pointRadius: 4,
          pointHoverRadius: 6,
          fill: true,
          tension: 0.4,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          position: "top",
          align: "end",
          labels: {
            boxWidth: 10,
            boxHeight: 10,
            borderRadius: 3,
            useBorderRadius: true,
            font: { size: 11, family: "-apple-system, BlinkMacSystemFont, sans-serif" },
            color: "#6b7280",
            padding: 12,
          }
        },
        tooltip: {
          backgroundColor: "#fff",
          titleColor: "#111827",
          bodyColor: "#374151",
          borderColor: "#e8ecf0",
          borderWidth: 1,
          padding: 12,
          boxShadow: "0 4px 12px rgba(0,0,0,.1)",
          callbacks: {
            label: ctx => ` ${ctx.dataset.label}: ${formatMoney(ctx.parsed.y)}`
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { size: 11 }, color: "#9ca3af" },
          border: { display: false }
        },
        y: {
          grid: { color: "#f0f3f5" },
          ticks: {
            font: { size: 11 },
            color: "#9ca3af",
            callback: v => formatMoney(v)
          },
          border: { display: false, dash: [4, 4] }
        }
      }
    }
  });
}

async function loadParceirosResumo() {
  const container = document.getElementById("parceiros-resumo");
  try {
    const saldos = await Api.parceiros.saldos();
    const ativos = saldos.filter(p => p.status === "ativo").slice(0, 3);

    if (!ativos.length) {
      container.innerHTML = `
        <div class="empty-state" style="grid-column:1/-1">
          <div class="empty-state-icon">👥</div>
          <h3>Nenhum parceiro cadastrado</h3>
          <p>Cadastre parceiros para acompanhar as movimentações.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = ativos.map(p => `
      <a href="/parceiro-detalhe.html?id=${p.parceiro_id}" class="card card-padded card-hover" style="text-decoration:none;display:block">
        <div style="display:flex;align-items:center;gap:var(--sp-3);margin-bottom:var(--sp-4)">
          <div class="partner-avatar">${initials(p.nome)}</div>
          <div style="min-width:0">
            <div style="font-weight:600;color:var(--c-text-1)" class="truncate">${p.nome}</div>
            <span class="badge ${p.status === 'ativo' ? 'badge-green' : 'badge-gray'} badge-dot">${p.status}</span>
          </div>
        </div>
        <div class="partner-meta">
          <div>
            <div class="partner-stat-label">Enviado</div>
            <div class="partner-stat-value">${p.total_enviado}</div>
          </div>
          <div>
            <div class="partner-stat-label">Vendido</div>
            <div class="partner-stat-value">${p.total_vendido}</div>
          </div>
          <div>
            <div class="partner-stat-label">Em mãos</div>
            <div class="partner-stat-value">${p.em_maos}</div>
          </div>
        </div>
      </a>
    `).join("");
  } catch (err) {
    container.innerHTML = `<p style="color:var(--c-danger);font-size:var(--text-sm);grid-column:1/-1">Erro ao carregar parceiros.</p>`;
  }
}

// ── Init ──
document.addEventListener("DOMContentLoaded", () => {
  const now = new Date();
  document.getElementById("topbar-date").textContent = now.toLocaleDateString("pt-BR", {
    weekday: "long", day: "numeric", month: "long", year: "numeric"
  });

  loadDashboard();
});

/* ============================================================
   CDN — Cliente de API
   ============================================================ */

const API_BASE = "http://localhost:8000/api";

const Api = {
  async _req(method, path, body = null) {
    const opts = {
      method,
      headers: { "Content-Type": "application/json" },
    };
    if (body) opts.body = JSON.stringify(body);

    const res = await fetch(API_BASE + path, opts);
    if (!res.ok) {
      let msg = `Erro ${res.status}`;
      try {
        const data = await res.json();
        msg = data.detail || msg;
      } catch (_) {}
      throw new Error(msg);
    }
    if (res.status === 204) return null;
    return res.json();
  },

  get:    (path)        => Api._req("GET",    path),
  post:   (path, body)  => Api._req("POST",   path, body),
  put:    (path, body)  => Api._req("PUT",    path, body),
  delete: (path)        => Api._req("DELETE", path),

  // Dashboard
  dashboard: () => Api.get("/dashboard"),

  // Estoque
  produtos: {
    listar:    (busca, catId)  => Api.get(`/produtos${buildQuery({ busca, categoria_id: catId })}`),
    obter:     (id)            => Api.get(`/produtos/${id}`),
    criar:     (data)          => Api.post("/produtos", data),
    atualizar: (id, data)      => Api.put(`/produtos/${id}`, data),
    deletar:   (id)            => Api.delete(`/produtos/${id}`),
    ajuste:    (id, data)      => Api.post(`/produtos/${id}/ajuste`, data),
    historico: (id)            => Api.get(`/produtos/${id}/movimentacoes`),
  },

  categorias: {
    listar: () => Api.get("/categorias"),
    criar:  (data) => Api.post("/categorias", data),
    deletar:(id)   => Api.delete(`/categorias/${id}`),
  },

  // Parceiros
  parceiros: {
    listar:      ()       => Api.get("/parceiros"),
    saldos:      ()       => Api.get("/parceiros/saldos"),
    obter:       (id)     => Api.get(`/parceiros/${id}`),
    saldo:       (id)     => Api.get(`/parceiros/${id}/saldo`),
    historico:   (id)     => Api.get(`/parceiros/${id}/historico`),
    criar:       (data)   => Api.post("/parceiros", data),
    atualizar:   (id, d)  => Api.put(`/parceiros/${id}`, d),
    deletar:     (id)     => Api.delete(`/parceiros/${id}`),
    envio:       (id, d)  => Api.post(`/parceiros/${id}/envio`, d),
    venda:       (id, d)  => Api.post(`/parceiros/${id}/venda`, d),
    devolucao:   (id, d)  => Api.post(`/parceiros/${id}/devolucao`, d),
  },

  // Financeiro
  financeiro: {
    resumo:  ()          => Api.get("/financeiro/resumo"),
    listar:  (tipo)      => Api.get(`/financeiro${buildQuery({ tipo })}`),
    criar:   (data)      => Api.post("/financeiro", data),
    deletar: (id)        => Api.delete(`/financeiro/${id}`),
  },
};

function buildQuery(params = {}) {
  const filtered = Object.entries(params).filter(([, v]) => v != null && v !== "");
  if (!filtered.length) return "";
  return "?" + new URLSearchParams(Object.fromEntries(filtered)).toString();
}

/* ============================================================
   Toast
   ============================================================ */
function showToast(msg, type = "success") {
  let container = document.querySelector(".toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
    document.body.appendChild(container);
  }

  const icons = {
    success: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`,
    error:   `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    warning: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
  };

  const colors = { success: "#57cc99", error: "#ef4444", warning: "#f59e0b" };

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.style.borderLeftColor = colors[type] || colors.success;
  toast.innerHTML = `
    <span style="color:${colors[type]};flex-shrink:0">${icons[type] || icons.success}</span>
    <span>${msg}</span>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 3200);
}

/* ============================================================
   Modal helpers
   ============================================================ */
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("open");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("open");
}

/* ============================================================
   Formatação
   ============================================================ */
function formatMoney(val) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(val || 0);
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(iso));
}

function formatDateFull(iso) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit"
  }).format(new Date(iso));
}

function initials(name) {
  return (name || "?")
    .split(" ")
    .slice(0, 2)
    .map(w => w[0])
    .join("")
    .toUpperCase();
}

/* ============================================================
   Sidebar ativa
   ============================================================ */
function setActivePage(page) {
  document.querySelectorAll(".nav-item").forEach(el => {
    el.classList.toggle("active", el.dataset.page === page);
  });
}

/* ============================================================
   Sidebar mobile
   ============================================================ */
document.addEventListener("DOMContentLoaded", () => {
  const sidebar = document.querySelector(".sidebar");
  const toggle  = document.querySelector(".sidebar-toggle");
  const overlay = document.querySelector(".sidebar-overlay");

  toggle?.addEventListener("click", () => {
    sidebar?.classList.toggle("open");
    overlay?.classList.toggle("visible");
  });

  overlay?.addEventListener("click", () => {
    sidebar?.classList.remove("open");
    overlay?.classList.remove("visible");
  });

  // Fecha modal ao clicar no backdrop
  document.querySelectorAll(".modal-backdrop").forEach(backdrop => {
    backdrop.addEventListener("click", e => {
      if (e.target === backdrop) backdrop.classList.remove("open");
    });
  });

  document.querySelectorAll(".modal-close").forEach(btn => {
    btn.addEventListener("click", () => {
      btn.closest(".modal-backdrop")?.classList.remove("open");
    });
  });
});

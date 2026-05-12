from calendar import monthrange

from flask import Blueprint, render_template
from sqlalchemy import func, extract
from datetime import datetime, timedelta

from ..database import get_db
from .. import models
from .auth import admin_required


# ── Helpers SVG (gráfico progressivo do mês) ──────────────────────────────────

_SW, _SH = 660, 210
_PL, _PR, _PT, _PB = 62, 12, 14, 32
_PW = _SW - _PL - _PR
_PH = _SH - _PT - _PB


def _sfmt(v):
    a = abs(v)
    if a >= 10000: return f"R${v/1000:.0f}k"
    if a >= 1000:  return f"R${v/1000:.1f}k"
    if v < 0:      return f"-R${abs(v):.0f}"
    return f"R${v:.0f}"


def _build_grafico_mes(fat_cum, desp_cum, hoje):
    # Saldo líquido acumulado dia a dia (o "caixa")
    saldo = [round(f - d, 2) for f, d in zip(fat_cum, desp_cum)]
    n     = len(saldo)

    lo = min(0, min(saldo) if saldo else 0)
    hi = max(max(saldo) if saldo else 0, 1)
    rng = hi - lo or 1

    def px(i):
        if n <= 1: return round(_PL + _PW / 2, 1)
        return round(_PL + i / (n - 1) * _PW, 1)

    def py(v):
        return round(_PT + _PH - ((v - lo) / rng * _PH), 1)

    y0    = py(0)
    ticks = [
        {"y": py(lo + rng * i / 4), "label": _sfmt(lo + rng * i / 4)}
        for i in range(5)
    ]

    pts  = [{"x": px(i), "y": py(v), "val": v} for i, v in enumerate(saldo)]
    poly = " ".join(f"{p['x']},{p['y']}" for p in pts)
    x0, xn = px(0), px(n - 1)
    fill = f"{x0},{y0} {poly} {xn},{y0}"

    step   = max(1, n // 8)
    labels = [{"x": px(i), "label": str(i + 1)} for i in range(0, n, step)]
    if n > 1 and (n - 1) % step != 0:
        labels.append({"x": px(n - 1), "label": str(n)})

    saldo_final = saldo[-1] if saldo else 0
    positivo    = saldo_final >= 0

    return {
        "pts": pts, "poly": poly, "fill": fill,
        "ticks": ticks, "labels": labels,
        "y0": y0, "pb": _PT + _PH, "ay": _SH - 4,
        "w": _SW, "h": _SH, "pl": _PL, "pr": _PR,
        "fat_total":   round(fat_cum[-1],  2) if fat_cum  else 0,
        "desp_total":  round(desp_cum[-1], 2) if desp_cum else 0,
        "saldo_final": round(saldo_final, 2),
        "positivo":    positivo,
        "cor":         "#059669" if positivo else "#dc2626",
        "fill_cor":    "rgba(5,150,105,0.12)" if positivo else "rgba(220,38,38,0.10)",
        "mes_label":   hoje.strftime("%B de %Y"),
        "vazio":       (not saldo or max(abs(v) for v in saldo) == 0),
    }

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@admin_required
def index():
    db = get_db()
    hoje = datetime.now()
    inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ── KPIs financeiros do mês atual ─────────────────────────────────────────
    def _soma(tipo, desde=None, categoria=None):
        q = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
            models.MovimentacaoFinanceira.tipo == tipo
        )
        if desde:
            q = q.filter(models.MovimentacaoFinanceira.data >= desde)
        if categoria:
            q = q.filter(models.MovimentacaoFinanceira.categoria == categoria)
        return q.scalar() or 0.0

    entradas_mes   = _soma("entrada", inicio_mes)
    saidas_mes     = _soma("saida",   inicio_mes)

    # Despesas manuais (fixas + variáveis) do Despesa table
    despesas_manuais = db.query(func.sum(models.Despesa.valor)).filter(
        extract("year",  models.Despesa.data_competencia) == hoje.year,
        extract("month", models.Despesa.data_competencia) == hoje.month,
    ).scalar() or 0.0

    total_despesas = saidas_mes + despesas_manuais

    # ── Resumo de estoque ─────────────────────────────────────────────────────
    total_produtos = db.query(func.count(models.Produto.id)).scalar() or 0

    # Produtos abaixo do estoque mínimo (alertas)
    alertas = db.query(models.Produto).filter(
        models.Produto.quantidade <= models.Produto.estoque_minimo
    ).all()

    # ── Parceiros ativos (prévia no dashboard) ────────────────────────────────
    parceiros = db.query(models.Parceiro).filter(
        models.Parceiro.status == "ativo"
    ).order_by(models.Parceiro.nome).limit(6).all()

    # ── Gráfico progressivo: caixa acumulado dia a dia no mês atual ──────────
    today_day = hoje.day

    # Faturamento por dia (VendaFinal.valor_total_liquido)
    fat_dia = [0.0] * today_day
    for vf in db.query(models.VendaFinal).filter(
        extract("year",  models.VendaFinal.data_venda) == hoje.year,
        extract("month", models.VendaFinal.data_venda) == hoje.month,
    ).all():
        d = vf.data_venda.day if vf.data_venda else 1
        if 1 <= d <= today_day:
            fat_dia[d - 1] += vf.valor_total_liquido

    # Despesas por dia — manual (Despesa, pelo criado_em)
    desp_dia = [0.0] * today_day
    for dep in db.query(models.Despesa).filter(
        extract("year",  models.Despesa.criado_em) == hoje.year,
        extract("month", models.Despesa.criado_em) == hoje.month,
    ).all():
        d = dep.criado_em.day if dep.criado_em else 1
        if 1 <= d <= today_day:
            desp_dia[d - 1] += dep.valor

    # Despesas por dia — automáticas (MovimentacaoFinanceira saidas: comissões etc.)
    for mf in db.query(models.MovimentacaoFinanceira).filter(
        models.MovimentacaoFinanceira.tipo == "saida",
        extract("year",  models.MovimentacaoFinanceira.data) == hoje.year,
        extract("month", models.MovimentacaoFinanceira.data) == hoje.month,
    ).all():
        d = mf.data.day if mf.data else 1
        if 1 <= d <= today_day:
            desp_dia[d - 1] += mf.valor

    # Cumulativos
    fat_cum, desp_cum = [], []
    rf = rd = 0.0
    for i in range(today_day):
        rf += fat_dia[i]
        rd += desp_dia[i]
        fat_cum.append(round(rf, 2))
        desp_cum.append(round(rd, 2))

    grafico_mes = _build_grafico_mes(fat_cum, desp_cum, hoje)

    return render_template("index.html",
        active_page="dashboard",
        hoje=hoje.strftime("%d de %B de %Y"),
        financeiro={
            "entradas_mes":   round(entradas_mes, 2),
            "total_despesas": round(total_despesas, 2),
            "lucro_mes":      round(entradas_mes - total_despesas, 2),
        },
        estoque={
            "total_produtos": total_produtos,
            "alertas": [{"id": p.id, "nome": p.nome, "quantidade": p.quantidade,
                         "estoque_minimo": p.estoque_minimo} for p in alertas],
        },
        parceiros=parceiros,
        grafico_mes=grafico_mes,
    )


@bp.route("/apresentacao")
@admin_required
def apresentacao():
    return render_template("apresentacao.html", active_page="apresentacao")

# Responsabilidade: dashboard principal do administrador (rota /).
# Agrega KPIs financeiros do mês, alertas de estoque mínimo, lista de parceiros
# ativos e dados dos últimos 6 meses para o gráfico de fluxo de caixa.

from calendar import monthrange

from flask import Blueprint, render_template, request
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

    _MESES_PT = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                 'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
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
        "mes_label":   f"{_MESES_PT[hoje.month - 1]} de {hoje.year}",
        "vazio":       (not saldo or max(abs(v) for v in saldo) == 0),
    }

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@admin_required
def index():
    db   = get_db()
    hoje = datetime.now()

    # ── Filtro de mês/ano ─────────────────────────────────────────────────────
    mes_num = request.args.get("mes_num", type=int) or hoje.month
    mes_ano = request.args.get("mes_ano", type=int) or hoje.year
    if not (1 <= mes_num <= 12):
        mes_num = hoje.month

    is_mes_atual  = (mes_ano == hoje.year and mes_num == hoje.month)
    _, dias_mes   = monthrange(mes_ano, mes_num)
    ultimo_dia    = hoje.day if is_mes_atual else dias_mes
    mes_ref       = datetime(mes_ano, mes_num, 1)

    # ── KPIs financeiros do mês selecionado ──────────────────────────────────
    entradas_mes = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "entrada",
        extract("year",  models.MovimentacaoFinanceira.data) == mes_ano,
        extract("month", models.MovimentacaoFinanceira.data) == mes_num,
    ).scalar() or 0.0

    saidas_mes = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "saida",
        extract("year",  models.MovimentacaoFinanceira.data) == mes_ano,
        extract("month", models.MovimentacaoFinanceira.data) == mes_num,
    ).scalar() or 0.0

    despesas_manuais = db.query(func.sum(models.Despesa.valor)).filter(
        extract("year",  models.Despesa.data_competencia) == mes_ano,
        extract("month", models.Despesa.data_competencia) == mes_num,
    ).scalar() or 0.0

    total_despesas = saidas_mes + despesas_manuais

    # ── Resumo de estoque ─────────────────────────────────────────────────────
    total_produtos = db.query(func.count(models.Produto.id)).scalar() or 0
    alertas = db.query(models.Produto).filter(
        models.Produto.quantidade <= models.Produto.estoque_minimo
    ).all()

    # ── Parceiros ativos ──────────────────────────────────────────────────────
    parceiros = db.query(models.Parceiro).filter(
        models.Parceiro.status == "ativo"
    ).order_by(models.Parceiro.nome).limit(6).all()

    # ── Gráfico progressivo: caixa acumulado dia a dia ────────────────────────
    fat_dia  = [0.0] * ultimo_dia
    desp_dia = [0.0] * ultimo_dia

    for vf in db.query(models.VendaFinal).filter(
        extract("year",  models.VendaFinal.data_venda) == mes_ano,
        extract("month", models.VendaFinal.data_venda) == mes_num,
    ).all():
        d = vf.data_venda.day if vf.data_venda else 1
        if 1 <= d <= ultimo_dia:
            fat_dia[d - 1] += vf.valor_total_liquido

    for dep in db.query(models.Despesa).filter(
        extract("year",  models.Despesa.criado_em) == mes_ano,
        extract("month", models.Despesa.criado_em) == mes_num,
    ).all():
        d = dep.criado_em.day if dep.criado_em else 1
        if 1 <= d <= ultimo_dia:
            desp_dia[d - 1] += dep.valor

    for mf in db.query(models.MovimentacaoFinanceira).filter(
        models.MovimentacaoFinanceira.tipo == "saida",
        extract("year",  models.MovimentacaoFinanceira.data) == mes_ano,
        extract("month", models.MovimentacaoFinanceira.data) == mes_num,
    ).all():
        d = mf.data.day if mf.data else 1
        if 1 <= d <= ultimo_dia:
            desp_dia[d - 1] += mf.valor

    fat_cum, desp_cum = [], []
    rf = rd = 0.0
    for i in range(ultimo_dia):
        rf += fat_dia[i];  fat_cum.append(round(rf, 2))
        rd += desp_dia[i]; desp_cum.append(round(rd, 2))

    grafico_mes = _build_grafico_mes(fat_cum, desp_cum, mes_ref)

    return render_template("index.html",
        active_page    = "dashboard",
        hoje           = hoje.strftime("%d de %B de %Y"),
        mes_num        = mes_num,
        mes_ano        = mes_ano,
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
        parceiros   = parceiros,
        grafico_mes = grafico_mes,
    )


@bp.route("/apresentacao")
@admin_required
def apresentacao():
    return render_template("apresentacao.html", active_page="apresentacao")

# Responsabilidade: dashboard principal do administrador (rota /).
# Agrega KPIs financeiros do mês, alertas de estoque mínimo, lista de parceiros
# ativos e dados dos últimos 6 meses para o gráfico de fluxo de caixa.

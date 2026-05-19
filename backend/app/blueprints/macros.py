from calendar import monthrange
from datetime import datetime

from flask import Blueprint, render_template
from sqlalchemy import func, extract

from ..database import get_db
from .. import models
from .auth import admin_required

bp = Blueprint("macros", __name__, url_prefix="/macros")

_MESES_PT = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
             'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']


def _meses_anteriores(mes, ano, n=3):
    """Retorna lista de (ano, mes) para os n meses anteriores ao dado."""
    resultado = []
    m, a = mes, ano
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            a -= 1
        resultado.append((a, m))
    return resultado


def _var_pct(atual, anterior):
    if not anterior:
        return None
    return round((atual - anterior) / abs(anterior) * 100, 1)


@bp.route("")
@admin_required
def index():
    db = get_db()
    hoje = datetime.now()
    ano, mes = hoje.year, hoje.month
    dia_atual = hoje.day
    _, dias_no_mes = monthrange(ano, mes)

    # ── BLOCO 1 — Saúde Financeira ─────────────────────────────────────────────

    receita_mes = db.query(func.sum(models.VendaFinal.valor_total_liquido)).filter(
        extract("year",  models.VendaFinal.data_venda) == ano,
        extract("month", models.VendaFinal.data_venda) == mes,
    ).scalar() or 0.0

    desp_mf = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "saida",
        extract("year",  models.MovimentacaoFinanceira.data) == ano,
        extract("month", models.MovimentacaoFinanceira.data) == mes,
    ).scalar() or 0.0

    desp_manual = db.query(func.sum(models.Despesa.valor)).filter(
        extract("year",  models.Despesa.data_competencia) == ano,
        extract("month", models.Despesa.data_competencia) == mes,
    ).scalar() or 0.0

    despesas_mes = desp_mf + desp_manual
    lucro_mes = receita_mes - despesas_mes
    margem_pct = round(lucro_mes / receita_mes * 100, 1) if receita_mes > 0 else 0.0

    fator_proj = dias_no_mes / dia_atual if dia_atual > 0 else 1
    receita_projetada = round(receita_mes * fator_proj, 2)
    lucro_projetado   = round(lucro_mes   * fator_proj, 2)
    dias_restantes    = dias_no_mes - dia_atual

    desp_fixas_mes = db.query(func.sum(models.Despesa.valor)).filter(
        models.Despesa.tipo == "fixo",
        extract("year",  models.Despesa.data_competencia) == ano,
        extract("month", models.Despesa.data_competencia) == mes,
    ).scalar() or 0.0

    breakeven_pct = round(min(receita_mes / desp_fixas_mes * 100, 100), 1) if desp_fixas_mes > 0 else None

    # Mês anterior
    meses_ant = _meses_anteriores(mes, ano, 1)
    ano_ant, mes_ant = meses_ant[0]

    receita_ant = db.query(func.sum(models.VendaFinal.valor_total_liquido)).filter(
        extract("year",  models.VendaFinal.data_venda) == ano_ant,
        extract("month", models.VendaFinal.data_venda) == mes_ant,
    ).scalar() or 0.0

    desp_mf_ant = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "saida",
        extract("year",  models.MovimentacaoFinanceira.data) == ano_ant,
        extract("month", models.MovimentacaoFinanceira.data) == mes_ant,
    ).scalar() or 0.0

    desp_man_ant = db.query(func.sum(models.Despesa.valor)).filter(
        extract("year",  models.Despesa.data_competencia) == ano_ant,
        extract("month", models.Despesa.data_competencia) == mes_ant,
    ).scalar() or 0.0

    despesas_ant = desp_mf_ant + desp_man_ant
    lucro_ant    = receita_ant - despesas_ant

    bloco1 = {
        "receita_mes":      round(receita_mes,   2),
        "despesas_mes":     round(despesas_mes,  2),
        "lucro_mes":        round(lucro_mes,     2),
        "margem_pct":       margem_pct,
        "receita_projetada": receita_projetada,
        "lucro_projetado":  lucro_projetado,
        "dias_restantes":   dias_restantes,
        "desp_fixas_mes":   round(desp_fixas_mes, 2),
        "breakeven_pct":    breakeven_pct,
        "receita_ant":      round(receita_ant,  2),
        "lucro_ant":        round(lucro_ant,    2),
        "mes_ant_nome":     _MESES_PT[mes_ant - 1],
        "var_receita":      _var_pct(receita_mes, receita_ant),
        "var_lucro":        _var_pct(lucro_mes,   lucro_ant),
    }

    # ── BLOCO 2 — Inteligência de Produtos ────────────────────────────────────

    produtos = db.query(models.Produto).all()
    produto_map = {p.id: p for p in produtos}

    vendas_por_prod = db.query(
        models.ItemVendaFinal.produto_id,
        func.sum(models.ItemVendaFinal.quantidade).label("qtd"),
        func.sum(models.ItemVendaFinal.subtotal_liquido).label("receita"),
    ).group_by(models.ItemVendaFinal.produto_id).all()

    roi_list = []
    for row in vendas_por_prod:
        p = produto_map.get(row.produto_id)
        if not p:
            continue
        rec  = float(row.receita or 0)
        qtd  = int(row.qtd or 0)
        custo = qtd * p.preco_custo
        lucro = rec - custo
        roi   = round(lucro / custo * 100, 1) if custo > 0 else None
        margem = round(lucro / rec * 100, 1)  if rec  > 0 else 0.0
        roi_list.append({
            "produto_id":  row.produto_id,
            "nome":        p.nome,
            "qtd_vendida": qtd,
            "receita":     round(rec, 2),
            "custo_total": round(custo, 2),
            "lucro":       round(lucro, 2),
            "roi":         roi,
            "margem":      margem,
        })

    roi_list_ranked = sorted(
        roi_list,
        key=lambda x: x["roi"] if x["roi"] is not None else -9999,
        reverse=True,
    )
    mais_lucrativo = roi_list_ranked[0] if roi_list_ranked else None
    mais_vendido   = max(roi_list, key=lambda x: x["qtd_vendida"]) if roi_list else None

    # Giro de estoque: quantos dias o estoque atual dura com a taxa de venda do mês
    vendas_mes_prod = db.query(
        models.ItemVendaFinal.produto_id,
        func.sum(models.ItemVendaFinal.quantidade).label("qtd"),
    ).join(models.VendaFinal).filter(
        extract("year",  models.VendaFinal.data_venda) == ano,
        extract("month", models.VendaFinal.data_venda) == mes,
    ).group_by(models.ItemVendaFinal.produto_id).all()

    vendas_mes_map = {r.produto_id: int(r.qtd or 0) for r in vendas_mes_prod}

    giro_list = []
    for p in produtos:
        qtd_mes = vendas_mes_map.get(p.id, 0)
        taxa_diaria = qtd_mes / dia_atual if dia_atual > 0 and qtd_mes > 0 else 0
        dias_esgota = round(p.quantidade / taxa_diaria) if taxa_diaria > 0 else None
        giro_list.append({
            "nome":          p.nome,
            "estoque_atual": p.quantidade,
            "vendas_no_mes": qtd_mes,
            "dias_para_escoar": dias_esgota,
            "sem_movimento": qtd_mes == 0 and p.quantidade > 0,
        })
    giro_list.sort(key=lambda x: (
        x["dias_para_escoar"] if x["dias_para_escoar"] is not None else 9999
    ))

    bloco2 = {
        "mais_lucrativo": mais_lucrativo,
        "mais_vendido":   mais_vendido,
        "roi_list":       roi_list_ranked[:10],
        "giro_list":      giro_list[:8],
    }

    # ── BLOCO 3 — Alertas Preditivos ──────────────────────────────────────────

    # Ruptura de estoque
    alertas_estoque = []
    for p in produtos:
        if p.quantidade == 0 or (p.estoque_minimo > 0 and p.quantidade <= p.estoque_minimo):
            alertas_estoque.append({
                "nome":            p.nome,
                "estoque_atual":   p.quantidade,
                "estoque_minimo":  p.estoque_minimo,
                "zerado":          p.quantidade == 0,
            })
    alertas_estoque.sort(key=lambda x: x["estoque_atual"])

    # Despesas acima da média dos últimos 3 meses por categoria
    ultimos3 = _meses_anteriores(mes, ano, 3)
    desp_cat_atual = db.query(
        models.Despesa.categoria,
        func.sum(models.Despesa.valor).label("total"),
    ).filter(
        extract("year",  models.Despesa.data_competencia) == ano,
        extract("month", models.Despesa.data_competencia) == mes,
    ).group_by(models.Despesa.categoria).all()

    alertas_despesas = []
    for row in desp_cat_atual:
        cat = row.categoria or "Sem categoria"
        total_atual = float(row.total or 0)
        vals_ant = []
        for (a_ant, m_ant) in ultimos3:
            v = db.query(func.sum(models.Despesa.valor)).filter(
                models.Despesa.categoria == row.categoria,
                extract("year",  models.Despesa.data_competencia) == a_ant,
                extract("month", models.Despesa.data_competencia) == m_ant,
            ).scalar() or 0.0
            if v > 0:
                vals_ant.append(v)
        if not vals_ant:
            continue
        media_ant = sum(vals_ant) / len(vals_ant)
        if total_atual > media_ant * 1.2 and (total_atual - media_ant) > 5:
            alertas_despesas.append({
                "categoria":      cat,
                "total_atual":    round(total_atual, 2),
                "media_anterior": round(media_ant,   2),
                "diferenca":      round(total_atual - media_ant, 2),
                "variacao_pct":   round((total_atual - media_ant) / media_ant * 100, 1),
            })
    alertas_despesas.sort(key=lambda x: x["variacao_pct"], reverse=True)

    # Canal mais rentável no mês
    pontos_mes = db.query(
        models.VendaFinal.ponto_venda_id,
        func.sum(models.VendaFinal.valor_total_liquido).label("receita"),
        func.count(models.VendaFinal.id).label("num_vendas"),
    ).filter(
        models.VendaFinal.ponto_venda_id.isnot(None),
        extract("year",  models.VendaFinal.data_venda) == ano,
        extract("month", models.VendaFinal.data_venda) == mes,
    ).group_by(models.VendaFinal.ponto_venda_id).order_by(
        func.sum(models.VendaFinal.valor_total_liquido).desc()
    ).all()

    ponto_map = {p.id: p.nome for p in db.query(models.PontoVenda).all()}
    canais_mes = [
        {
            "nome":      ponto_map.get(r.ponto_venda_id, f"Ponto #{r.ponto_venda_id}"),
            "receita":   round(float(r.receita or 0), 2),
            "num_vendas": int(r.num_vendas or 0),
        }
        for r in pontos_mes
    ]

    bloco3 = {
        "alertas_estoque":  alertas_estoque,
        "alertas_despesas": alertas_despesas,
        "canais_mes":       canais_mes,
        "canal_destaque":   canais_mes[0] if canais_mes else None,
    }

    return render_template(
        "macros.html",
        active_page  = "macros",
        bloco1       = bloco1,
        bloco2       = bloco2,
        bloco3       = bloco3,
        mes_nome     = _MESES_PT[mes - 1],
        mes          = mes,
        ano          = ano,
        dia_atual    = dia_atual,
        dias_no_mes  = dias_no_mes,
    )

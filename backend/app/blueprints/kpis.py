from calendar import monthrange
from datetime import datetime

from flask import Blueprint, render_template, request, Response
from sqlalchemy import func, extract

from ..database import get_db
from .. import models
from .auth import admin_required, get_usuario_atual
from . import _excel_export as xls

bp = Blueprint("kpis", __name__, url_prefix="/kpis")

_MESES_PT = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
             'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

def _meses_anteriores(mes, ano, n=3):

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

def _custo_medio_ponderado(db, produto):

    entradas = db.query(models.MovimentacaoEstoque).filter(
        models.MovimentacaoEstoque.produto_id == produto.id,
        models.MovimentacaoEstoque.tipo == "entrada",
    ).all()
    total_qtd = 0
    total_custo = 0.0
    for m in entradas:
        custo_un = m.preco_custo_unitario if m.preco_custo_unitario is not None else produto.preco_custo
        total_qtd  += m.quantidade
        total_custo += (custo_un or 0) * m.quantidade
    if total_qtd == 0:
        return produto.preco_custo or 0.0
    return total_custo / total_qtd

@bp.route("")
@admin_required
def index():
    db = get_db()
    hoje = datetime.now()

    mes = request.args.get("mes", type=int) or hoje.month
    ano = request.args.get("ano", type=int) or hoje.year
    if not (1 <= mes <= 12):
        mes = hoje.month

    is_mes_atual = (ano == hoje.year and mes == hoje.month)
    _, dias_no_mes = monthrange(ano, mes)
    dia_atual = hoje.day if is_mes_atual else dias_no_mes

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

    if is_mes_atual:
        fator_proj = dias_no_mes / dia_atual if dia_atual > 0 else 1
        receita_projetada = round(receita_mes * fator_proj, 2)
        lucro_projetado   = round(lucro_mes   * fator_proj, 2)
        dias_restantes    = dias_no_mes - dia_atual
    else:

        receita_projetada = round(receita_mes, 2)
        lucro_projetado   = round(lucro_mes,   2)
        dias_restantes    = 0

    desp_fixas_mes = db.query(func.sum(models.Despesa.valor)).filter(
        models.Despesa.tipo == "fixo",
        extract("year",  models.Despesa.data_competencia) == ano,
        extract("month", models.Despesa.data_competencia) == mes,
    ).scalar() or 0.0

    breakeven_pct = round(min(receita_mes / desp_fixas_mes * 100, 100), 1) if desp_fixas_mes > 0 else None

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
    margem_ant_pct = round(lucro_ant / receita_ant * 100, 1) if receita_ant > 0 else 0.0

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
        "despesas_ant":     round(despesas_ant, 2),
        "lucro_ant":        round(lucro_ant,    2),
        "margem_ant_pct":   margem_ant_pct,
        "mes_ant_nome":     _MESES_PT[mes_ant - 1],
        "var_receita":      _var_pct(receita_mes,  receita_ant),
        "var_despesas":     _var_pct(despesas_mes, despesas_ant),
        "var_lucro":        _var_pct(lucro_mes,    lucro_ant),
        "var_margem":       round(margem_pct - margem_ant_pct, 1) if (receita_mes > 0 or receita_ant > 0) else None,

        "delta_receita":    round(receita_mes  - receita_ant,    2),
        "delta_despesas":   round(despesas_mes - despesas_ant,   2),
        "delta_lucro":      round(lucro_mes    - lucro_ant,      2),
        "delta_margem":     round(margem_pct   - margem_ant_pct, 1),
    }

    produtos = db.query(models.Produto).all()
    produto_map = {p.id: p for p in produtos}

    custo_medio_map = {p.id: _custo_medio_ponderado(db, p) for p in produtos}

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
        custo_unit = custo_medio_map.get(p.id, p.preco_custo)
        custo = qtd * custo_unit
        lucro = rec - custo
        roi   = round(lucro / custo * 100, 1) if custo > 0 else None
        margem = round(lucro / rec * 100, 1)  if rec  > 0 else 0.0
        roi_list.append({
            "produto_id":  row.produto_id,
            "nome":        p.nome,
            "qtd_vendida": qtd,
            "receita":     round(rec, 2),
            "custo_total": round(custo, 2),
            "custo_medio_un": round(custo_unit, 2),
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

    bloco2 = {
        "mais_lucrativo": mais_lucrativo,
        "mais_vendido":   mais_vendido,
        "roi_list":       roi_list_ranked[:10],
    }

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

    anos_disponiveis = sorted({
        r[0] for r in (
            db.query(extract("year", models.VendaFinal.data_venda)).distinct().all()
            + db.query(extract("year", models.Despesa.data_competencia)).distinct().all()
            + db.query(extract("year", models.MovimentacaoFinanceira.data)).distinct().all()
        ) if r[0] is not None
    } | {hoje.year}, reverse=True)
    anos_disponiveis = [int(a) for a in anos_disponiveis]

    return render_template(
        "kpis.html",
        active_page    = "kpis",
        bloco1         = bloco1,
        bloco2         = bloco2,
        bloco3         = bloco3,
        mes_nome       = _MESES_PT[mes - 1],
        mes            = mes,
        ano            = ano,
        dia_atual      = dia_atual,
        dias_no_mes    = dias_no_mes,
        is_mes_atual   = is_mes_atual,
        meses_pt       = _MESES_PT,
        anos_disponiveis = anos_disponiveis,
    )

@bp.route("/export.xlsx")
@admin_required
def export_xlsx():
    db   = get_db()
    hoje = datetime.now()

    mes = request.args.get("mes", type=int) or hoje.month
    ano = request.args.get("ano", type=int) or hoje.year
    if not (1 <= mes <= 12):
        mes = hoje.month

    is_mes_atual = (ano == hoje.year and mes == hoje.month)
    _, dias_no_mes = monthrange(ano, mes)
    dia_atual = hoje.day if is_mes_atual else dias_no_mes

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
    desp_fixas_mes = db.query(func.sum(models.Despesa.valor)).filter(
        models.Despesa.tipo == "fixo",
        extract("year",  models.Despesa.data_competencia) == ano,
        extract("month", models.Despesa.data_competencia) == mes,
    ).scalar() or 0.0
    breakeven_pct = round(min(receita_mes / desp_fixas_mes * 100, 100), 1) if desp_fixas_mes > 0 else None

    if is_mes_atual:
        fator = dias_no_mes / dia_atual if dia_atual > 0 else 1
        receita_proj = round(receita_mes * fator, 2)
        lucro_proj   = round(lucro_mes   * fator, 2)
    else:
        receita_proj = round(receita_mes, 2)
        lucro_proj   = round(lucro_mes,   2)

    ano_ant, mes_ant = _meses_anteriores(mes, ano, 1)[0]
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
    lucro_ant = receita_ant - despesas_ant
    margem_ant = round(lucro_ant / receita_ant * 100, 1) if receita_ant > 0 else 0.0

    def _var(atual, anterior):
        return _var_pct(atual, anterior)

    produtos = db.query(models.Produto).all()
    produto_map = {p.id: p for p in produtos}
    custo_medio_map = {p.id: _custo_medio_ponderado(db, p) for p in produtos}

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
        rec   = float(row.receita or 0)
        qtd   = int(row.qtd or 0)
        custo_un = custo_medio_map.get(p.id, p.preco_custo)
        custo = qtd * custo_un
        lucro = rec - custo
        roi_v = round(lucro / custo * 100, 1) if custo > 0 else None
        margem = round(lucro / rec * 100, 1) if rec > 0 else 0.0
        roi_list.append({
            "nome": p.nome, "qtd": qtd, "receita": round(rec, 2),
            "custo_un": round(custo_un, 2), "custo_total": round(custo, 2),
            "lucro": round(lucro, 2), "margem": margem, "roi": roi_v,
        })
    roi_list.sort(key=lambda x: x["roi"] if x["roi"] is not None else -9999, reverse=True)

    alertas_estoque = []
    for p in produtos:
        if p.quantidade == 0 or (p.estoque_minimo > 0 and p.quantidade <= p.estoque_minimo):
            alertas_estoque.append({
                "nome": p.nome,
                "atual": p.quantidade,
                "minimo": p.estoque_minimo,
                "status": "Zerado" if p.quantidade == 0 else "Baixo",
            })
    alertas_estoque.sort(key=lambda x: x["atual"])

    pontos_mes = db.query(
        models.VendaFinal.ponto_venda_id,
        func.sum(models.VendaFinal.valor_total_liquido).label("receita"),
        func.count(models.VendaFinal.id).label("num"),
    ).filter(
        models.VendaFinal.ponto_venda_id.isnot(None),
        extract("year",  models.VendaFinal.data_venda) == ano,
        extract("month", models.VendaFinal.data_venda) == mes,
    ).group_by(models.VendaFinal.ponto_venda_id).all()
    ponto_map = {p.id: p.nome for p in db.query(models.PontoVenda).all()}
    total_canais = sum(float(r.receita or 0) for r in pontos_mes)
    canais = [
        {
            "nome": ponto_map.get(r.ponto_venda_id, f"Ponto #{r.ponto_venda_id}"),
            "receita": round(float(r.receita or 0), 2),
            "num": int(r.num or 0),
            "pct": round(float(r.receita or 0) / total_canais * 100, 1) if total_canais > 0 else 0.0,
        }
        for r in pontos_mes
    ]
    canais.sort(key=lambda x: x["receita"], reverse=True)

    ultimos3 = _meses_anteriores(mes, ano, 3)
    desp_cat = db.query(
        models.Despesa.categoria,
        func.sum(models.Despesa.valor).label("total"),
    ).filter(
        extract("year",  models.Despesa.data_competencia) == ano,
        extract("month", models.Despesa.data_competencia) == mes,
    ).group_by(models.Despesa.categoria).all()
    alertas_despesas = []
    for r in desp_cat:
        total_atual = float(r.total or 0)
        vals = []
        for (a_ant, m_ant) in ultimos3:
            v = db.query(func.sum(models.Despesa.valor)).filter(
                models.Despesa.categoria == r.categoria,
                extract("year",  models.Despesa.data_competencia) == a_ant,
                extract("month", models.Despesa.data_competencia) == m_ant,
            ).scalar() or 0.0
            if v > 0:
                vals.append(v)
        if not vals:
            continue
        media = sum(vals) / len(vals)
        if total_atual > media * 1.2 and (total_atual - media) > 5:
            alertas_despesas.append({
                "categoria": r.categoria or "Sem categoria",
                "atual": round(total_atual, 2),
                "media": round(media, 2),
                "dif": round(total_atual - media, 2),
                "var": round((total_atual - media) / media * 100, 1),
            })
    alertas_despesas.sort(key=lambda x: x["var"], reverse=True)

    wb = xls.novo_workbook({"title": f"KPIs {ano}-{mes:02d}"})
    usuario = get_usuario_atual()
    usuario_nome = usuario.nome if usuario else None
    periodo = f"{_MESES_PT[mes-1]}/{ano}"

    ws = wb.create_sheet("Saúde financeira")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Saúde financeira do mês",
                         periodo=periodo, usuario=usuario_nome, span=5)
    mes_ant_nome = _MESES_PT[mes_ant - 1]
    def _row_var(nome, atual, anterior, var_v=None, eh_pp=False):
        delta = round(atual - anterior, 2)
        if var_v is None:
            var_v = _var(atual, anterior)
        var_display = f"{var_v}%" if var_v is not None else "—"
        if eh_pp:
            var_display = f"{var_v} p.p." if var_v is not None else "—"
        return [nome, round(atual, 2), round(anterior, 2), delta, var_display]
    b.table(
        ["Indicador", periodo, mes_ant_nome, "Δ absoluto", "Variação"],
        [
            _row_var("Receita",         receita_mes,    receita_ant),
            _row_var("Despesas",        despesas_mes,   despesas_ant),
            _row_var("Lucro",           lucro_mes,      lucro_ant),
            _row_var("Margem líquida (%)", margem_pct, margem_ant,
                     var_v=round(margem_pct - margem_ant, 1), eh_pp=True),
            ["Despesas fixas",     round(desp_fixas_mes, 2),  None, None, None],
            ["Ponto de equilíbrio", (f"{breakeven_pct}%" if breakeven_pct is not None else "—"),  None, None, None],
            [f"Receita {'projetada' if is_mes_atual else 'realizada'}",  receita_proj, None, None, None],
            [f"Lucro {'projetado'  if is_mes_atual else 'realizado'}",   lucro_proj,   None, None, None],
        ],
        formats=[None, xls.FMT_BRL, xls.FMT_BRL, xls.FMT_BRL, None],
    )
    b.apply_widths()

    ws = wb.create_sheet("ROI por produto")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Desempenho por produto (histórico)",
                         periodo=periodo, usuario=usuario_nome,
                         filtros=["Custo: média ponderada por lote registrado"], span=8)
    rows = [
        [it["nome"], it["qtd"], it["receita"], it["custo_un"], it["custo_total"],
         it["lucro"], it["margem"], (it["roi"] if it["roi"] is not None else "—")]
        for it in roi_list
    ]
    t_qtd = sum(it["qtd"] for it in roi_list)
    t_rec = sum(it["receita"] for it in roi_list)
    t_cus = sum(it["custo_total"] for it in roi_list)
    t_luc = sum(it["lucro"] for it in roi_list)
    t_marg = round(t_luc / t_rec * 100, 1) if t_rec > 0 else 0.0
    t_roi  = round(t_luc / t_cus * 100, 1) if t_cus > 0 else 0.0
    b.table(
        ["Produto", "Qtd vendida", "Receita", "Custo médio un.", "Custo total",
         "Lucro", "Margem %", "ROI %"],
        rows,
        formats=[None, xls.FMT_INT, xls.FMT_BRL, xls.FMT_BRL, xls.FMT_BRL,
                 xls.FMT_BRL, xls.FMT_PCT, xls.FMT_PCT],
        total_row=["TOTAL", t_qtd, round(t_rec, 2), None, round(t_cus, 2),
                   round(t_luc, 2), t_marg, t_roi],
    )
    b.apply_widths()

    ws = wb.create_sheet("Alertas estoque")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Produtos com estoque baixo ou zerado",
                         periodo="Snapshot atual", usuario=usuario_nome, span=4)
    b.table(
        ["Produto", "Estoque atual", "Estoque mínimo", "Status"],
        [[a["nome"], a["atual"], a["minimo"], a["status"]] for a in alertas_estoque],
        formats=[None, xls.FMT_INT, xls.FMT_INT, None],
    )
    b.apply_widths()

    ws = wb.create_sheet("Canais de venda")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Canais de venda",
                         periodo=periodo, usuario=usuario_nome, span=4)
    rows = [[c["nome"], c["receita"], c["num"], c["pct"]] for c in canais]
    t_rec = sum(c["receita"] for c in canais)
    t_n   = sum(c["num"] for c in canais)
    b.table(
        ["Canal", "Receita", "Nº vendas", "% do total"],
        rows,
        formats=[None, xls.FMT_BRL, xls.FMT_INT, xls.FMT_PCT],
        total_row=["TOTAL", round(t_rec, 2), t_n, 100.0 if t_rec > 0 else 0],
    )
    b.apply_widths()

    ws = wb.create_sheet("Despesas atípicas")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Despesas acima da média (3 meses anteriores)",
                         periodo=periodo, usuario=usuario_nome,
                         filtros=["Limite: 20% acima da média"], span=5)
    b.table(
        ["Categoria", "Total atual", "Média 3 meses", "Diferença", "Variação %"],
        [[a["categoria"], a["atual"], a["media"], a["dif"], a["var"]] for a in alertas_despesas],
        formats=[None, xls.FMT_BRL, xls.FMT_BRL, xls.FMT_BRL, xls.FMT_PCT],
    )
    b.apply_widths()

    data = xls.to_response_bytes(wb)
    filename = f"kpis_{ano}-{mes:02d}.xlsx"
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

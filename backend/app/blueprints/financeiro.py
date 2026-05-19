import math
from types import SimpleNamespace
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, flash
from sqlalchemy import func, extract
from sqlalchemy.orm import joinedload

from ..database import get_db
from .. import models
from .auth import login_required, admin_required, get_usuario_atual

bp = Blueprint("financeiro", __name__, url_prefix="/financeiro")

# ── SVG chart helpers (sem JavaScript — tudo renderizado no servidor) ──────────

_MESES_ABR = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']
_SW, _SH = 760, 220          # viewBox
_PL, _PR, _PT, _PB = 70, 15, 12, 36
_PW = _SW - _PL - _PR        # 675
_PH = _SH - _PT - _PB        # 172
_CW = _PW / 12               # 56.25 por coluna


def _sfmt(v):
    a = abs(v)
    if a >= 10000: return f"R${v/1000:.0f}k"
    if a >= 1000:  return f"R${v/1000:.1f}k"
    if v < 0:      return f"-R${abs(v):.0f}"
    return f"R${v:.0f}"


def _svg_bar(values, cf, cs):
    max_v = max(max(values), 0.01)
    ticks = [
        {'y': round(_PT + _PH * (1 - i / 4), 1), 'label': _sfmt(max_v * i / 4)}
        for i in range(5)
    ]
    bw = round(_CW * 0.62, 1)
    bars = []
    for i, v in enumerate(values):
        h = round(max(v, 0) / max_v * _PH, 1)
        bars.append({
            'x':   round(_PL + i * _CW + (_CW - bw) / 2, 1),
            'y':   round(_PT + _PH - h, 1),
            'w':   bw, 'h': h,
            'lx':  round(_PL + i * _CW + _CW / 2, 1),
            'mes': _MESES_ABR[i], 'val': round(v, 2),
        })
    return {'ticks': ticks, 'bars': bars, 'cf': cf, 'cs': cs,
            'pb': _PT + _PH, 'ay': _SH - 4, 'w': _SW, 'h': _SH, 'pl': _PL, 'pr': _PR}


def _svg_hbar(items):
    """Horizontal bar chart — one bar per item, sorted descending."""
    n = len(items)
    if not n:
        return None
    bar_h  = 34
    gap    = 18
    # pl = left pad (location names), pr = right pad (value text ~110px)
    pl, pr, pt, pb = 150, 115, 16, 32
    row_h    = bar_h + gap
    grid_btm = pt + n * row_h - gap
    sh       = grid_btm + pb
    sw       = 700
    pw       = sw - pl - pr   # width available for bars

    max_v = max((it['value'] for it in items), default=0.01) or 0.01

    ticks_x = [
        {'x': round(pl + pw * i / 4, 1), 'label': _sfmt(max_v * i / 4)}
        for i in range(5)
    ]
    bars = []
    for i, it in enumerate(items):
        y  = pt + i * row_h
        w  = round(max(it['value'], 0) / max_v * pw, 1)
        ty = round(y + bar_h / 2 + 4.5, 1)
        bars.append({
            'label': it['label'],
            'value': round(it['value'], 2),
            'y': y, 'w': w, 'bar_h': bar_h,
            'ty': ty,
            'vx': round(pl + w + 8, 1),
        })
    return {
        'bars': bars, 'ticks_x': ticks_x,
        'pl': pl, 'pw': pw, 'pt': pt,
        'sh': sh, 'sw': sw,
        'grid_btm': grid_btm,
        'label_y': grid_btm + 20,
    }


def _svg_pie(items):
    """Pie chart — one slice per item."""
    if not items:
        return None
    total = sum(it['value'] for it in items) or 0.01
    cx, cy, r = 165, 150, 120
    sw, sh = 700, 300
    _COLORS = ['#38a3a5','#059669','#6d28d9','#d97706','#dc2626','#0284c7','#7c3aed','#be185d','#0f766e','#ca8a04']
    slices = []
    start = -math.pi / 2
    for i, it in enumerate(items):
        frac  = it['value'] / total
        angle = frac * 2 * math.pi
        end   = start + angle
        x1 = round(cx + r * math.cos(start), 2)
        y1 = round(cy + r * math.sin(start), 2)
        x2 = round(cx + r * math.cos(end), 2)
        y2 = round(cy + r * math.sin(end), 2)
        large = 1 if angle > math.pi else 0
        slices.append({
            'path':  f"M {cx} {cy} L {x1} {y1} A {r} {r} 0 {large} 1 {x2} {y2} Z",
            'color': _COLORS[i % len(_COLORS)],
            'label': it['label'],
            'value': round(it['value'], 2),
            'pct':   round(frac * 100, 1),
        })
        start = end
    leg_x  = cx * 2 + 30
    legend = [
        {'color': s['color'], 'label': s['label'], 'value': s['value'],
         'pct': s['pct'], 'ry': 30 + i * 38}
        for i, s in enumerate(slices)
    ]
    return {'slices': slices, 'legend': legend, 'leg_x': leg_x,
            'cx': cx, 'cy': cy, 'r': r, 'sw': sw, 'sh': sh}


def _svg_line(series):
    all_v = [v for s in series for v in s['data']] + [0]
    lo, hi = min(all_v), max(all_v + [0.01])
    rng = hi - lo or 1

    def vy(v):
        return round(_PT + _PH - ((v - lo) / rng * _PH), 1)

    ticks = [{'y': vy(lo + rng * i / 4), 'label': _sfmt(lo + rng * i / 4)} for i in range(5)]
    y0 = vy(0)
    rendered = []
    for s in series:
        pts = [{'x': round(_PL + i * _CW + _CW / 2, 1), 'y': vy(v), 'val': round(v, 2)}
               for i, v in enumerate(s['data'])]
        poly = ' '.join(f"{p['x']},{p['y']}" for p in pts)
        fp   = f"{pts[0]['x']},{y0} " + poly + f" {pts[-1]['x']},{y0}"
        rendered.append({'label': s['label'], 'color': s['color'],
                         'fill_color': s.get('fill_color'),
                         'pts': pts, 'poly': poly, 'fill_poly': fp})
    meses = [{'x': round(_PL + i * _CW + _CW / 2, 1), 'label': _MESES_ABR[i]} for i in range(12)]
    return {'ticks': ticks, 'series': rendered, 'meses': meses, 'y0': y0,
            'ay': _SH - 4, 'w': _SW, 'h': _SH, 'pl': _PL, 'pr': _PR}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _soma_mf(db, tipo, parceiro_id=None, desde=None, categoria=None):
    """Soma MovimentacaoFinanceira com filtros opcionais."""
    q = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == tipo
    )
    if parceiro_id:
        q = q.filter(models.MovimentacaoFinanceira.parceiro_id == parceiro_id)
    if desde:
        q = q.filter(models.MovimentacaoFinanceira.data >= desde)
    if categoria:
        q = q.filter(models.MovimentacaoFinanceira.categoria == categoria)
    return q.scalar() or 0.0


def _soma_despesas(db, ano=None, mes=None, excluir_categoria=None):
    """Soma Despesa.valor com filtros opcionais."""
    q = db.query(func.sum(models.Despesa.valor))
    if ano and mes:
        q = q.filter(
            extract("year",  models.Despesa.data_competencia) == ano,
            extract("month", models.Despesa.data_competencia) == mes,
        )
    if excluir_categoria:
        q = q.filter(models.Despesa.categoria != excluir_categoria)
    return q.scalar() or 0.0


def _soma_despesas_cat(db, categoria, ano=None, mes=None):
    """Soma Despesa.valor por categoria."""
    q = db.query(func.sum(models.Despesa.valor)).filter(
        models.Despesa.categoria == categoria
    )
    if ano and mes:
        q = q.filter(
            extract("year",  models.Despesa.data_competencia) == ano,
            extract("month", models.Despesa.data_competencia) == mes,
        )
    return q.scalar() or 0.0


def _resumo(db, parceiro_id=None):
    """
    Resumo financeiro consolidado.
    Receita bruta = entradas em MovimentacaoFinanceira.
    Despesas      = saídas automáticas (produção + comissões) + Despesa manual.
    Faturamento   = receita - despesas totais.
    """
    hoje        = datetime.now()
    inicio_mes  = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ano, mes    = hoje.year, hoje.month

    te   = _soma_mf(db, "entrada", parceiro_id)
    ts   = _soma_mf(db, "saida",   parceiro_id)
    tcom = _soma_mf(db, "saida",   parceiro_id, categoria="Comissão Parceiro")
    me   = _soma_mf(db, "entrada", parceiro_id, desde=inicio_mes)
    ms   = _soma_mf(db, "saida",   parceiro_id, desde=inicio_mes)
    mcom = _soma_mf(db, "saida",   parceiro_id, desde=inicio_mes, categoria="Comissão Parceiro")

    # Custo de produção: legado em MovimentacaoFinanceira + novos em Despesa
    tcp_mf  = _soma_mf(db, "saida", parceiro_id, categoria="Custo de Produção")
    mcp_mf  = _soma_mf(db, "saida", parceiro_id, desde=inicio_mes, categoria="Custo de Produção")
    tcp_d   = _soma_despesas_cat(db, "Custo de Produção")                if not parceiro_id else 0.0
    mcp_d   = _soma_despesas_cat(db, "Custo de Produção", ano=ano, mes=mes) if not parceiro_id else 0.0
    tcp     = tcp_mf + tcp_d
    mcp     = mcp_mf + mcp_d

    # Despesas manuais (exclui Custo de Produção, que já é contado separado)
    td   = _soma_despesas(db,                    excluir_categoria="Custo de Produção") if not parceiro_id else 0.0
    md   = _soma_despesas(db, ano=ano, mes=mes,  excluir_categoria="Custo de Produção") if not parceiro_id else 0.0

    total_desp    = ts + tcp_d + td   # ts já inclui tcp_mf; tcp_d e td são de Despesa
    mes_desp      = ms + mcp_d + md
    lucro_total   = te - total_desp
    lucro_mes     = me - mes_desp

    return {
        "total_entradas":        round(te, 2),
        "total_saidas":          round(ts, 2),
        "total_custo_prod":      round(tcp, 2),
        "total_comissoes":       round(tcom, 2),
        "total_outras_saidas":   round(ts - tcp_mf - tcom, 2),
        "total_despesas_manual": round(td, 2),
        "total_despesas":        round(total_desp, 2),
        "lucro_estimado":        round(lucro_total, 2),

        "mes_atual_entradas":    round(me, 2),
        "mes_atual_saidas":      round(ms, 2),
        "mes_atual_custo_prod":  round(mcp, 2),
        "mes_atual_comissoes":   round(mcom, 2),
        "mes_atual_outras":      round(ms - mcp_mf - mcom, 2),
        "mes_atual_despesas_manual": round(md, 2),
        "mes_atual_despesas":    round(mes_desp, 2),
        "mes_atual_lucro":       round(lucro_mes, 2),
    }


def _faturamento_por_produto(db, ano=None, mes=None, ponto_id=None, metodo_id=None, so_parceiros=False):
    """
    Agrupa ItemVendaFinal por produto retornando quantidade, faturamento e %.
    Filtros opcionais: mês/ano, ponto_venda_id, metodo_recebimento_id, só parceiros.
    """
    q = (
        db.query(
            models.ItemVendaFinal.produto_id,
            models.ItemVendaFinal.nome_produto,
            func.sum(models.ItemVendaFinal.quantidade).label("total_vendido"),
            func.sum(models.ItemVendaFinal.subtotal_liquido).label("faturamento"),
        )
        .join(models.VendaFinal, models.ItemVendaFinal.venda_id == models.VendaFinal.id)
    )

    if ano and mes:
        q = q.filter(
            extract("year",  models.VendaFinal.data_venda) == ano,
            extract("month", models.VendaFinal.data_venda) == mes,
        )
    if ponto_id:
        q = q.filter(models.VendaFinal.ponto_venda_id == ponto_id)
    if metodo_id:
        q = q.filter(models.VendaFinal.metodo_recebimento_id == metodo_id)
    if so_parceiros:
        q = q.filter(models.VendaFinal.parceiro_id.isnot(None))

    rows = (
        q.group_by(models.ItemVendaFinal.produto_id, models.ItemVendaFinal.nome_produto)
        .order_by(func.sum(models.ItemVendaFinal.subtotal_liquido).desc())
        .all()
    )

    total = sum(r.faturamento or 0 for r in rows)
    return [
        {
            "produto_id":    r.produto_id,
            "nome":          r.nome_produto,
            "total_vendido": r.total_vendido,
            "faturamento":   round(r.faturamento or 0, 2),
            "percentual":    round((r.faturamento or 0) / total * 100, 1) if total > 0 else 0,
        }
        for r in rows
    ]


def _faturamento_por_ponto(db, ano=None, mes=None, so_parceiros=False):
    """Agrupa VendaFinal por ponto de venda, excluindo vendas sem ponto."""
    q = (
        db.query(
            models.VendaFinal.ponto_venda_id,
            func.sum(models.VendaFinal.valor_total_liquido).label("faturamento"),
            func.count(models.VendaFinal.id).label("total_vendas"),
        )
        .filter(models.VendaFinal.ponto_venda_id.isnot(None))
    )
    if ano and mes:
        q = q.filter(
            extract("year",  models.VendaFinal.data_venda) == ano,
            extract("month", models.VendaFinal.data_venda) == mes,
        )
    if so_parceiros:
        q = q.filter(models.VendaFinal.parceiro_id.isnot(None))

    rows = (
        q.group_by(models.VendaFinal.ponto_venda_id)
        .order_by(func.sum(models.VendaFinal.valor_total_liquido).desc())
        .all()
    )
    ponto_map = {p.id: p.nome for p in db.query(models.PontoVenda).all()}
    total = sum(r.faturamento or 0 for r in rows)
    return [
        {
            "ponto_nome":   ponto_map.get(r.ponto_venda_id, f"Ponto #{r.ponto_venda_id}"),
            "total_vendas": r.total_vendas,
            "faturamento":  round(r.faturamento or 0, 2),
            "percentual":   round((r.faturamento or 0) / total * 100, 1) if total > 0 else 0,
        }
        for r in rows
    ]


# ── Rota principal ────────────────────────────────────────────────────────────

@bp.route("")
@login_required
def listar():
    db      = get_db()
    usuario = get_usuario_atual()
    tipo    = request.args.get("tipo")

    # Filtros de período para faturamento por produto (admin)
    mes_str  = request.args.get("mes")
    if not mes_str:
        mn = request.args.get("mes_num", type=int)
        ma = request.args.get("mes_ano", type=int)
        if mn and ma:
            mes_str = f"{ma:04d}-{mn:02d}"
    ponto_id = request.args.get("ponto_id") or None
    metod_id = request.args.get("metodo_id") or None
    if ponto_id:
        ponto_id = int(ponto_id)
    if metod_id:
        metod_id = int(metod_id)

    hoje     = datetime.now()
    ano_mes  = (hoje.year, hoje.month)
    if mes_str:
        try:
            dt = datetime.strptime(mes_str, "%Y-%m")
            ano_mes = (dt.year, dt.month)
        except ValueError:
            pass
    ano, mes = ano_mes

    parceiro_id = None if usuario.role == "admin" else usuario.parceiro_id

    # ── Transações para listagem ──────────────────────────────────────────────
    if parceiro_id:
        parceiro_obj = db.query(models.Parceiro).filter_by(id=parceiro_id).first()
        pct = parceiro_obj.comissao_percentual if parceiro_obj else 0.0
        transacoes = []
        pv_ids = [
            row.id for row in
            db.query(models.PreVenda.id).filter(models.PreVenda.parceiro_id == parceiro_id).all()
        ]
        vendas_qr = (
            db.query(models.VendaFinal)
            .filter(models.VendaFinal.pre_venda_id.in_(pv_ids))
            .order_by(models.VendaFinal.data_venda.desc())
            .limit(200)
            .all()
        ) if pv_ids else []
        vendas_manual = (
            db.query(models.VendaFinal)
            .filter(
                models.VendaFinal.parceiro_id == parceiro_id,
                models.VendaFinal.pre_venda_id.is_(None),
            )
            .order_by(models.VendaFinal.data_venda.desc())
            .limit(200)
            .all()
        )
        pv_map = {pv.id: pv for pv in db.query(models.PreVenda).filter(models.PreVenda.id.in_(pv_ids)).all()} if pv_ids else {}

        for vf in vendas_qr + vendas_manual:
            pv        = pv_map.get(vf.pre_venda_id) if vf.pre_venda_id else None
            ref       = pv.token[:8] if pv and pv.token else str(vf.id)
            comissao  = round(vf.valor_total_liquido * pct, 2)
            repasse   = round(vf.valor_total_liquido - comissao, 2)
            forma     = f" — {vf.forma_pagamento}" if vf.forma_pagamento else ""
            tipo_venda = "QR" if vf.pre_venda_id else "Manual"
            transacoes.append(SimpleNamespace(
                id=None, tipo="entrada", categoria="Sua comissão",
                descricao=f"Comissão venda #{ref} [{tipo_venda}]{forma} ({pct*100:.0f}% da receita)",
                valor=comissao, data=vf.data_venda,
            ))
            transacoes.append(SimpleNamespace(
                id=None, tipo="saida", categoria="Repasse empresa",
                descricao=f"Repasse venda #{ref} [{tipo_venda}]{forma}",
                valor=repasse, data=vf.data_venda,
            ))
        if tipo == "entrada":
            transacoes = [t for t in transacoes if t.tipo == "entrada"]
        elif tipo == "saida":
            transacoes = [t for t in transacoes if t.tipo == "saida"]
    else:
        q = db.query(models.MovimentacaoFinanceira).options(
            joinedload(models.MovimentacaoFinanceira.parceiro)
        )
        if tipo in ("entrada", "saida"):
            q = q.filter(models.MovimentacaoFinanceira.tipo == tipo)
        transacoes = q.order_by(models.MovimentacaoFinanceira.data.desc()).limit(200).all()

    # ── Dados específicos do parceiro ─────────────────────────────────────────
    parceiro_comissao_pct = 0.0
    parceiro_lucro        = 0.0
    parceiro_lucro_mes    = 0.0
    if parceiro_id:
        parceiro_obj = db.query(models.Parceiro).filter_by(id=parceiro_id).first()
        if parceiro_obj:
            parceiro_comissao_pct = parceiro_obj.comissao_percentual
            resumo_p = _resumo(db, parceiro_id)
            parceiro_lucro     = round(resumo_p["total_entradas"]     * parceiro_comissao_pct, 2)
            parceiro_lucro_mes = round(resumo_p["mes_atual_entradas"] * parceiro_comissao_pct, 2)

    # ── Dados exclusivos do admin ─────────────────────────────────────────────
    vendas_detalhadas      = []
    resumo_parceiros       = []
    fat_por_produto        = []
    pontos                 = []
    metodos                = []
    despesas_mes           = []
    total_despesas_fixo    = 0.0
    total_despesas_variavel = 0.0
    chart_svg              = None
    chart_aba              = None
    chart_tipo_c           = 'bar'
    chart_ano_c            = None
    chart_produto_id_c     = None
    chart_totais           = None
    todos_produtos_chart   = []
    so_parceiros_prod      = False
    chart_so_parceiros     = False

    if usuario.role == "admin":
        so_parceiros_prod  = request.args.get("so_parceiros") == "1"
        chart_so_parceiros = request.args.get("chart_so_parceiros") == "1"

        pontos  = db.query(models.PontoVenda).filter_by(ativo=True).order_by(models.PontoVenda.nome).all()
        metodos = db.query(models.MetodoRecebimento).filter_by(ativo=True).order_by(models.MetodoRecebimento.nome).all()

        # Faturamento por produto (mês selecionado)
        fat_por_produto = _faturamento_por_produto(
            db, ano=ano, mes=mes, ponto_id=ponto_id, metodo_id=metod_id, so_parceiros=so_parceiros_prod
        )

        # Despesas do mês para o card de resumo
        despesas_mes = (
            db.query(models.Despesa)
            .filter(
                extract("year",  models.Despesa.data_competencia) == ano,
                extract("month", models.Despesa.data_competencia) == mes,
            )
            .order_by(models.Despesa.tipo, models.Despesa.descricao)
            .all()
        )
        total_despesas_fixo     = round(sum(d.valor for d in despesas_mes if d.tipo == "fixo"), 2)
        total_despesas_variavel = round(sum(d.valor for d in despesas_mes if d.tipo == "variavel"), 2)

        # Margem por venda (últimas 50)
        produtos_custo = {p.id: p.preco_custo for p in db.query(models.Produto).all()}
        for vf in (
            db.query(models.VendaFinal)
            .options(joinedload(models.VendaFinal.itens))
            .order_by(models.VendaFinal.data_venda.desc())
            .limit(50)
            .all()
        ):
            custo_total = sum(
                i.quantidade * produtos_custo.get(i.produto_id, 0) for i in vf.itens
            )
            vendas_detalhadas.append({
                "id":       vf.id,
                "data":     vf.data_venda,
                "forma":    vf.forma_pagamento,
                "ponto":    vf.ponto_venda.nome if vf.ponto_venda else None,
                "bruto":    vf.valor_total_bruto,
                "desconto": vf.valor_total_desconto,
                "liquido":  vf.valor_total_liquido,
                "custo":    round(custo_total, 2),
                "margem":   round(vf.valor_total_liquido - custo_total, 2),
                "itens":    [
                    {"nome": i.nome_produto, "qty": i.quantidade,
                     "preco": i.preco_unitario_liquido,
                     "custo": produtos_custo.get(i.produto_id, 0)}
                    for i in vf.itens
                ],
            })

        # ── Análise anual — gráficos SVG ─────────────────────────────────────────
        chart_aba          = request.args.get("chart_aba", "faturamento")
        if chart_aba == 'balanco':   # backward compat
            chart_aba = 'resultado'
        chart_ano_c        = request.args.get("chart_ano", type=int) or hoje.year
        chart_produto_id_c = request.args.get("chart_produto_id", type=int)
        _default_tipo = {'faturamento': 'bar', 'despesas': 'bar', 'resultado': 'line', 'por_local': 'pie'}
        _valid_tipo   = {'faturamento': {'bar', 'line'}, 'despesas': {'bar', 'line'},
                         'resultado': {'line', 'bar'}, 'por_local': {'pie'}}
        chart_tipo_c  = request.args.get("chart_tipo", "")
        if chart_tipo_c not in _valid_tipo.get(chart_aba, set()):
            chart_tipo_c = _default_tipo.get(chart_aba, 'bar')

        c_fat  = [0.0] * 12
        c_desp = [0.0] * 12
        c_ent  = [0.0] * 12
        c_sai  = [0.0] * 12

        if chart_produto_id_c:
            prod_c = db.query(models.Produto).filter_by(id=chart_produto_id_c).first()

            _qfat = (
                db.query(
                    extract("month", models.VendaFinal.data_venda).label("m"),
                    func.sum(models.ItemVendaFinal.subtotal_bruto).label("v"),
                )
                .join(models.VendaFinal, models.ItemVendaFinal.venda_id == models.VendaFinal.id)
                .filter(models.ItemVendaFinal.produto_id == chart_produto_id_c,
                        extract("year", models.VendaFinal.data_venda) == chart_ano_c)
            )
            if chart_so_parceiros:
                _qfat = _qfat.filter(models.VendaFinal.parceiro_id.isnot(None))
            for r in _qfat.group_by("m").all():
                c_fat[int(r.m) - 1] = round(float(r.v or 0), 2)

            _qent = (
                db.query(
                    extract("month", models.VendaFinal.data_venda).label("m"),
                    func.sum(models.ItemVendaFinal.subtotal_liquido).label("v"),
                )
                .join(models.VendaFinal, models.ItemVendaFinal.venda_id == models.VendaFinal.id)
                .filter(models.ItemVendaFinal.produto_id == chart_produto_id_c,
                        extract("year", models.VendaFinal.data_venda) == chart_ano_c)
            )
            if chart_so_parceiros:
                _qent = _qent.filter(models.VendaFinal.parceiro_id.isnot(None))
            for r in _qent.group_by("m").all():
                c_ent[int(r.m) - 1] = round(float(r.v or 0), 2)

            if prod_c:
                for r in db.query(
                    extract("month", models.MovimentacaoFinanceira.data).label("m"),
                    func.sum(models.MovimentacaoFinanceira.valor).label("v"),
                ).filter(models.MovimentacaoFinanceira.tipo == "saida",
                         models.MovimentacaoFinanceira.categoria == "Custo de Produção",
                         models.MovimentacaoFinanceira.descricao.ilike(f"%{prod_c.nome}%"),
                         extract("year", models.MovimentacaoFinanceira.data) == chart_ano_c,
                ).group_by("m").all():
                    c_desp[int(r.m) - 1] = round(float(r.v or 0), 2)
                    c_sai[int(r.m) - 1]  = c_desp[int(r.m) - 1]
        else:
            _qfat2 = (
                db.query(
                    extract("month", models.VendaFinal.data_venda).label("m"),
                    func.sum(models.VendaFinal.valor_total_bruto).label("v"),
                ).filter(extract("year", models.VendaFinal.data_venda) == chart_ano_c)
            )
            if chart_so_parceiros:
                _qfat2 = _qfat2.filter(models.VendaFinal.parceiro_id.isnot(None))
            for r in _qfat2.group_by("m").all():
                c_fat[int(r.m) - 1] = round(float(r.v or 0), 2)

            _qent2 = (
                db.query(
                    extract("month", models.VendaFinal.data_venda).label("m"),
                    func.sum(models.VendaFinal.valor_total_liquido).label("v"),
                ).filter(extract("year", models.VendaFinal.data_venda) == chart_ano_c)
            )
            if chart_so_parceiros:
                _qent2 = _qent2.filter(models.VendaFinal.parceiro_id.isnot(None))
            for r in _qent2.group_by("m").all():
                c_ent[int(r.m) - 1] = round(float(r.v or 0), 2)

            mf_s = [0.0] * 12
            for r in db.query(
                extract("month", models.MovimentacaoFinanceira.data).label("m"),
                func.sum(models.MovimentacaoFinanceira.valor).label("v"),
            ).filter(models.MovimentacaoFinanceira.tipo == "saida",
                     extract("year", models.MovimentacaoFinanceira.data) == chart_ano_c,
            ).group_by("m").all():
                mf_s[int(r.m) - 1] = round(float(r.v or 0), 2)

            dm = [0.0] * 12
            for r in db.query(
                extract("month", models.Despesa.data_competencia).label("m"),
                func.sum(models.Despesa.valor).label("v"),
            ).filter(extract("year", models.Despesa.data_competencia) == chart_ano_c
            ).group_by("m").all():
                dm[int(r.m) - 1] = round(float(r.v or 0), 2)

            c_desp = [round(mf_s[i] + dm[i], 2) for i in range(12)]
            c_sai  = list(c_desp)

        c_res = [round(c_ent[i] - c_sai[i], 2) for i in range(12)]

        # Totais por local (ponto de venda) — um valor agregado por ponto para o ano
        c_local_items = []
        if chart_aba == 'por_local':
            for ponto in pontos:
                _qp = (
                    db.query(func.sum(models.VendaFinal.valor_total_liquido))
                    .filter(
                        models.VendaFinal.ponto_venda_id == ponto.id,
                        extract("year", models.VendaFinal.data_venda) == chart_ano_c,
                    )
                )
                if chart_so_parceiros:
                    _qp = _qp.filter(models.VendaFinal.parceiro_id.isnot(None))
                total_ponto = round(float(_qp.scalar() or 0), 2)
                if total_ponto > 0:
                    c_local_items.append({'label': ponto.nome, 'value': total_ponto})
            c_local_items.sort(key=lambda x: x['value'], reverse=True)

        if chart_aba == 'faturamento':
            if chart_tipo_c == 'line':
                chart_svg = _svg_line([{'data': c_fat, 'label': 'Faturamento bruto', 'color': '#38a3a5', 'fill_color': 'rgba(56,163,165,0.12)'}])
            else:
                chart_svg = _svg_bar(c_fat, 'rgba(56,163,165,0.72)', 'rgba(56,163,165,1)')
        elif chart_aba == 'despesas':
            if chart_tipo_c == 'line':
                chart_svg = _svg_line([{'data': c_desp, 'label': 'Despesas', 'color': '#dc2626', 'fill_color': 'rgba(220,38,38,0.1)'}])
            else:
                chart_svg = _svg_bar(c_desp, 'rgba(220,38,38,0.62)', 'rgba(220,38,38,1)')
        elif chart_aba == 'por_local':
            chart_svg = _svg_pie(c_local_items)
        else:  # resultado
            if chart_tipo_c == 'bar':
                chart_svg = _svg_bar(c_res, 'rgba(56,163,165,0.62)', 'rgba(56,163,165,1)')
            else:
                chart_svg = _svg_line([
                    {'data': c_ent,  'label': 'Entradas',  'color': '#059669', 'fill_color': None},
                    {'data': c_sai,  'label': 'Saídas',    'color': '#dc2626', 'fill_color': None},
                    {'data': c_res,  'label': 'Resultado', 'color': '#38a3a5', 'fill_color': 'rgba(56,163,165,0.12)'},
                ])

        chart_totais = {
            'fat':   round(sum(c_fat),  2),
            'desp':  round(sum(c_desp), 2),
            'ent':   round(sum(c_ent),  2),
            'sai':   round(sum(c_sai),  2),
            'res':   round(sum(c_res),  2),
            'local': round(sum(it['value'] for it in c_local_items), 2),
        }
        todos_produtos_chart = db.query(models.Produto).order_by(models.Produto.nome).all()

        # Resumo por parceiro
        for parceiro in db.query(models.Parceiro).filter_by(status="ativo").all():
            receita = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
                models.MovimentacaoFinanceira.tipo == "entrada",
                models.MovimentacaoFinanceira.parceiro_id == parceiro.id,
            ).scalar() or 0.0
            comissoes = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
                models.MovimentacaoFinanceira.tipo == "saida",
                models.MovimentacaoFinanceira.categoria == "Comissão Parceiro",
                models.MovimentacaoFinanceira.parceiro_id == parceiro.id,
            ).scalar() or 0.0
            if receita > 0 or comissoes > 0:
                resumo_parceiros.append({
                    "id":          parceiro.id,
                    "nome":        parceiro.nome,
                    "comissao_pct": parceiro.comissao_percentual * 100,
                    "receita":     round(receita, 2),
                    "comissao":    round(comissoes, 2),
                    "admin_recebe": round(receita - comissoes, 2),
                })

    return render_template(
        "financeiro.html",
        active_page              = "financeiro",
        resumo                   = _resumo(db, parceiro_id),
        transacoes               = transacoes,
        tipo_filtro              = tipo,
        is_admin                 = usuario.role == "admin",
        vendas_detalhadas        = vendas_detalhadas,
        resumo_parceiros         = resumo_parceiros,
        parceiro_comissao_pct    = parceiro_comissao_pct,
        parceiro_lucro           = parceiro_lucro,
        parceiro_lucro_mes       = parceiro_lucro_mes,
        fat_por_produto          = fat_por_produto,
        pontos                   = pontos,
        metodos                  = metodos,
        ano                      = ano,
        mes                      = mes,
        mes_str                  = f"{ano:04d}-{mes:02d}",
        ponto_id_filtro          = ponto_id,
        metodo_id_filtro         = metod_id,
        so_parceiros_prod        = so_parceiros_prod,
        chart_so_parceiros       = chart_so_parceiros,
        despesas_mes             = despesas_mes,
        total_despesas_fixo      = total_despesas_fixo,
        total_despesas_variavel  = total_despesas_variavel,
        chart_svg                = chart_svg,
        chart_aba                = chart_aba,
        chart_tipo               = chart_tipo_c,
        chart_ano_c              = chart_ano_c,
        chart_produto_id_c       = chart_produto_id_c,
        chart_totais             = chart_totais,
        todos_produtos_chart     = todos_produtos_chart,
    )


@bp.route("/anual")
@admin_required
def anual():
    from flask import jsonify
    ano        = request.args.get("ano", type=int) or datetime.today().year
    produto_id = request.args.get("produto_id", type=int)
    db         = get_db()

    fat  = [0.0] * 12
    desp = [0.0] * 12
    ent  = [0.0] * 12
    sai  = [0.0] * 12

    if produto_id:
        produto = db.query(models.Produto).filter_by(id=produto_id).first()

        # Faturamento bruto do produto por mês
        for r in db.query(
            extract("month", models.VendaFinal.data_venda).label("m"),
            func.sum(models.ItemVendaFinal.subtotal_bruto).label("v"),
        ).join(models.VendaFinal, models.ItemVendaFinal.venda_id == models.VendaFinal.id
        ).filter(
            models.ItemVendaFinal.produto_id == produto_id,
            extract("year", models.VendaFinal.data_venda) == ano,
        ).group_by("m").all():
            fat[int(r.m) - 1] = round(float(r.v or 0), 2)

        # Receita líquida do produto por mês
        for r in db.query(
            extract("month", models.VendaFinal.data_venda).label("m"),
            func.sum(models.ItemVendaFinal.subtotal_liquido).label("v"),
        ).join(models.VendaFinal, models.ItemVendaFinal.venda_id == models.VendaFinal.id
        ).filter(
            models.ItemVendaFinal.produto_id == produto_id,
            extract("year", models.VendaFinal.data_venda) == ano,
        ).group_by("m").all():
            ent[int(r.m) - 1] = round(float(r.v or 0), 2)

        # Custo de produção deste produto por mês
        if produto:
            for r in db.query(
                extract("month", models.MovimentacaoFinanceira.data).label("m"),
                func.sum(models.MovimentacaoFinanceira.valor).label("v"),
            ).filter(
                models.MovimentacaoFinanceira.tipo == "saida",
                models.MovimentacaoFinanceira.categoria == "Custo de Produção",
                models.MovimentacaoFinanceira.descricao.ilike(f"%{produto.nome}%"),
                extract("year", models.MovimentacaoFinanceira.data) == ano,
            ).group_by("m").all():
                desp[int(r.m) - 1] = round(float(r.v or 0), 2)
                sai[int(r.m) - 1]  = desp[int(r.m) - 1]
    else:
        # Faturamento bruto total (sem desconto) por mês
        for r in db.query(
            extract("month", models.VendaFinal.data_venda).label("m"),
            func.sum(models.VendaFinal.valor_total_bruto).label("v"),
        ).filter(extract("year", models.VendaFinal.data_venda) == ano
        ).group_by("m").all():
            fat[int(r.m) - 1] = round(float(r.v or 0), 2)

        # Receita líquida por mês
        for r in db.query(
            extract("month", models.VendaFinal.data_venda).label("m"),
            func.sum(models.VendaFinal.valor_total_liquido).label("v"),
        ).filter(extract("year", models.VendaFinal.data_venda) == ano
        ).group_by("m").all():
            ent[int(r.m) - 1] = round(float(r.v or 0), 2)

        # Saídas automáticas (MovimentacaoFinanceira) por mês
        mf_sai = [0.0] * 12
        for r in db.query(
            extract("month", models.MovimentacaoFinanceira.data).label("m"),
            func.sum(models.MovimentacaoFinanceira.valor).label("v"),
        ).filter(
            models.MovimentacaoFinanceira.tipo == "saida",
            extract("year", models.MovimentacaoFinanceira.data) == ano,
        ).group_by("m").all():
            mf_sai[int(r.m) - 1] = round(float(r.v or 0), 2)

        # Despesas manuais por mês
        desp_man = [0.0] * 12
        for r in db.query(
            extract("month", models.Despesa.data_competencia).label("m"),
            func.sum(models.Despesa.valor).label("v"),
        ).filter(extract("year", models.Despesa.data_competencia) == ano
        ).group_by("m").all():
            desp_man[int(r.m) - 1] = round(float(r.v or 0), 2)

        desp = [round(mf_sai[i] + desp_man[i], 2) for i in range(12)]
        sai  = desp

    produtos = [
        {"id": p.id, "nome": p.nome}
        for p in db.query(models.Produto).order_by(models.Produto.nome).all()
    ]

    return jsonify({
        "faturamento": fat,
        "despesas":    desp,
        "entradas":    ent,
        "saidas":      sai,
        "resultado":   [round(ent[i] - sai[i], 2) for i in range(12)],
        "produtos":    produtos,
        "ano":         ano,
    })


@bp.route("/nova", methods=["POST"])
@admin_required
def criar():
    db       = get_db()
    data_str = request.form.get("data", "").strip()
    data_dt  = None
    if data_str:
        try:
            data_dt = datetime.strptime(data_str, "%Y-%m-%d")
        except ValueError:
            pass

    db.add(models.MovimentacaoFinanceira(
        tipo      = request.form["tipo"],
        descricao = request.form["descricao"],
        valor     = float(request.form["valor"]),
        categoria = request.form.get("categoria") or None,
        data      = data_dt or datetime.now(),
    ))
    db.commit()
    flash("Transação registrada com sucesso.", "success")
    return redirect("/financeiro")


@bp.route("/<int:mov_id>/deletar", methods=["POST"])
@admin_required
def deletar(mov_id):
    db  = get_db()
    mov = db.query(models.MovimentacaoFinanceira).filter(
        models.MovimentacaoFinanceira.id == mov_id
    ).first()
    if mov:
        db.delete(mov)
        db.commit()
        flash("Transação excluída.", "success")
    return redirect("/financeiro")

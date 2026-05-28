from collections import defaultdict
from datetime import datetime

from flask import Blueprint, render_template, redirect, request, Response
from sqlalchemy import extract
from sqlalchemy.orm import joinedload

from ..database import get_db
from .. import models
from .auth import login_required, get_usuario_atual
from . import _excel_export as xls

bp = Blueprint("caixa", __name__, url_prefix="/caixa")

_MESES_PT_C = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

def _parse_mes(mes_str):
    if mes_str:
        try:
            dt = datetime.strptime(mes_str, "%Y-%m")
            return dt.year, dt.month
        except ValueError:
            pass
    hoje = datetime.today()
    return hoje.year, hoje.month

@bp.route("")
@bp.route("/historico")
@login_required
def historico():
    db      = get_db()
    usuario = get_usuario_atual()
    mes_str = request.args.get("mes")
    if not mes_str:
        mn = request.args.get("mes_num", type=int)
        ma = request.args.get("mes_ano", type=int)
        if mn and ma:
            mes_str = f"{ma:04d}-{mn:02d}"
    ano, mes = _parse_mes(mes_str)

    q = db.query(models.VendaFinal).filter(
        extract("year",  models.VendaFinal.data_venda) == ano,
        extract("month", models.VendaFinal.data_venda) == mes,
    )

    if usuario.role != "admin" and usuario.parceiro_id:
        q = q.filter(models.VendaFinal.parceiro_id == usuario.parceiro_id)

    vendas = q.order_by(models.VendaFinal.data_venda.desc()).all()

    return render_template("caixa/historico.html",
        active_page = "caixa",
        vendas      = vendas,
        ano         = ano,
        mes         = mes,
        mes_str     = f"{ano:04d}-{mes:02d}",
    )

@bp.route("/venda/<int:venda_id>")
@login_required
def recibo(venda_id):
    return redirect(f"/vendas/{venda_id}/recibo")

@bp.route("/export.xlsx")
@login_required
def export_xlsx():
    db      = get_db()
    usuario = get_usuario_atual()
    mes_str = request.args.get("mes")
    ano, mes = _parse_mes(mes_str)

    q = (
        db.query(models.VendaFinal)
        .options(
            joinedload(models.VendaFinal.itens),
            joinedload(models.VendaFinal.ponto_venda),
            joinedload(models.VendaFinal.parceiro),
            joinedload(models.VendaFinal.metodo_recebimento),
        )
        .filter(
            extract("year",  models.VendaFinal.data_venda) == ano,
            extract("month", models.VendaFinal.data_venda) == mes,
        )
    )
    if usuario.role != "admin" and usuario.parceiro_id:
        q = q.filter(models.VendaFinal.parceiro_id == usuario.parceiro_id)
    vendas = q.order_by(models.VendaFinal.data_venda.desc()).all()

    wb = xls.novo_workbook({"title": f"Vendas {ano}-{mes:02d}"})
    usuario_nome = usuario.nome if usuario else None
    periodo = f"{_MESES_PT_C[mes-1]}/{ano}"

    total_n        = len(vendas)
    total_bruto    = sum(float(v.valor_total_bruto    or 0) for v in vendas)
    total_desconto = sum(float(v.valor_total_desconto or 0) for v in vendas)
    total_liquido  = sum(float(v.valor_total_liquido  or 0) for v in vendas)
    ticket_medio   = round(total_liquido / total_n, 2) if total_n > 0 else 0.0

    por_canal: dict[str, dict] = defaultdict(lambda: {"n": 0, "fat": 0.0})
    por_forma: dict[str, dict] = defaultdict(lambda: {"n": 0, "fat": 0.0})
    por_produto: dict[int, dict] = {}
    for v in vendas:
        canal = v.ponto_venda.nome if v.ponto_venda else "Sem ponto"
        por_canal[canal]["n"]   += 1
        por_canal[canal]["fat"] += float(v.valor_total_liquido or 0)

        forma = v.forma_pagamento or (v.metodo_recebimento.nome if v.metodo_recebimento else "—")
        por_forma[forma]["n"]   += 1
        por_forma[forma]["fat"] += float(v.valor_total_liquido or 0)

        for it in v.itens:
            d = por_produto.setdefault(it.produto_id, {
                "nome": it.nome_produto, "qtd": 0, "receita": 0.0,
            })
            d["qtd"]     += int(it.quantidade or 0)
            d["receita"] += float(it.subtotal_liquido or 0)

    ws = wb.create_sheet("Resumo")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Resumo de vendas",
                         periodo=periodo, usuario=usuario_nome, span=3)
    b.table(
        ["Indicador", "Valor", ""],
        [
            ["Nº de vendas",       total_n,                 ""],
            ["Faturamento bruto",  round(total_bruto, 2),   ""],
            ["Descontos",          round(total_desconto, 2),""],
            ["Faturamento líquido", round(total_liquido, 2), ""],
            ["Ticket médio",       ticket_medio,            ""],
        ],
        formats=[None, None, None],
    )

    if por_canal:
        b.blank(1)
        canais_rows = [
            [k, v["n"], round(v["fat"], 2),
             round(v["fat"] / total_liquido * 100, 1) if total_liquido > 0 else 0.0]
            for k, v in sorted(por_canal.items(), key=lambda x: x[1]["fat"], reverse=True)
        ]
        b.table(
            ["Canal", "Nº vendas", "Faturamento", "% do total"],
            canais_rows,
            formats=[None, xls.FMT_INT, xls.FMT_BRL, xls.FMT_PCT],
            total_row=["TOTAL", total_n, round(total_liquido, 2), 100.0 if total_liquido > 0 else 0],
        )
    b.apply_widths()

    ws = wb.create_sheet("Vendas do mês")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Vendas do mês",
                         periodo=periodo, usuario=usuario_nome, span=9)
    rows = []
    for v in vendas:
        itens_resumo = " · ".join(
            f"{int(i.quantidade)}× {i.nome_produto}" for i in v.itens
        ) if v.itens else "—"
        rows.append([
            xls._to_brt(v.data_venda),
            v.id,
            v.parceiro.nome if v.parceiro else "—",
            v.ponto_venda.nome if v.ponto_venda else "—",
            v.forma_pagamento or (v.metodo_recebimento.nome if v.metodo_recebimento else "—"),
            itens_resumo,
            float(v.valor_total_bruto    or 0),
            float(v.valor_total_desconto or 0),
            float(v.valor_total_liquido  or 0),
        ])
    b.table(
        ["Data/hora", "Nº venda", "Parceiro", "Ponto de venda", "Forma de pagamento",
         "Itens (resumo)", "Bruto", "Desconto", "Líquido"],
        rows,
        formats=[xls.FMT_DT, xls.FMT_INT, None, None, None, None,
                 xls.FMT_BRL, xls.FMT_BRL, xls.FMT_BRL],
        total_row=["TOTAIS", total_n, None, None, None, None,
                   round(total_bruto, 2), round(total_desconto, 2), round(total_liquido, 2)],
    )
    b.apply_widths()

    ws = wb.create_sheet("Itens vendidos")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Itens vendidos (detalhe linha-a-linha)",
                         periodo=periodo, usuario=usuario_nome, span=8)
    rows = []
    total_qtd  = 0
    total_sub_bruto = 0.0
    total_sub_liq   = 0.0
    for v in vendas:
        for it in v.itens:
            rows.append([
                xls._to_brt(v.data_venda),
                v.id,
                it.nome_produto,
                int(it.quantidade or 0),
                float(it.preco_unitario_bruto   or 0),
                float(it.desconto_valor         or 0),
                float(it.preco_unitario_liquido or 0),
                float(it.subtotal_liquido       or 0),
            ])
            total_qtd       += int(it.quantidade or 0)
            total_sub_bruto += float(it.subtotal_bruto or 0)
            total_sub_liq   += float(it.subtotal_liquido or 0)
    b.table(
        ["Data", "Venda #", "Produto", "Qtd", "Preço un. bruto", "Desconto un.",
         "Preço un. líquido", "Subtotal líquido"],
        rows,
        formats=[xls.FMT_DT, xls.FMT_INT, None, xls.FMT_INT,
                 xls.FMT_BRL, xls.FMT_BRL, xls.FMT_BRL, xls.FMT_BRL],
        total_row=["TOTAIS", None, None, total_qtd, None, None, None, round(total_sub_liq, 2)],
    )
    b.apply_widths()

    ws = wb.create_sheet("Por produto")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Vendas agregadas por produto",
                         periodo=periodo, usuario=usuario_nome, span=4)
    total_rec = sum(d["receita"] for d in por_produto.values())
    prod_rows = [
        [d["nome"], d["qtd"], round(d["receita"], 2),
         round(d["receita"] / total_rec * 100, 1) if total_rec > 0 else 0.0]
        for d in sorted(por_produto.values(), key=lambda x: x["receita"], reverse=True)
    ]
    t_qtd = sum(d["qtd"] for d in por_produto.values())
    b.table(
        ["Produto", "Qtd total", "Receita líquida", "% da receita"],
        prod_rows,
        formats=[None, xls.FMT_INT, xls.FMT_BRL, xls.FMT_PCT],
        total_row=["TOTAL", t_qtd, round(total_rec, 2), 100.0 if total_rec > 0 else 0],
    )
    b.apply_widths()

    ws = wb.create_sheet("Por forma de pagamento")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Vendas por forma de pagamento",
                         periodo=periodo, usuario=usuario_nome, span=4)
    forma_rows = [
        [k, v["n"], round(v["fat"], 2),
         round(v["fat"] / total_liquido * 100, 1) if total_liquido > 0 else 0.0]
        for k, v in sorted(por_forma.items(), key=lambda x: x[1]["fat"], reverse=True)
    ]
    b.table(
        ["Forma", "Nº vendas", "Faturamento", "% do total"],
        forma_rows,
        formats=[None, xls.FMT_INT, xls.FMT_BRL, xls.FMT_PCT],
        total_row=["TOTAL", total_n, round(total_liquido, 2), 100.0 if total_liquido > 0 else 0],
    )
    b.apply_widths()

    data = xls.to_response_bytes(wb)
    filename = f"vendas_{ano}-{mes:02d}.xlsx"
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

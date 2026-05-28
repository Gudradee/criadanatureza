
from collections import defaultdict
from datetime import datetime
from io import BytesIO

from flask import (Blueprint, render_template, request, redirect, flash,
                   Response, abort)
from sqlalchemy import extract, func, or_
from sqlalchemy.orm import joinedload

from ..database import get_db
from .. import models
from .auth import login_required, admin_required, get_usuario_atual
from . import _excel_export as xls

bp = Blueprint("historico", __name__, url_prefix="/historico")

_MESES_PT_H = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

def _parse_mes(mes_str=None):

    if not mes_str:
        mn = request.args.get("mes_num", type=int)
        ma = request.args.get("mes_ano", type=int)
        if mn and ma and 1 <= mn <= 12:
            return ma, mn
    if mes_str:
        try:
            dt = datetime.strptime(mes_str, "%Y-%m")
            return dt.year, dt.month
        except ValueError:
            pass
    hoje = datetime.today()
    return hoje.year, hoje.month

def _periodo_str(ano, mes):
    return f"{ano:04d}-{mes:02d}"

@bp.route("/vendas")
@login_required
def vendas():
    db      = get_db()
    usuario = get_usuario_atual()
    ano, mes = _parse_mes(request.args.get("mes"))

    q = db.query(models.VendaFinal).filter(
        extract("year",  models.VendaFinal.data_venda) == ano,
        extract("month", models.VendaFinal.data_venda) == mes,
    )
    if usuario.role != "admin" and usuario.parceiro_id:
        q = q.filter(models.VendaFinal.parceiro_id == usuario.parceiro_id)
    vendas = q.order_by(models.VendaFinal.data_venda.desc()).all()

    return render_template("historico/vendas.html",
        active_page = "historico_vendas",
        vendas      = vendas,
        ano         = ano,
        mes         = mes,
        mes_str     = _periodo_str(ano, mes),
        meses_pt    = _MESES_PT_H,
    )

@bp.route("/recebimentos")
@login_required
def recebimentos():
    db      = get_db()
    usuario = get_usuario_atual()
    ano, mes = _parse_mes(request.args.get("mes"))
    status_filtro = request.args.get("status", "todos")

    q = (
        db.query(models.ParcelaRecebimento)
        .join(models.VendaFinal, models.ParcelaRecebimento.venda_id == models.VendaFinal.id)
        .options(
            joinedload(models.ParcelaRecebimento.venda)
                .joinedload(models.VendaFinal.parceiro),
            joinedload(models.ParcelaRecebimento.venda)
                .joinedload(models.VendaFinal.ponto_venda),
        )
        .filter(
            extract("year",  models.ParcelaRecebimento.vencimento) == ano,
            extract("month", models.ParcelaRecebimento.vencimento) == mes,
        )
    )
    if usuario.role != "admin" and usuario.parceiro_id:
        q = q.filter(models.VendaFinal.parceiro_id == usuario.parceiro_id)
    if status_filtro == "recebidos":
        q = q.filter(models.ParcelaRecebimento.recebido.is_(True))
    elif status_filtro == "pendentes":
        q = q.filter(models.ParcelaRecebimento.recebido.is_(False))

    parcelas = q.order_by(models.ParcelaRecebimento.vencimento.asc(),
                          models.ParcelaRecebimento.id.asc()).all()

    total_recebido = sum(float(p.valor or 0) for p in parcelas if p.recebido)
    total_pendente = sum(float(p.valor or 0) for p in parcelas if not p.recebido)
    total_geral    = total_recebido + total_pendente

    return render_template("historico/recebimentos.html",
        active_page    = "historico_recebimentos",
        parcelas       = parcelas,
        ano            = ano,
        mes            = mes,
        mes_str        = _periodo_str(ano, mes),
        meses_pt       = _MESES_PT_H,
        status_filtro  = status_filtro,
        total_recebido = round(total_recebido, 2),
        total_pendente = round(total_pendente, 2),
        total_geral    = round(total_geral,    2),
    )

@bp.route("/recebimentos/<int:parcela_id>/marcar", methods=["POST"])
@admin_required
def marcar_recebimento(parcela_id):

    db = get_db()
    parcela = db.query(models.ParcelaRecebimento).filter_by(id=parcela_id).first()
    if not parcela:
        abort(404)
    if parcela.recebido:
        parcela.recebido    = False
        parcela.recebido_em = None
    else:
        parcela.recebido    = True
        parcela.recebido_em = datetime.now()
    db.flush()

    venda = db.query(models.VendaFinal).filter_by(id=parcela.venda_id).first()
    if venda:
        todas = list(venda.parcelas_recebimento)
        venda.recebido    = all(p.recebido for p in todas) if todas else False
        venda.recebido_em = max((p.recebido_em for p in todas if p.recebido_em), default=None) if venda.recebido else None
    db.commit()
    return redirect(request.referrer or "/historico/recebimentos")

@bp.route("/recebimentos/<int:venda_id>/parcelar", methods=["POST"])
@admin_required
def parcelar_recebimento(venda_id):

    db = get_db()
    venda = db.query(models.VendaFinal).filter_by(id=venda_id).first()
    if not venda:
        abort(404)

    try:
        num = int(request.form.get("num_parcelas", "1"))
    except ValueError:
        num = 1
    num = max(1, min(num, 36))

    datas: list[datetime] = []
    for i in range(1, num + 1):
        ds = request.form.get(f"parcela_data_{i}", "").strip()
        try:
            datas.append(datetime.strptime(ds, "%Y-%m-%d") if ds else venda.data_venda)
        except ValueError:
            datas.append(venda.data_venda)

    recebidos_anteriores: dict[int, tuple[bool, datetime | None]] = {
        p.numero: (p.recebido, p.recebido_em) for p in venda.parcelas_recebimento
    }

    db.query(models.ParcelaRecebimento).filter_by(venda_id=venda.id).delete()

    valor_parcela = round(float(venda.valor_total_liquido or 0) / num, 2)
    diff = round(float(venda.valor_total_liquido or 0) - valor_parcela * num, 2)

    for i in range(1, num + 1):
        val = valor_parcela + (diff if i == num else 0)
        rec_ant, rec_em_ant = recebidos_anteriores.get(i, (False, None))
        db.add(models.ParcelaRecebimento(
            venda_id    = venda.id,
            numero      = i,
            total       = num,
            valor       = round(val, 2),
            vencimento  = datas[i - 1],
            recebido    = rec_ant,
            recebido_em = rec_em_ant,
        ))
    db.flush()

    parcelas = db.query(models.ParcelaRecebimento).filter_by(venda_id=venda.id).all()
    venda.recebido    = all(p.recebido for p in parcelas) if parcelas else False
    venda.recebido_em = max((p.recebido_em for p in parcelas if p.recebido_em), default=None) if venda.recebido else None

    db.commit()
    flash(f"Venda #{venda.id} reparcelada em {num}x.", "success")
    return redirect(request.referrer or "/historico/recebimentos")

@bp.route("/pagamentos")
@admin_required
def pagamentos():
    db = get_db()
    ano, mes = _parse_mes(request.args.get("mes"))
    status_filtro = request.args.get("status", "todos")

    q = (
        db.query(models.ParcelaPagamento)
        .options(joinedload(models.ParcelaPagamento.despesa))
        .filter(
            extract("year",  models.ParcelaPagamento.vencimento) == ano,
            extract("month", models.ParcelaPagamento.vencimento) == mes,
        )
    )
    if status_filtro == "pagos":
        q = q.filter(models.ParcelaPagamento.pago.is_(True))
    elif status_filtro == "pendentes":
        q = q.filter(models.ParcelaPagamento.pago.is_(False))

    parcelas = q.order_by(models.ParcelaPagamento.vencimento.asc(),
                          models.ParcelaPagamento.id.asc()).all()

    producao   = [p for p in parcelas if (p.despesa and p.despesa.categoria == "Custo de Produção")]
    outras     = [p for p in parcelas if p not in producao]

    def _totais(lista):
        pago_v     = sum(float(p.valor or 0) for p in lista if p.pago)
        pend_v     = sum(float(p.valor or 0) for p in lista if not p.pago)
        return round(pago_v, 2), round(pend_v, 2), round(pago_v + pend_v, 2)

    pago_prod, pend_prod, total_prod   = _totais(producao)
    pago_out,  pend_out,  total_out    = _totais(outras)
    pago_geral = round(pago_prod + pago_out, 2)
    pend_geral = round(pend_prod + pend_out, 2)
    total_geral = round(pago_geral + pend_geral, 2)

    return render_template("historico/pagamentos.html",
        active_page   = "historico_pagamentos",
        parcelas_prod = producao,
        parcelas_out  = outras,
        ano           = ano,
        mes           = mes,
        mes_str       = _periodo_str(ano, mes),
        meses_pt      = _MESES_PT_H,
        status_filtro = status_filtro,
        pago_prod     = pago_prod,
        pend_prod     = pend_prod,
        total_prod    = total_prod,
        pago_out      = pago_out,
        pend_out      = pend_out,
        total_out     = total_out,
        pago_geral    = pago_geral,
        pend_geral    = pend_geral,
        total_geral   = total_geral,
    )

@bp.route("/pagamentos/<int:parcela_id>/marcar", methods=["POST"])
@admin_required
def marcar_parcela(parcela_id):
    db = get_db()
    parcela = db.query(models.ParcelaPagamento).filter_by(id=parcela_id).first()
    if not parcela:
        abort(404)
    if parcela.pago:
        parcela.pago    = False
        parcela.pago_em = None
    else:
        parcela.pago    = True
        parcela.pago_em = datetime.now()
    db.commit()
    return redirect(request.referrer or "/historico/pagamentos")

@bp.route("/pagamentos/<int:despesa_id>/parcelar", methods=["POST"])
@admin_required
def parcelar_despesa(despesa_id):

    db = get_db()
    despesa = db.query(models.Despesa).filter_by(id=despesa_id).first()
    if not despesa:
        abort(404)

    try:
        num = int(request.form.get("num_parcelas", "1"))
    except ValueError:
        num = 1
    num = max(1, min(num, 36))

    datas: list[datetime] = []
    for i in range(1, num + 1):
        ds = request.form.get(f"parcela_data_{i}", "").strip()
        try:
            datas.append(datetime.strptime(ds, "%Y-%m-%d") if ds else despesa.data_competencia)
        except ValueError:
            datas.append(despesa.data_competencia)

    pagos_anteriores: dict[int, tuple[bool, datetime | None]] = {
        p.numero: (p.pago, p.pago_em) for p in despesa.parcelas
    }

    db.query(models.ParcelaPagamento).filter_by(despesa_id=despesa.id).delete()

    valor_parcela = round(float(despesa.valor or 0) / num, 2)

    total_calculado = round(valor_parcela * num, 2)
    diff = round(float(despesa.valor or 0) - total_calculado, 2)

    for i in range(1, num + 1):
        val = valor_parcela
        if i == num:
            val = round(val + diff, 2)
        pago_ant, pago_em_ant = pagos_anteriores.get(i, (False, None))
        db.add(models.ParcelaPagamento(
            despesa_id = despesa.id,
            numero     = i,
            total      = num,
            valor      = val,
            vencimento = datas[i - 1],
            pago       = pago_ant,
            pago_em    = pago_em_ant,
        ))
    db.commit()
    flash(f"Despesa '{despesa.descricao}' reparcelada em {num}x.", "success")
    return redirect(request.referrer or "/historico/pagamentos")

def criar_parcela_default(db, despesa: "models.Despesa"):

    db.add(models.ParcelaPagamento(
        despesa_id = despesa.id,
        numero     = 1,
        total      = 1,
        valor      = despesa.valor,
        vencimento = despesa.data_competencia,
        pago       = False,
    ))

def criar_parcela_recebimento_default(db, venda: "models.VendaFinal"):

    db.add(models.ParcelaRecebimento(
        venda_id    = venda.id,
        numero      = 1,
        total       = 1,
        valor       = float(venda.valor_total_liquido or 0),
        vencimento  = venda.data_venda,
        recebido    = bool(venda.recebido),
        recebido_em = venda.recebido_em,
    ))

def criar_parcelas_a_partir_do_form(db, despesa: "models.Despesa", form):

    try:
        num = int(form.get("num_parcelas", "1"))
    except (TypeError, ValueError):
        num = 1
    num = max(1, min(num, 36))

    datas: list[datetime] = []
    for i in range(1, num + 1):
        ds = (form.get(f"parcela_data_{i}", "") or "").strip()
        try:
            datas.append(datetime.strptime(ds, "%Y-%m-%d") if ds else despesa.data_competencia)
        except ValueError:
            datas.append(despesa.data_competencia)

    valor_parcela = round(float(despesa.valor or 0) / num, 2)
    diff = round(float(despesa.valor or 0) - valor_parcela * num, 2)
    for i in range(1, num + 1):
        val = valor_parcela + (diff if i == num else 0)
        db.add(models.ParcelaPagamento(
            despesa_id = despesa.id,
            numero     = i,
            total      = num,
            valor      = round(val, 2),
            vencimento = datas[i - 1],
            pago       = False,
        ))
    return num

def _export_response(wb, filename):
    data = xls.to_response_bytes(wb)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@bp.route("/recebimentos/export.xlsx")
@admin_required
def export_recebimentos():
    db       = get_db()
    ano, mes = _parse_mes(request.args.get("mes"))
    status_filtro = request.args.get("status", "todos")

    q = (
        db.query(models.ParcelaRecebimento)
        .join(models.VendaFinal, models.ParcelaRecebimento.venda_id == models.VendaFinal.id)
        .options(
            joinedload(models.ParcelaRecebimento.venda)
                .joinedload(models.VendaFinal.parceiro),
            joinedload(models.ParcelaRecebimento.venda)
                .joinedload(models.VendaFinal.ponto_venda),
        )
        .filter(
            extract("year",  models.ParcelaRecebimento.vencimento) == ano,
            extract("month", models.ParcelaRecebimento.vencimento) == mes,
        )
    )
    if status_filtro == "recebidos":
        q = q.filter(models.ParcelaRecebimento.recebido.is_(True))
    elif status_filtro == "pendentes":
        q = q.filter(models.ParcelaRecebimento.recebido.is_(False))
    parcelas = q.order_by(models.ParcelaRecebimento.vencimento.asc()).all()

    wb = xls.novo_workbook({"title": f"Recebimentos {ano}-{mes:02d}"})
    usuario = get_usuario_atual()
    usuario_nome = usuario.nome if usuario else None
    periodo = f"{_MESES_PT_H[mes-1]}/{ano}"

    ws = wb.create_sheet("Recebimentos")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Histórico de recebimentos",
                         periodo=periodo, usuario=usuario_nome,
                         filtros=[f"Status: {status_filtro}"], span=9)
    rows = []
    t_rec = t_pen = 0.0
    for p in parcelas:
        valor = float(p.valor or 0)
        if p.recebido:
            t_rec += valor
        else:
            t_pen += valor
        v = p.venda
        rows.append([
            xls._to_brt(p.vencimento),
            v.id if v else "—",
            f"{p.numero}/{p.total}",
            (v.parceiro.nome if v and v.parceiro else "—"),
            (v.ponto_venda.nome if v and v.ponto_venda else "—"),
            (v.forma_pagamento if v else "—") or "—",
            valor,
            "Sim" if p.recebido else "Não",
            xls._to_brt(p.recebido_em) if p.recebido_em else None,
        ])
    b.table(
        ["Vencimento", "Venda #", "Parcela", "Parceiro", "Ponto de venda",
         "Forma de pagamento", "Valor", "Recebido?", "Recebido em"],
        rows,
        formats=[xls.FMT_DATE, xls.FMT_INT, None, None, None, None, xls.FMT_BRL, None, xls.FMT_DT],
        total_row=["TOTAIS", None, None, None, None,
                   f"Recebido: R$ {t_rec:,.2f} · Pendente: R$ {t_pen:,.2f}",
                   round(t_rec + t_pen, 2), None, None],
    )
    b.apply_widths()
    return _export_response(wb, f"recebimentos_{ano}-{mes:02d}.xlsx")

@bp.route("/pagamentos/export.xlsx")
@admin_required
def export_pagamentos():
    db       = get_db()
    ano, mes = _parse_mes(request.args.get("mes"))
    status_filtro = request.args.get("status", "todos")

    q = db.query(models.ParcelaPagamento).options(
        joinedload(models.ParcelaPagamento.despesa)
    ).filter(
        extract("year",  models.ParcelaPagamento.vencimento) == ano,
        extract("month", models.ParcelaPagamento.vencimento) == mes,
    )
    if status_filtro == "pagos":
        q = q.filter(models.ParcelaPagamento.pago.is_(True))
    elif status_filtro == "pendentes":
        q = q.filter(models.ParcelaPagamento.pago.is_(False))
    parcelas = q.order_by(models.ParcelaPagamento.vencimento.asc()).all()

    wb = xls.novo_workbook({"title": f"Pagamentos {ano}-{mes:02d}"})
    usuario = get_usuario_atual()
    usuario_nome = usuario.nome if usuario else None
    periodo = f"{_MESES_PT_H[mes-1]}/{ano}"

    def _aba(titulo, lista):
        ws = wb.create_sheet(titulo[:31])
        b = xls.SheetBuilder(ws)
        xls.cabecalho_padrao(b, titulo=titulo, periodo=periodo,
                             usuario=usuario_nome,
                             filtros=[f"Status: {status_filtro}"], span=8)
        rows = []
        t_pago = t_pend = 0.0
        for p in lista:
            valor = float(p.valor or 0)
            if p.pago:
                t_pago += valor
            else:
                t_pend += valor
            rows.append([
                xls._to_brt(p.vencimento),
                (p.despesa.descricao if p.despesa else "—"),
                (p.despesa.categoria if p.despesa else "—") or "—",
                ("Fixo" if p.despesa and p.despesa.tipo == "fixo" else "Variável") if p.despesa else "—",
                f"{p.numero}/{p.total}",
                valor,
                "Sim" if p.pago else "Não",
                xls._to_brt(p.pago_em) if p.pago_em else None,
            ])
        b.table(
            ["Vencimento", "Descrição", "Categoria", "Tipo", "Parcela",
             "Valor", "Pago?", "Pago em"],
            rows,
            formats=[xls.FMT_DATE, None, None, None, None, xls.FMT_BRL, None, xls.FMT_DT],
            total_row=["TOTAIS", None, None, None,
                       f"Pago: R$ {t_pago:,.2f} · Pendente: R$ {t_pend:,.2f}",
                       round(t_pago + t_pend, 2), None, None],
        )
        b.apply_widths()

    producao = [p for p in parcelas if p.despesa and p.despesa.categoria == "Custo de Produção"]
    outras   = [p for p in parcelas if p not in producao]
    _aba("Custos de produção", producao)
    _aba("Outras despesas",    outras)

    return _export_response(wb, f"pagamentos_{ano}-{mes:02d}.xlsx")

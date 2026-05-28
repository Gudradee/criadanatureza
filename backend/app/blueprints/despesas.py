from datetime import datetime, date

from flask import Blueprint, render_template, request, redirect, flash, Response
from sqlalchemy import extract, func
from sqlalchemy.orm import joinedload

from ..database import get_db
from .. import models
from .auth import admin_required, get_usuario_atual
from . import _excel_export as xls
from .historico import criar_parcela_default, criar_parcelas_a_partir_do_form

bp = Blueprint("despesas", __name__, url_prefix="/despesas")

def _parse_mes(mes_str: str | None) -> tuple[int, int]:

    if mes_str:
        try:
            dt = datetime.strptime(mes_str, "%Y-%m")
            return dt.year, dt.month
        except ValueError:
            pass
    hoje = datetime.now()
    return hoje.year, hoje.month

@bp.route("")
@admin_required
def index():
    db      = get_db()
    mes_str = request.args.get("mes")
    if not mes_str:
        mn = request.args.get("mes_num", type=int)
        ma = request.args.get("mes_ano", type=int)
        if mn and ma:
            mes_str = f"{ma:04d}-{mn:02d}"
    ano, mes = _parse_mes(mes_str)

    despesas = (
        db.query(models.Despesa)
        .options(joinedload(models.Despesa.parcelas))
        .filter(
            extract("year",  models.Despesa.data_competencia) == ano,
            extract("month", models.Despesa.data_competencia) == mes,
        )
        .order_by(models.Despesa.criado_em.desc(), models.Despesa.id.desc())
        .all()
    )

    fixas = (
        db.query(models.DespesaFixa)
        .order_by(models.DespesaFixa.descricao)
        .all()
    )

    total_fixo     = sum(d.valor for d in despesas if d.tipo == "fixo")
    total_variavel = sum(d.valor for d in despesas if d.tipo == "variavel")
    total_mes      = total_fixo + total_variavel

    ids_importados = {
        d.despesa_fixa_id
        for d in despesas
        if d.despesa_fixa_id is not None
    }

    return render_template(
        "despesas/index.html",
        active_page     = "despesas",
        despesas        = despesas,
        fixas           = fixas,
        ano             = ano,
        mes             = mes,
        mes_str         = f"{ano:04d}-{mes:02d}",
        total_fixo      = round(total_fixo, 2),
        total_variavel  = round(total_variavel, 2),
        total_mes       = round(total_mes, 2),
        ids_importados  = ids_importados,
    )

@bp.route("/nova", methods=["POST"])
@admin_required
def criar():
    db = get_db()

    descricao = request.form.get("descricao", "").strip()
    valor_str = request.form.get("valor", "0").replace(",", ".")
    categoria = request.form.get("categoria", "").strip() or None
    mes_str   = request.form.get("mes_referencia", "")
    tipo      = request.form.get("tipo", "variavel")

    if not descricao:
        flash("Informe a descrição da despesa.", "warning")
        return redirect(f"/despesas?mes={mes_str}")

    try:
        valor = float(valor_str)
        if valor <= 0:
            raise ValueError
    except ValueError:
        flash("Valor inválido.", "warning")
        return redirect(f"/despesas?mes={mes_str}")

    ano, mes = _parse_mes(mes_str)
    data_competencia = datetime(ano, mes, 1)

    despesa = models.Despesa(
        descricao        = descricao,
        valor            = round(valor, 2),
        tipo             = tipo,
        categoria        = categoria,
        data_competencia = data_competencia,
    )
    db.add(despesa)
    db.flush()

    num = criar_parcelas_a_partir_do_form(db, despesa, request.form)

    db.commit()
    if num > 1:
        flash(f"Despesa '{descricao}' registrada em {num} parcela(s).", "success")
    else:
        flash(f"Despesa '{descricao}' registrada.", "success")
    return redirect(f"/despesas?mes={mes_str}")

@bp.route("/<int:despesa_id>/deletar", methods=["POST"])
@admin_required
def deletar(despesa_id):
    db      = get_db()
    mes_str = request.form.get("mes_referencia", "")
    despesa = db.query(models.Despesa).get(despesa_id)
    if despesa:
        db.delete(despesa)
        db.commit()
        flash("Despesa excluída.", "success")
    return redirect(f"/despesas?mes={mes_str}")

@bp.route("/fixas/nova", methods=["POST"])
@admin_required
def criar_fixa():
    db = get_db()

    descricao    = request.form.get("descricao", "").strip()
    valor_str    = request.form.get("valor_padrao", "0").replace(",", ".")
    categoria    = request.form.get("categoria", "").strip() or None
    mes_str      = request.form.get("mes_referencia", "")

    if not descricao:
        flash("Informe a descrição do custo fixo.", "warning")
        return redirect(f"/despesas?mes={mes_str}")

    try:
        valor = float(valor_str)
        if valor <= 0:
            raise ValueError
    except ValueError:
        flash("Valor inválido.", "warning")
        return redirect(f"/despesas?mes={mes_str}")

    db.add(models.DespesaFixa(
        descricao    = descricao,
        valor_padrao = round(valor, 2),
        categoria    = categoria,
        ativo        = True,
    ))
    db.commit()
    flash(f"Custo fixo '{descricao}' cadastrado.", "success")
    return redirect(f"/despesas?mes={mes_str}")

@bp.route("/fixas/<int:fixa_id>/deletar", methods=["POST"])
@admin_required
def deletar_fixa(fixa_id):
    db      = get_db()
    mes_str = request.form.get("mes_referencia", "")
    fixa    = db.query(models.DespesaFixa).get(fixa_id)
    if fixa:

        fixa.ativo = False
        db.commit()
        flash(f"Custo fixo '{fixa.descricao}' desativado.", "success")
    return redirect(f"/despesas?mes={mes_str}")

@bp.route("/importar-fixas", methods=["POST"])
@admin_required
def importar_fixas():

    db      = get_db()
    mes_str = request.form.get("mes_referencia", "")
    ano, mes = _parse_mes(mes_str)
    data_competencia = datetime(ano, mes, 1)

    ja_importados = {
        row.despesa_fixa_id
        for row in db.query(models.Despesa.despesa_fixa_id).filter(
            extract("year",  models.Despesa.data_competencia) == ano,
            extract("month", models.Despesa.data_competencia) == mes,
            models.Despesa.despesa_fixa_id.isnot(None),
        ).all()
    }

    fixas_ativas = db.query(models.DespesaFixa).filter_by(ativo=True).all()
    importados = 0
    for fixa in fixas_ativas:
        if fixa.id in ja_importados:
            continue
        despesa = models.Despesa(
            descricao        = fixa.descricao,
            valor            = fixa.valor_padrao,
            tipo             = "fixo",
            categoria        = fixa.categoria,
            data_competencia = data_competencia,
            despesa_fixa_id  = fixa.id,
        )
        db.add(despesa)
        db.flush()
        criar_parcela_default(db, despesa)
        importados += 1

    if importados:
        db.commit()
        flash(f"{importados} custo(s) fixo(s) importado(s) para {mes:02d}/{ano}.", "success")
    else:
        flash("Todos os custos fixos já foram importados para este mês.", "info")

    return redirect(f"/despesas?mes={mes_str}")

_MESES_PT_D = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

@bp.route("/export.xlsx")
@admin_required
def export_xlsx():
    db      = get_db()
    mes_str = request.args.get("mes")
    ano, mes = _parse_mes(mes_str)

    despesas_mes = (
        db.query(models.Despesa)
        .filter(
            extract("year",  models.Despesa.data_competencia) == ano,
            extract("month", models.Despesa.data_competencia) == mes,
        )
        .order_by(models.Despesa.tipo, models.Despesa.categoria, models.Despesa.descricao)
        .all()
    )

    wb = xls.novo_workbook({"title": f"Despesas {ano}-{mes:02d}"})
    usuario = get_usuario_atual()
    usuario_nome = usuario.nome if usuario else None
    periodo = f"{_MESES_PT_D[mes-1]}/{ano}"

    ws = wb.create_sheet("Despesas do mês")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Despesas do mês",
                         periodo=periodo, usuario=usuario_nome, span=6)
    rows = []
    total_fixo = 0.0
    total_var  = 0.0
    for d in despesas_mes:
        origem = "Template fixo" if d.despesa_fixa_id else "Manual"
        valor = float(d.valor or 0)
        if d.tipo == "fixo":
            total_fixo += valor
        else:
            total_var += valor
        rows.append([
            "Fixo" if d.tipo == "fixo" else "Variável",
            d.categoria or "—",
            d.descricao,
            xls._to_brt(d.data_competencia),
            valor,
            origem,
        ])
    b.table(
        ["Tipo", "Categoria", "Descrição", "Data competência", "Valor", "Origem"],
        rows,
        formats=[None, None, None, xls.FMT_DATE, xls.FMT_BRL, None],
    )

    b.row_values(["Subtotal fixas",      None, None, None, round(total_fixo, 2), None], formats=[None, None, None, None, xls.FMT_BRL, None], is_total=True)
    b.row_values(["Subtotal variáveis",  None, None, None, round(total_var, 2),  None], formats=[None, None, None, None, xls.FMT_BRL, None], is_total=True)
    b.row_values(["TOTAL DO MÊS",        None, None, None, round(total_fixo + total_var, 2), None], formats=[None, None, None, None, xls.FMT_BRL, None], is_total=True)
    b.apply_widths()

    ws = wb.create_sheet("Templates fixos")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo="Templates de custos fixos (cadastro)",
                         periodo="Snapshot atual", usuario=usuario_nome, span=4)
    fixas = db.query(models.DespesaFixa).order_by(models.DespesaFixa.descricao).all()
    b.table(
        ["Descrição", "Valor padrão", "Categoria", "Ativo"],
        [[f.descricao, float(f.valor_padrao or 0), f.categoria or "—", "Sim" if f.ativo else "Não"] for f in fixas],
        formats=[None, xls.FMT_BRL, None, None],
    )
    b.apply_widths()

    ws = wb.create_sheet(f"Anual {ano} por categoria")
    b = xls.SheetBuilder(ws)
    xls.cabecalho_padrao(b, titulo=f"Histórico de despesas por categoria — {ano}",
                         periodo=f"Janeiro a Dezembro de {ano}",
                         usuario=usuario_nome, span=14)

    matriz: dict[str, list[float]] = {}
    rows_db = db.query(
        models.Despesa.categoria,
        extract("month", models.Despesa.data_competencia).label("m"),
        func.sum(models.Despesa.valor).label("v"),
    ).filter(extract("year", models.Despesa.data_competencia) == ano
    ).group_by(models.Despesa.categoria, "m").all()
    for r in rows_db:
        cat = r.categoria or "Sem categoria"
        if cat not in matriz:
            matriz[cat] = [0.0] * 12
        matriz[cat][int(r.m) - 1] = round(float(r.v or 0), 2)

    headers = ["Categoria"] + [_MESES_PT_D[i][:3] for i in range(12)] + ["Total ano"]
    table_rows = []
    totais_mes = [0.0] * 12
    for cat in sorted(matriz.keys()):
        vals = matriz[cat]
        for i, v in enumerate(vals):
            totais_mes[i] += v
        table_rows.append([cat] + vals + [round(sum(vals), 2)])
    formatos = [None] + [xls.FMT_BRL] * 12 + [xls.FMT_BRL]
    b.table(
        headers,
        table_rows,
        formats=formatos,
        total_row=["TOTAL POR MÊS"] + [round(v, 2) for v in totais_mes] + [round(sum(totais_mes), 2)],
    )
    b.apply_widths()

    data = xls.to_response_bytes(wb)
    filename = f"despesas_{ano}-{mes:02d}.xlsx"
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

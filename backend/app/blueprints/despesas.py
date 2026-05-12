from datetime import datetime, date

from flask import Blueprint, render_template, request, redirect, flash
from sqlalchemy import extract, func

from ..database import get_db
from .. import models
from .auth import admin_required

bp = Blueprint("despesas", __name__, url_prefix="/despesas")


def _parse_mes(mes_str: str | None) -> tuple[int, int]:
    """Converte 'YYYY-MM' em (ano, mes). Usa o mês atual como padrão."""
    if mes_str:
        try:
            dt = datetime.strptime(mes_str, "%Y-%m")
            return dt.year, dt.month
        except ValueError:
            pass
    hoje = datetime.now()
    return hoje.year, hoje.month


# ── Listagem / painel principal ───────────────────────────────────────────────

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

    # Despesas do mês selecionado
    despesas = (
        db.query(models.Despesa)
        .filter(
            extract("year",  models.Despesa.data_competencia) == ano,
            extract("month", models.Despesa.data_competencia) == mes,
        )
        .order_by(models.Despesa.tipo, models.Despesa.descricao)
        .all()
    )

    # Templates de custos fixos
    fixas = (
        db.query(models.DespesaFixa)
        .order_by(models.DespesaFixa.descricao)
        .all()
    )

    total_fixo     = sum(d.valor for d in despesas if d.tipo == "fixo")
    total_variavel = sum(d.valor for d in despesas if d.tipo == "variavel")
    total_mes      = total_fixo + total_variavel

    # IDs das DespesaFixa já importadas neste mês (para o botão de importação)
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


# ── Criar despesa variável (ou fixa avulsa) ───────────────────────────────────

@bp.route("/nova", methods=["POST"])
@admin_required
def criar():
    db = get_db()

    descricao = request.form.get("descricao", "").strip()
    valor_str = request.form.get("valor", "0").replace(",", ".")
    categoria = request.form.get("categoria", "").strip() or None
    mes_str   = request.form.get("mes_referencia", "")
    tipo      = request.form.get("tipo", "variavel")  # fixo | variavel

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

    db.add(models.Despesa(
        descricao        = descricao,
        valor            = round(valor, 2),
        tipo             = tipo,
        categoria        = categoria,
        data_competencia = data_competencia,
    ))
    db.commit()
    flash(f"Despesa '{descricao}' registrada.", "success")
    return redirect(f"/despesas?mes={mes_str}")


# ── Excluir despesa ───────────────────────────────────────────────────────────

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


# ── Criar template de custo fixo ──────────────────────────────────────────────

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


# ── Excluir template de custo fixo ───────────────────────────────────────────

@bp.route("/fixas/<int:fixa_id>/deletar", methods=["POST"])
@admin_required
def deletar_fixa(fixa_id):
    db      = get_db()
    mes_str = request.form.get("mes_referencia", "")
    fixa    = db.query(models.DespesaFixa).get(fixa_id)
    if fixa:
        # Desativa ao invés de deletar para preservar histórico das instâncias
        fixa.ativo = False
        db.commit()
        flash(f"Custo fixo '{fixa.descricao}' desativado.", "success")
    return redirect(f"/despesas?mes={mes_str}")


# ── Importar custos fixos ativos para o mês ───────────────────────────────────

@bp.route("/importar-fixas", methods=["POST"])
@admin_required
def importar_fixas():
    """
    Cria instâncias de Despesa para cada DespesaFixa ativa
    que ainda não foi importada no mês selecionado.
    """
    db      = get_db()
    mes_str = request.form.get("mes_referencia", "")
    ano, mes = _parse_mes(mes_str)
    data_competencia = datetime(ano, mes, 1)

    # IDs já importados neste mês
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
        db.add(models.Despesa(
            descricao        = fixa.descricao,
            valor            = fixa.valor_padrao,
            tipo             = "fixo",
            categoria        = fixa.categoria,
            data_competencia = data_competencia,
            despesa_fixa_id  = fixa.id,
        ))
        importados += 1

    if importados:
        db.commit()
        flash(f"{importados} custo(s) fixo(s) importado(s) para {mes:02d}/{ano}.", "success")
    else:
        flash("Todos os custos fixos já foram importados para este mês.", "info")

    return redirect(f"/despesas?mes={mes_str}")

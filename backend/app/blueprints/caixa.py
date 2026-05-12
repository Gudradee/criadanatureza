from datetime import datetime

from flask import Blueprint, render_template, redirect, request
from sqlalchemy import extract

from ..database import get_db
from .. import models
from .auth import login_required, get_usuario_atual

bp = Blueprint("caixa", __name__, url_prefix="/caixa")


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

    # Parceiro vê apenas as próprias vendas
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

from types import SimpleNamespace

from flask import Blueprint, render_template, request, redirect, flash
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from datetime import datetime

from ..database import get_db
from .. import models
from .auth import login_required, admin_required, get_usuario_atual

bp = Blueprint("financeiro", __name__, url_prefix="/financeiro")


def _resumo(db, parceiro_id=None):
    """Retorna resumo financeiro. Se parceiro_id, filtra apenas aquele parceiro."""
    hoje = datetime.now()
    inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    q = db.query(models.MovimentacaoFinanceira)
    if parceiro_id:
        q = q.filter(models.MovimentacaoFinanceira.parceiro_id == parceiro_id)

    def _soma(tipo, desde=None, categoria=None):
        fq = q.filter(models.MovimentacaoFinanceira.tipo == tipo)
        if desde:
            fq = fq.filter(models.MovimentacaoFinanceira.data >= desde)
        if categoria:
            fq = fq.filter(models.MovimentacaoFinanceira.categoria == categoria)
        return fq.with_entities(func.sum(models.MovimentacaoFinanceira.valor)).scalar() or 0.0

    te   = _soma("entrada")
    ts   = _soma("saida")
    tcp  = _soma("saida", categoria="Custo de Produção")
    tcom = _soma("saida", categoria="Comissão Parceiro")
    me   = _soma("entrada", inicio_mes)
    ms   = _soma("saida",   inicio_mes)
    mcp  = _soma("saida",   inicio_mes, "Custo de Produção")
    mcom = _soma("saida",   inicio_mes, "Comissão Parceiro")

    return {
        "total_entradas":        round(te, 2),
        "total_saidas":          round(ts, 2),
        "total_custo_prod":      round(tcp, 2),
        "total_comissoes":       round(tcom, 2),
        "total_outras_saidas":   round(ts - tcp - tcom, 2),
        "lucro_estimado":        round(te - ts, 2),
        "mes_atual_entradas":    round(me, 2),
        "mes_atual_saidas":      round(ms, 2),
        "mes_atual_custo_prod":  round(mcp, 2),
        "mes_atual_comissoes":   round(mcom, 2),
        "mes_atual_outras":      round(ms - mcp - mcom, 2),
        "mes_atual_lucro":       round(me - ms, 2),
    }


@bp.route("")
@login_required
def listar():
    db       = get_db()
    usuario  = get_usuario_atual()
    tipo     = request.args.get("tipo")

    # Parceiro vê apenas as próprias transações
    parceiro_id = None if usuario.role == "admin" else usuario.parceiro_id

    if parceiro_id:
        # Parceiro vê: comissão (entrada = lucro dele) + repasse (saída = vai para admin)
        # Gerado a partir das VendaFinal vinculadas ao parceiro
        parceiro_obj = db.query(models.Parceiro).filter_by(id=parceiro_id).first()
        pct = parceiro_obj.comissao_percentual if parceiro_obj else 0.0
        transacoes = []
        pv_ids = [
            row.id for row in
            db.query(models.PreVenda.id).filter(models.PreVenda.parceiro_id == parceiro_id).all()
        ]
        vendas_parceiro = (
            db.query(models.VendaFinal)
            .filter(models.VendaFinal.pre_venda_id.in_(pv_ids))
            .order_by(models.VendaFinal.data_venda.desc())
            .limit(200)
            .all()
        ) if pv_ids else []
        # Mapa para buscar token de cada PreVenda sem N+1 queries
        pv_map = {pv.id: pv for pv in db.query(models.PreVenda).filter(models.PreVenda.id.in_(pv_ids)).all()} if pv_ids else {}
        for vf in vendas_parceiro:
            pv = pv_map.get(vf.pre_venda_id)
            token_ref = pv.token[:8] if pv and pv.token else str(vf.id)
            comissao = round(vf.valor_total_liquido * pct, 2)
            repasse  = round(vf.valor_total_liquido - comissao, 2)
            forma = f" — {vf.forma_pagamento}" if vf.forma_pagamento else ""
            transacoes.append(SimpleNamespace(
                id=None, tipo="entrada", categoria="Sua comissão",
                descricao=f"Comissão venda #{token_ref}{forma} ({pct*100:.0f}% da receita)",
                valor=comissao, data=vf.data_venda,
            ))
            transacoes.append(SimpleNamespace(
                id=None, tipo="saida", categoria="Repasse empresa",
                descricao=f"Repasse venda #{token_ref}{forma}",
                valor=repasse, data=vf.data_venda,
            ))
        if tipo == "entrada":
            transacoes = [t for t in transacoes if t.tipo == "entrada"]
        elif tipo == "saida":
            transacoes = [t for t in transacoes if t.tipo == "saida"]
    else:
        q = db.query(models.MovimentacaoFinanceira)
        if tipo in ("entrada", "saida"):
            q = q.filter(models.MovimentacaoFinanceira.tipo == tipo)
        transacoes = q.order_by(models.MovimentacaoFinanceira.data.desc()).limit(200).all()

    # Para parceiro: calcula o lucro dele (receita × comissao_percentual)
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

    # Vendas finais com margem + breakdown por parceiro (admin only)
    vendas_detalhadas = []
    resumo_parceiros  = []
    if usuario.role == "admin":
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
                "id": vf.id, "data": vf.data_venda, "forma": vf.forma_pagamento,
                "bruto": vf.valor_total_bruto, "desconto": vf.valor_total_desconto,
                "liquido": vf.valor_total_liquido,
                "custo": round(custo_total, 2),
                "margem": round(vf.valor_total_liquido - custo_total, 2),
                "itens": [{"nome": i.nome_produto, "qty": i.quantidade,
                           "preco": i.preco_unitario_liquido,
                           "custo": produtos_custo.get(i.produto_id, 0)} for i in vf.itens],
            })

        # Lucro por parceiro
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
                    "id": parceiro.id,
                    "nome": parceiro.nome,
                    "comissao_pct": parceiro.comissao_percentual * 100,
                    "receita": round(receita, 2),
                    "comissao": round(comissoes, 2),
                    "admin_recebe": round(receita - comissoes, 2),
                })

    return render_template("financeiro.html",
        active_page           = "financeiro",
        resumo                = _resumo(db, parceiro_id),
        transacoes            = transacoes,
        tipo_filtro           = tipo,
        is_admin              = usuario.role == "admin",
        vendas_detalhadas     = vendas_detalhadas,
        resumo_parceiros      = resumo_parceiros,
        parceiro_comissao_pct = parceiro_comissao_pct,
        parceiro_lucro        = parceiro_lucro,
        parceiro_lucro_mes    = parceiro_lucro_mes,
    )


@bp.route("/nova", methods=["POST"])
@admin_required
def criar():
    db      = get_db()
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
    mov = db.query(models.MovimentacaoFinanceira).filter(models.MovimentacaoFinanceira.id == mov_id).first()
    if mov:
        db.delete(mov)
        db.commit()
        flash("Transação excluída.", "success")
    return redirect("/financeiro")

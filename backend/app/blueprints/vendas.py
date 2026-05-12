from collections import defaultdict
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, flash, abort
from sqlalchemy.exc import SQLAlchemyError

from ..database import get_db
from .. import models
from .auth import login_required, get_usuario_atual

bp = Blueprint("vendas", __name__, url_prefix="/vendas")


# ── Helpers de estoque ────────────────────────────────────────────────────────

def _em_maos_parceiro(db, parceiro_id: int) -> dict:
    """Calcula quantos itens de cada produto o parceiro tem em mãos."""
    enviado   = defaultdict(int)
    vendido   = defaultdict(int)
    devolvido = defaultdict(int)

    for env in db.query(models.Envio).filter_by(parceiro_id=parceiro_id).all():
        for it in db.query(models.ItemEnvio).filter_by(envio_id=env.id).all():
            enviado[it.produto_id] += it.quantidade

    # Vendas via QR (pré-venda)
    pv_ids = [
        r.id for r in
        db.query(models.PreVenda.id).filter(models.PreVenda.parceiro_id == parceiro_id).all()
    ]
    if pv_ids:
        for vf in db.query(models.VendaFinal).filter(
            models.VendaFinal.pre_venda_id.in_(pv_ids)
        ).all():
            for it in db.query(models.ItemVendaFinal).filter_by(venda_id=vf.id).all():
                vendido[it.produto_id] += it.quantidade

    # Vendas manuais atribuídas ao parceiro
    for vf in db.query(models.VendaFinal).filter(
        models.VendaFinal.parceiro_id == parceiro_id,
        models.VendaFinal.pre_venda_id.is_(None),
    ).all():
        for it in db.query(models.ItemVendaFinal).filter_by(venda_id=vf.id).all():
            vendido[it.produto_id] += it.quantidade

    for dev in db.query(models.Devolucao).filter_by(parceiro_id=parceiro_id).all():
        for it in db.query(models.ItemDevolucao).filter_by(devolucao_id=dev.id).all():
            devolvido[it.produto_id] += it.quantidade

    return {
        pid: max(enviado[pid] - vendido[pid] - devolvido[pid], 0)
        for pid in enviado
    }


def _produtos_disponiveis(db, usuario):
    """
    Retorna lista de dicts {produto, quantidade_disponivel} para o formulário.
    Admin → estoque do almoxarifado. Parceiro → em mãos.
    """
    if usuario.role == "admin":
        return [
            {"produto": p, "quantidade_disponivel": p.quantidade}
            for p in db.query(models.Produto)
            .filter(models.Produto.quantidade > 0)
            .order_by(models.Produto.nome)
            .all()
        ]

    em_maos = _em_maos_parceiro(db, usuario.parceiro_id)
    result = []
    for pid, qty in em_maos.items():
        if qty > 0:
            produto = db.query(models.Produto).get(pid)
            if produto:
                result.append({"produto": produto, "quantidade_disponivel": qty})
    result.sort(key=lambda x: x["produto"].nome)
    return result


# ── Formulário de nova venda ──────────────────────────────────────────────────

@bp.route("/nova")
@login_required
def nova():
    db      = get_db()
    usuario = get_usuario_atual()

    if usuario.role != "admin" and not usuario.parceiro_id:
        abort(403)

    produtos  = _produtos_disponiveis(db, usuario)

    if usuario.role == "admin":
        metodos          = (
            db.query(models.MetodoRecebimento)
            .filter_by(ativo=True)
            .order_by(models.MetodoRecebimento.nome)
            .all()
        )
        metodos_parceiro = []
    else:
        metodos          = []
        metodos_parceiro = (
            db.query(models.MetodoParceiro)
            .filter_by(parceiro_id=usuario.parceiro_id)
            .order_by(models.MetodoParceiro.nome)
            .all()
        )

    pontos    = (
        db.query(models.PontoVenda)
        .filter_by(ativo=True)
        .order_by(models.PontoVenda.nome)
        .all()
    )
    parceiros = []
    if usuario.role == "admin":
        parceiros = (
            db.query(models.Parceiro)
            .filter_by(status="ativo")
            .order_by(models.Parceiro.nome)
            .all()
        )

    return render_template(
        "vendas/nova.html",
        active_page      = "nova_venda",
        produtos         = produtos,
        metodos          = metodos,
        metodos_parceiro = metodos_parceiro,
        pontos           = pontos,
        parceiros        = parceiros,
        is_admin         = usuario.role == "admin",
    )


# ── Confirmar venda manual ────────────────────────────────────────────────────

@bp.route("/nova", methods=["POST"])
@login_required
def criar():
    db      = get_db()
    usuario = get_usuario_atual()

    if usuario.role != "admin" and not usuario.parceiro_id:
        abort(403)

    # ── Cabeçalho da venda ────────────────────────────────────────────────────
    ponto_id    = request.form.get("ponto_venda_id") or None
    observacoes = request.form.get("observacoes", "").strip()

    if ponto_id:
        ponto_id = int(ponto_id)

    # Método de recebimento: admin usa FK global; parceiro usa nome direto
    if usuario.role == "admin":
        metodo_id   = request.form.get("metodo_recebimento_id") or None
        metodo_nome = None
        if metodo_id:
            metodo_id  = int(metodo_id)
            metodo_obj = db.query(models.MetodoRecebimento).get(metodo_id)
            metodo_nome = metodo_obj.nome if metodo_obj else None
    else:
        metodo_id   = None
        metodo_nome = request.form.get("forma_pagamento") or None

    # Parceiro logado: a venda é sempre atribuída a ele mesmo
    if usuario.role == "admin":
        raw = request.form.get("parceiro_id") or None
        parceiro_id = int(raw) if raw else None
    else:
        parceiro_id = usuario.parceiro_id

    # ── Itens do formulário ───────────────────────────────────────────────────
    produto_ids    = request.form.getlist("produto_id[]")
    quantidades    = request.form.getlist("quantidade[]")
    precos         = request.form.getlist("preco_unitario[]")
    desconto_total = float(request.form.get("desconto_total", "0").replace(",", ".") or "0")
    desconto_total = max(0.0, desconto_total)

    if not produto_ids:
        flash("Adicione ao menos um produto à venda.", "warning")
        return redirect("/vendas/nova")

    itens_form = []
    for i in range(len(produto_ids)):
        try:
            pid  = int(produto_ids[i])
            qty  = int(quantidades[i])
            prec = float(str(precos[i]).replace(",", "."))
            if qty > 0:
                itens_form.append({"produto_id": pid, "quantidade": qty, "preco": prec})
        except (ValueError, IndexError):
            continue

    if not itens_form:
        flash("Nenhum item válido informado.", "warning")
        return redirect("/vendas/nova")

    # ── Validação de estoque ──────────────────────────────────────────────────
    eh_venda_parceiro = bool(parceiro_id)
    em_maos_map = _em_maos_parceiro(db, parceiro_id) if eh_venda_parceiro else {}

    for item in itens_form:
        produto = db.query(models.Produto).get(item["produto_id"])
        if not produto:
            flash(f"Produto ID {item['produto_id']} não encontrado.", "warning")
            return redirect("/vendas/nova")

        if eh_venda_parceiro:
            disponivel = em_maos_map.get(item["produto_id"], 0)
            if disponivel < item["quantidade"]:
                flash(
                    f"'{produto.nome}': parceiro tem {disponivel} em mãos, "
                    f"pedido requer {item['quantidade']}.",
                    "warning",
                )
                return redirect("/vendas/nova")
        else:
            if produto.quantidade < item["quantidade"]:
                flash(
                    f"'{produto.nome}': estoque insuficiente "
                    f"({produto.quantidade} disponível).",
                    "warning",
                )
                return redirect("/vendas/nova")

    # ── Transação atômica ─────────────────────────────────────────────────────
    try:
        total_bruto = 0.0
        itens_venda = []

        for item in itens_form:
            produto   = db.query(models.Produto).get(item["produto_id"])
            sub_bruto = round(item["preco"] * item["quantidade"], 2)
            total_bruto += sub_bruto

            itens_venda.append(models.ItemVendaFinal(
                produto_id             = item["produto_id"],
                nome_produto           = produto.nome,
                quantidade             = item["quantidade"],
                preco_unitario_bruto   = item["preco"],
                desconto_valor         = 0.0,
                desconto_percentual    = 0.0,
                preco_unitario_liquido = item["preco"],
                subtotal_bruto         = sub_bruto,
                subtotal_liquido       = sub_bruto,
            ))

            # Baixa estoque apenas para vendas diretas (sem parceiro)
            if not eh_venda_parceiro:
                produto.quantidade -= item["quantidade"]
                db.add(models.MovimentacaoEstoque(
                    produto_id = item["produto_id"],
                    tipo       = "saida",
                    quantidade = item["quantidade"],
                    motivo     = "Venda manual",
                ))

        total_bruto    = round(total_bruto, 2)
        total_desconto = round(min(desconto_total, total_bruto), 2)
        total_liquido  = round(total_bruto - total_desconto, 2)

        venda = models.VendaFinal(
            pre_venda_id          = None,
            metodo_recebimento_id = metodo_id,
            ponto_venda_id        = ponto_id,
            parceiro_id           = parceiro_id,
            forma_pagamento       = metodo_nome,
            valor_total_bruto     = round(total_bruto, 2),
            valor_total_desconto  = round(total_desconto, 2),
            valor_total_liquido   = round(total_liquido, 2),
            observacoes           = observacoes or None,
            data_venda            = datetime.now(),
        )
        db.add(venda)
        db.flush()  # gera venda.id

        for iv in itens_venda:
            iv.venda_id = venda.id
            db.add(iv)

        # Descrição financeira
        partes = ["Venda manual"]
        if metodo_nome:
            partes.append(metodo_nome)
        if ponto_id:
            ponto_obj = db.query(models.PontoVenda).get(ponto_id)
            if ponto_obj:
                partes.append(f"@ {ponto_obj.nome}")

        db.add(models.MovimentacaoFinanceira(
            tipo        = "entrada",
            categoria   = "Venda Direta",
            descricao   = " — ".join(partes),
            valor       = round(total_liquido, 2),
            data        = datetime.now(),
            parceiro_id = parceiro_id,
        ))

        # Comissão automática quando a venda é de um parceiro
        if parceiro_id:
            parceiro_obj = db.query(models.Parceiro).get(parceiro_id)
            if parceiro_obj and parceiro_obj.comissao_percentual > 0:
                comissao = round(total_liquido * parceiro_obj.comissao_percentual, 2)
                if comissao > 0.001:
                    db.add(models.MovimentacaoFinanceira(
                        tipo        = "saida",
                        categoria   = "Comissão Parceiro",
                        descricao   = (
                            f"Comissão {parceiro_obj.nome} — Venda #{venda.id} "
                            f"({parceiro_obj.comissao_percentual * 100:.1f}% sobre receita líquida)"
                        ),
                        valor       = comissao,
                        data        = datetime.now(),
                        parceiro_id = parceiro_id,
                    ))

        db.commit()
        flash(
            f"Venda registrada com sucesso! "
            f"Total bruto: R$ {total_bruto:,.2f} | "
            f"Desconto: R$ {total_desconto:,.2f} | "
            f"Total líquido: R$ {total_liquido:,.2f}",
            "success",
        )
        return redirect(f"/vendas/{venda.id}/recibo")

    except SQLAlchemyError:
        db.rollback()
        flash("Erro ao registrar a venda. Tente novamente.", "warning")
        return redirect("/vendas/nova")


# ── Recibo da venda ───────────────────────────────────────────────────────────

@bp.route("/<int:venda_id>/recibo")
@login_required
def recibo(venda_id):
    db    = get_db()
    venda = db.query(models.VendaFinal).get(venda_id)
    if not venda:
        abort(404)
    return render_template("vendas/recibo.html", active_page="caixa", venda=venda)

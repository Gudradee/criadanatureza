from datetime import datetime

from flask import Blueprint, render_template, request, redirect, flash, abort
from sqlalchemy.exc import SQLAlchemyError

from ..database import get_db
from .. import models
from .auth import login_required, get_usuario_atual

bp = Blueprint("caixa", __name__, url_prefix="/caixa")


# ── Tela inicial: entrar com o token do QR Code ───────────────────────────────

@bp.route("")
@login_required
def index():
    db      = get_db()
    usuario = get_usuario_atual()

    # Auto-cancela pedidos expirados que ainda estão como "aguardando"
    agora = datetime.now()
    expirados = db.query(models.PreVenda).filter(
        models.PreVenda.status == models.StatusPreVenda.aguardando,
        models.PreVenda.expira_em != None,
        models.PreVenda.expira_em < agora,
    ).all()
    for pv in expirados:
        pv.status = models.StatusPreVenda.cancelada
    if expirados:
        db.commit()

    q = db.query(models.PreVenda).filter(
        models.PreVenda.status == models.StatusPreVenda.aguardando
    )
    # Parceiro vê apenas os pedidos do próprio catálogo
    if usuario.role != "admin" and usuario.parceiro_id:
        q = q.filter(models.PreVenda.parceiro_id == usuario.parceiro_id)

    pendentes = q.order_by(models.PreVenda.criado_em.desc()).all()
    return render_template("caixa/index.html", active_page="caixa", pendentes=pendentes)


@bp.route("/buscar", methods=["POST"])
@login_required
def buscar():
    token = request.form.get("token", "").strip()
    if not token:
        flash("Informe o código do pedido.", "warning")
        return redirect("/caixa")
    return redirect(f"/caixa/pedido/{token}")


# ── Visualizar pedido + formulário de desconto ────────────────────────────────

@bp.route("/pedido/<token>")
@login_required
def ver_pedido(token):
    db = get_db()
    pre_venda = db.query(models.PreVenda).filter_by(token=token).first()

    if not pre_venda:
        flash("Pedido não encontrado.", "warning")
        return redirect("/caixa")

    # Pedido já confirmado → ir direto para o recibo
    if pre_venda.status == models.StatusPreVenda.confirmada and pre_venda.venda_final:
        return redirect(f"/caixa/venda/{pre_venda.venda_final.id}")

    # Verificar expiração
    if pre_venda.expira_em and datetime.now() > pre_venda.expira_em:
        if pre_venda.status != models.StatusPreVenda.cancelada:
            pre_venda.status = models.StatusPreVenda.cancelada
            db.commit()
        flash("Este pedido expirou. O cliente precisa gerar um novo.", "warning")
        return redirect("/caixa")

    if pre_venda.status == models.StatusPreVenda.cancelada:
        flash("Este pedido foi cancelado.", "warning")
        return redirect("/caixa")

    # Montar itens para exibição (com verificação de estoque em tempo real)
    itens = []
    total_bruto = 0.0
    tem_problema = False

    for item in pre_venda.itens:
        produto = item.produto
        sub = produto.preco_venda * item.quantidade
        total_bruto += sub
        estoque_ok = produto.quantidade >= item.quantidade

        if not estoque_ok:
            tem_problema = True

        itens.append({
            "item":       item,
            "produto":    produto,
            "subtotal":   sub,
            "estoque_ok": estoque_ok,
        })

    return render_template("caixa/pedido.html",
        active_page  = "caixa",
        pre_venda    = pre_venda,
        itens        = itens,
        total_bruto  = total_bruto,
        tem_problema = tem_problema,
    )


# ── Confirmar venda: a transação central do sistema ───────────────────────────

@bp.route("/pedido/<token>/confirmar", methods=["POST"])
@login_required
def confirmar(token):
    db = get_db()

    pre_venda = db.query(models.PreVenda).filter_by(token=token).first()

    if not pre_venda:
        abort(404)

    # ── Guardiões: validações antes de qualquer escrita ───────────────────────

    if pre_venda.status != models.StatusPreVenda.aguardando:
        flash("Este pedido já foi processado ou está inválido.", "warning")
        return redirect(f"/caixa/pedido/{token}")

    if pre_venda.expira_em and datetime.now() > pre_venda.expira_em:
        pre_venda.status = models.StatusPreVenda.cancelada
        db.commit()
        flash("Pedido expirado. O cliente deve gerar um novo.", "warning")
        return redirect("/caixa")

    # ── Ler formulário do caixa ────────────────────────────────────────────────
    # Os descontos vêm SOMENTE deste formulário administrativo
    # O painel público nunca envia preços ou descontos

    forma_pagamento = request.form.get("forma_pagamento", "").strip()
    observacoes     = request.form.get("observacoes", "").strip()

    descontos = {}
    for item in pre_venda.itens:
        campo = request.form.get(f"desconto_{item.produto_id}", "0").replace(",", ".")
        try:
            descontos[item.produto_id] = max(0.0, float(campo))
        except ValueError:
            descontos[item.produto_id] = 0.0

    # ── Validar estoque de TODOS os itens antes de escrever qualquer coisa ────
    # Para vendas de parceiro, o estoque "disponível" é o que ele tem em mãos
    # (enviado - já vendido - devolvido), não o almoxarifado do admin.

    from collections import defaultdict as _dd

    def _em_maos_parceiro(parceiro_id):
        enviado  = _dd(int)
        vendido  = _dd(int)
        devolvido = _dd(int)
        for env in db.query(models.Envio).filter_by(parceiro_id=parceiro_id).all():
            for it in db.query(models.ItemEnvio).filter_by(envio_id=env.id).all():
                enviado[it.produto_id] += it.quantidade
        _pv_ids = [
            r.id for r in
            db.query(models.PreVenda.id).filter(models.PreVenda.parceiro_id == parceiro_id).all()
        ]
        if _pv_ids:
            for vf in db.query(models.VendaFinal).filter(models.VendaFinal.pre_venda_id.in_(_pv_ids)).all():
                for it in db.query(models.ItemVendaFinal).filter_by(venda_id=vf.id).all():
                    vendido[it.produto_id] += it.quantidade
        for dev in db.query(models.Devolucao).filter_by(parceiro_id=parceiro_id).all():
            for it in db.query(models.ItemDevolucao).filter_by(devolucao_id=dev.id).all():
                devolvido[it.produto_id] += it.quantidade
        return {pid: max(enviado[pid] - vendido[pid] - devolvido[pid], 0) for pid in enviado}

    eh_venda_parceiro = bool(pre_venda.parceiro_id)
    em_maos_map = _em_maos_parceiro(pre_venda.parceiro_id) if eh_venda_parceiro else {}

    erros_estoque = []
    for item in pre_venda.itens:
        produto = db.query(models.Produto).get(item.produto_id)
        if not produto:
            erros_estoque.append(f"Produto ID {item.produto_id} não encontrado.")
            continue
        if eh_venda_parceiro:
            disponiveis = em_maos_map.get(item.produto_id, 0)
            if disponiveis < item.quantidade:
                erros_estoque.append(
                    f"'{produto.nome}': parceiro tem {disponiveis} em mãos, "
                    f"pedido quer {item.quantidade}."
                )
        else:
            if produto.quantidade < item.quantidade:
                erros_estoque.append(
                    f"'{produto.nome}': precisa de {item.quantidade}, "
                    f"disponível apenas {produto.quantidade}."
                )

    if erros_estoque:
        for erro in erros_estoque:
            flash(erro, "warning")
        return redirect(f"/caixa/pedido/{token}")

    # ── Transação atômica: tudo ou nada ───────────────────────────────────────

    try:
        total_bruto    = 0.0
        total_desconto = 0.0
        total_liquido  = 0.0
        itens_venda    = []

        for item in pre_venda.itens:
            produto = db.query(models.Produto).get(item.produto_id)

            # Preço bruto = preço atual do produto (nunca o valor vindo do cliente)
            preco_bruto = produto.preco_venda

            # Desconto definido pelo operador no caixa
            desc_valor = descontos.get(item.produto_id, 0.0)
            # Clamp: desconto não pode ser negativo nem maior que o preço
            desc_valor = max(0.0, min(desc_valor, preco_bruto))

            preco_liquido = preco_bruto - desc_valor
            desc_pct      = (desc_valor / preco_bruto * 100) if preco_bruto > 0 else 0.0

            sub_bruto   = round(preco_bruto   * item.quantidade, 2)
            sub_liquido = round(preco_liquido * item.quantidade, 2)

            total_bruto    += sub_bruto
            total_desconto += round(desc_valor * item.quantidade, 2)
            total_liquido  += sub_liquido

            # Fotografia histórica — imutável após este ponto
            itens_venda.append(models.ItemVendaFinal(
                produto_id             = item.produto_id,
                nome_produto           = produto.nome,       # snapshot do nome
                quantidade             = item.quantidade,
                preco_unitario_bruto   = preco_bruto,
                desconto_valor         = desc_valor,
                desconto_percentual    = round(desc_pct, 4),
                preco_unitario_liquido = preco_liquido,
                subtotal_bruto         = sub_bruto,
                subtotal_liquido       = sub_liquido,
            ))

            # Baixar estoque apenas para vendas diretas (não de parceiro)
            # Em vendas de parceiro o estoque já foi movido ao envio do produto
            if not eh_venda_parceiro:
                produto.quantidade -= item.quantidade
                db.add(models.MovimentacaoEstoque(
                    produto_id = item.produto_id,
                    tipo       = "saida",
                    quantidade = item.quantidade,
                    motivo     = f"Venda QR #{token[:8]}",
                ))

        # Cabeçalho da venda
        venda = models.VendaFinal(
            pre_venda_id         = pre_venda.id,
            forma_pagamento      = forma_pagamento,
            valor_total_bruto    = round(total_bruto, 2),
            valor_total_desconto = round(total_desconto, 2),
            valor_total_liquido  = round(total_liquido, 2),
            observacoes          = observacoes or None,
            data_venda           = datetime.now(),
        )
        db.add(venda)
        db.flush()  # gera venda.id sem commitar ainda

        for iv in itens_venda:
            iv.venda_id = venda.id
            db.add(iv)

        # Entrada no fluxo de caixa — parceiro_id preserva a origem da venda
        db.add(models.MovimentacaoFinanceira(
            tipo        = "entrada",
            categoria   = "Venda Direta",
            descricao   = (
                f"Venda QR #{token[:8]}"
                + (f" — {forma_pagamento}" if forma_pagamento else "")
            ),
            valor       = round(total_liquido, 2),
            data        = datetime.now(),
            parceiro_id = pre_venda.parceiro_id,
        ))

        # Comissão automática quando a venda é de um parceiro
        # Base = receita líquida da venda (consignado: parceiro não tem custo de produto)
        if pre_venda.parceiro_id:
            parceiro_venda = db.query(models.Parceiro).filter_by(id=pre_venda.parceiro_id).first()
            if parceiro_venda and parceiro_venda.comissao_percentual > 0:
                comissao_total = round(total_liquido * parceiro_venda.comissao_percentual, 2)
                if comissao_total > 0.001:
                    db.add(models.MovimentacaoFinanceira(
                        tipo        = "saida",
                        categoria   = "Comissão Parceiro",
                        descricao   = (
                            f"Comissão {parceiro_venda.nome} — Venda #{token[:8]}"
                            f" ({parceiro_venda.comissao_percentual * 100:.1f}% sobre receita líquida)"
                        ),
                        valor       = comissao_total,
                        data        = datetime.now(),
                        parceiro_id = pre_venda.parceiro_id,
                    ))

        # Fechar o pedido
        pre_venda.status = models.StatusPreVenda.confirmada

        db.commit()  # ← único commit — se qualquer passo falhar, tudo é revertido

        flash(
            f"Venda confirmada! "
            f"Total bruto: R$ {total_bruto:,.2f} | "
            f"Desconto: R$ {total_desconto:,.2f} | "
            f"Total líquido: R$ {total_liquido:,.2f}",
            "success"
        )
        return redirect(f"/caixa/venda/{venda.id}")

    except SQLAlchemyError as e:
        db.rollback()
        flash(f"Erro ao confirmar venda. Tente novamente.", "warning")
        return redirect(f"/caixa/pedido/{token}")


# ── Recibo da venda confirmada ────────────────────────────────────────────────

@bp.route("/venda/<int:venda_id>")
@login_required
def recibo(venda_id):
    db = get_db()
    venda = db.query(models.VendaFinal).get(venda_id)
    if not venda:
        abort(404)
    return render_template("caixa/recibo.html",
        active_page = "caixa",
        venda       = venda,
    )


# ── Histórico de vendas diretas ───────────────────────────────────────────────

@bp.route("/historico")
@login_required
def historico():
    db      = get_db()
    usuario = get_usuario_atual()

    q = db.query(models.VendaFinal).join(
        models.PreVenda, models.VendaFinal.pre_venda_id == models.PreVenda.id
    )

    # Parceiro vê apenas as próprias vendas
    if usuario.role != "admin" and usuario.parceiro_id:
        q = q.filter(models.PreVenda.parceiro_id == usuario.parceiro_id)

    vendas = q.order_by(models.VendaFinal.data_venda.desc()).limit(100).all()
    return render_template("caixa/historico.html",
        active_page = "caixa",
        vendas      = vendas,
    )

from collections import defaultdict
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, flash
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash

from ..database import get_db
from .. import models
from .auth import admin_required

bp = Blueprint("parceiros", __name__, url_prefix="/parceiros")


# ── Helpers de cálculo ────────────────────────────────────────────────────────

def _calcular_saldo(parceiro, db):
    """Consolida enviado/vendido/devolvido e calcula valor em mãos + receita via caixa."""
    enviado_map   = defaultdict(int)
    vendido_map   = defaultdict(int)
    devolvido_map = defaultdict(int)

    for envio in parceiro.envios:
        for item in envio.itens:
            enviado_map[item.produto_id] += item.quantidade
    for venda in parceiro.vendas:
        for item in venda.itens:
            vendido_map[item.produto_id] += item.quantidade
    for dev in parceiro.devolucoes:
        for item in dev.itens:
            devolvido_map[item.produto_id] += item.quantidade

    total_enviado   = sum(enviado_map.values())
    total_vendido   = sum(vendido_map.values())
    total_devolvido = sum(devolvido_map.values())
    em_maos_total   = max(total_enviado - total_vendido - total_devolvido, 0)

    # Valor em mãos baseado no preco_venda cadastrado no produto
    produto_ids = list(enviado_map.keys())
    produtos = {p.id: p for p in db.query(models.Produto).filter(models.Produto.id.in_(produto_ids)).all()} if produto_ids else {}

    valor_em_maos = 0.0
    for pid, env_qty in enviado_map.items():
        em_maos = max(env_qty - vendido_map[pid] - devolvido_map[pid], 0)
        preco = produtos[pid].preco_venda if pid in produtos else 0.0
        valor_em_maos += em_maos * preco

    # Receita total de vendas via caixa (VendaFinal) — inclui desconto aplicado pelo operador
    vendas_finais = (
        db.query(models.VendaFinal)
        .join(models.PreVenda, models.VendaFinal.pre_venda_id == models.PreVenda.id)
        .filter(models.PreVenda.parceiro_id == parceiro.id)
        .all()
    )
    receita_total   = sum(v.valor_total_liquido for v in vendas_finais)
    desconto_total  = sum(v.valor_total_desconto for v in vendas_finais)
    total_vendas_caixa = len(vendas_finais)

    return {
        "total_enviado":     total_enviado,
        "total_vendido":     total_vendido,
        "total_devolvido":   total_devolvido,
        "em_maos":           em_maos_total,
        "valor_em_maos":     round(valor_em_maos, 2),
        "receita_total":     round(receita_total, 2),
        "desconto_total":    round(desconto_total, 2),
        "total_vendas_caixa": total_vendas_caixa,
    }


def _historico(parceiro_id, db):
    """Monta lista cronológica de envios, vendas via caixa e devoluções de um parceiro."""
    historico = []

    for e in db.query(models.Envio).options(
        joinedload(models.Envio.itens).joinedload(models.ItemEnvio.produto)
    ).filter(models.Envio.parceiro_id == parceiro_id).all():
        total = sum(i.quantidade * i.preco_unitario for i in e.itens)
        historico.append({
            "tipo": "envio",
            "data": e.criado_em.isoformat() if e.criado_em else None,
            "observacoes": e.observacoes,
            "total": total,
            "itens": [{"produto": i.produto.nome if i.produto else "—", "quantidade": i.quantidade, "preco_unitario": i.preco_unitario} for i in e.itens],
        })

    # Vendas via caixa (VendaFinal) — contêm desconto por item
    for vf in (
        db.query(models.VendaFinal)
        .join(models.PreVenda, models.VendaFinal.pre_venda_id == models.PreVenda.id)
        .filter(models.PreVenda.parceiro_id == parceiro_id)
        .options(joinedload(models.VendaFinal.itens))
        .all()
    ):
        historico.append({
            "tipo": "venda_final",
            "data": vf.data_venda.isoformat() if vf.data_venda else None,
            "observacoes": vf.observacoes,
            "total_bruto": vf.valor_total_bruto,
            "desconto": vf.valor_total_desconto,
            "total_liquido": vf.valor_total_liquido,
            "forma_pagamento": vf.forma_pagamento,
            "itens": [{
                "produto": i.nome_produto,
                "quantidade": i.quantidade,
                "preco_unitario": i.preco_unitario_bruto,
                "desconto": i.desconto_valor,
                "subtotal": i.subtotal_liquido,
            } for i in vf.itens],
        })

    for d in db.query(models.Devolucao).options(
        joinedload(models.Devolucao.itens).joinedload(models.ItemDevolucao.produto)
    ).filter(models.Devolucao.parceiro_id == parceiro_id).all():
        historico.append({
            "tipo": "devolucao",
            "data": d.criado_em.isoformat() if d.criado_em else None,
            "observacoes": d.observacoes,
            "total": 0,
            "itens": [{"produto": i.produto.nome if i.produto else "—", "quantidade": i.quantidade, "preco_unitario": i.preco_unitario} for i in d.itens],
        })

    historico.sort(key=lambda x: x["data"] or "", reverse=True)
    return historico


def _parse_itens():
    """Extrai e valida a lista de itens (produto_id, quantidade, preco) do form."""
    produto_ids = request.form.getlist("produto_id")
    quantidades = request.form.getlist("quantidade")
    precos = request.form.getlist("preco_unitario")
    itens = []
    for i in range(len(produto_ids)):
        pid = produto_ids[i] if i < len(produto_ids) else ""
        qty = quantidades[i] if i < len(quantidades) else ""
        preco = precos[i] if i < len(precos) else "0"
        if pid and qty and pid.strip() and qty.strip():
            try:
                itens.append({"produto_id": int(pid), "quantidade": int(qty), "preco_unitario": float(preco or 0)})
            except (ValueError, TypeError):
                pass
    return itens


# ── CRUD de parceiros ─────────────────────────────────────────────────────────

@bp.route("")
@admin_required
def listar():
    db = get_db()
    parceiros = db.query(models.Parceiro).order_by(models.Parceiro.nome).all()
    return render_template("parceiros.html", active_page="parceiros", parceiros=parceiros)


@bp.route("/novo", methods=["GET"])
@admin_required
def form_novo():
    return render_template("parceiro_form.html", active_page="parceiros", parceiro=None)


@bp.route("/novo", methods=["POST"])
@admin_required
def criar():
    db = get_db()
    nome = request.form["nome"]

    # Criação opcional de login vinculado ao parceiro
    criar_login = request.form.get("criar_login") == "1"
    if criar_login:
        username = request.form.get("login_username", "").strip().lower()
        senha    = request.form.get("login_senha", "")
        senha2   = request.form.get("login_senha2", "")
        if not username or not senha:
            flash("Preencha o usuário e a senha para criar o login.", "warning")
            return redirect("/parceiros/novo")
        if len(senha) < 8:
            flash("A senha deve ter ao menos 8 caracteres.", "warning")
            return redirect("/parceiros/novo")
        if senha != senha2:
            flash("As senhas não conferem.", "warning")
            return redirect("/parceiros/novo")
        if db.query(models.Usuario).filter_by(username=username).first():
            flash(f"O usuário '{username}' já existe. Escolha outro nome de login.", "warning")
            return redirect("/parceiros/novo")

    # comissao_percentual: formulário envia em % (ex: 25), armazena como decimal (0.25)
    try:
        comissao_pct = float(request.form.get("comissao_percentual", "0").replace(",", "."))
    except ValueError:
        comissao_pct = 0.0
    comissao_pct = max(0.0, min(comissao_pct, 100.0)) / 100.0

    parceiro = models.Parceiro(
        nome=nome,
        contato=request.form.get("contato") or None,
        telefone=request.form.get("telefone") or None,
        email=request.form.get("email") or None,
        status=request.form.get("status", "ativo"),
        observacoes=request.form.get("observacoes") or None,
        comissao_percentual=comissao_pct,
    )
    db.add(parceiro)
    db.flush()  # obtém parceiro.id antes do commit para vincular o usuário

    if criar_login:
        db.add(models.Usuario(
            nome        = nome,
            username    = username,
            senha_hash  = generate_password_hash(senha),
            role        = "parceiro",
            parceiro_id = parceiro.id,
            ativo       = True,
        ))

    db.commit()
    if criar_login:
        flash(f"Parceiro '{nome}' criado com login '{username}'.", "success")
    else:
        flash(f"Parceiro '{nome}' criado com sucesso.", "success")
    return redirect("/parceiros")


@bp.route("/<int:parceiro_id>")
@admin_required
def detalhe(parceiro_id):
    db = get_db()
    parceiro = (
        db.query(models.Parceiro)
        .options(
            joinedload(models.Parceiro.envios).joinedload(models.Envio.itens).joinedload(models.ItemEnvio.produto),
            joinedload(models.Parceiro.vendas).joinedload(models.Venda.itens),
            joinedload(models.Parceiro.devolucoes).joinedload(models.Devolucao.itens),
        )
        .filter(models.Parceiro.id == parceiro_id).first()
    )
    if not parceiro:
        flash("Parceiro não encontrado.", "warning")
        return redirect("/parceiros")

    # Solicitações de devolução pendentes (iniciadas pelo parceiro via /meu-catalogo)
    solicitacoes_pendentes = (
        db.query(models.SolicitacaoDevolucao)
        .options(joinedload(models.SolicitacaoDevolucao.itens).joinedload(models.ItemSolicitacaoDevolucao.produto))
        .filter(
            models.SolicitacaoDevolucao.parceiro_id == parceiro_id,
            models.SolicitacaoDevolucao.status == "pendente",
        )
        .order_by(models.SolicitacaoDevolucao.criado_em.desc())
        .all()
    )

    produtos = db.query(models.Produto).order_by(models.Produto.nome).all()
    produtos_json = [{"id": p.id, "nome": p.nome, "preco_venda": p.preco_venda, "quantidade": p.quantidade} for p in produtos]

    return render_template("parceiro_detalhe.html",
        active_page="parceiros",
        parceiro=parceiro,
        saldo=_calcular_saldo(parceiro, db),
        historico=_historico(parceiro_id, db),
        produtos=produtos,
        produtos_json=produtos_json,
        solicitacoes_pendentes=solicitacoes_pendentes,
    )


@bp.route("/<int:parceiro_id>/editar", methods=["GET"])
@admin_required
def form_editar(parceiro_id):
    db = get_db()
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        flash("Parceiro não encontrado.", "warning")
        return redirect("/parceiros")
    return render_template("parceiro_form.html", active_page="parceiros", parceiro=parceiro)


@bp.route("/<int:parceiro_id>/editar", methods=["POST"])
@admin_required
def atualizar(parceiro_id):
    db = get_db()
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        flash("Parceiro não encontrado.", "warning")
        return redirect("/parceiros")
    try:
        comissao_pct = float(request.form.get("comissao_percentual", "0").replace(",", "."))
    except ValueError:
        comissao_pct = 0.0
    parceiro.nome = request.form["nome"]
    parceiro.contato = request.form.get("contato") or None
    parceiro.telefone = request.form.get("telefone") or None
    parceiro.email = request.form.get("email") or None
    parceiro.status = request.form.get("status", "ativo")
    parceiro.observacoes = request.form.get("observacoes") or None
    parceiro.comissao_percentual = max(0.0, min(comissao_pct, 100.0)) / 100.0
    db.commit()
    flash(f"Parceiro '{parceiro.nome}' atualizado.", "success")
    return redirect(f"/parceiros/{parceiro_id}")


@bp.route("/<int:parceiro_id>/deletar", methods=["POST"])
@admin_required
def deletar(parceiro_id):
    db = get_db()
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if parceiro:
        nome = parceiro.nome
        db.delete(parceiro)
        db.commit()
        flash(f"Parceiro '{nome}' excluído.", "success")
    return redirect("/parceiros")


# ── Movimentações: envio, venda manual, devolução ────────────────────────────

@bp.route("/<int:parceiro_id>/envio", methods=["POST"])
@admin_required
def envio(parceiro_id):
    """Registra saída do almoxarifado e entrada no estoque do parceiro (consignado)."""
    db = get_db()
    parceiro = db.query(models.Parceiro).options(
        joinedload(models.Parceiro.produtos_catalogo)
    ).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        flash("Parceiro não encontrado.", "warning")
        return redirect("/parceiros")
    itens = _parse_itens()
    if not itens:
        flash("Informe ao menos um produto para o envio.", "warning")
        return redirect(f"/parceiros/{parceiro_id}")

    envio_obj = models.Envio(parceiro_id=parceiro_id, observacoes=request.form.get("observacoes") or None)
    db.add(envio_obj)
    db.flush()

    catalogo_ids = {p.id for p in parceiro.produtos_catalogo}
    for item in itens:
        produto = db.query(models.Produto).filter(models.Produto.id == item["produto_id"]).first()
        if not produto:
            continue
        if produto.quantidade < item["quantidade"]:
            db.rollback()
            flash(f"Estoque insuficiente para '{produto.nome}'.", "warning")
            return redirect(f"/parceiros/{parceiro_id}")
        produto.quantidade -= item["quantidade"]
        db.add(models.MovimentacaoEstoque(
            produto_id=produto.id, tipo="saida", quantidade=item["quantidade"],
            motivo=f"Envio ao parceiro {parceiro.nome}",
        ))
        db.add(models.ItemEnvio(
            envio_id=envio_obj.id, produto_id=item["produto_id"],
            quantidade=item["quantidade"], preco_unitario=item["preco_unitario"],
        ))
        # Adiciona automaticamente ao catálogo do parceiro se ainda não estiver
        if produto.id not in catalogo_ids:
            parceiro.produtos_catalogo.append(produto)
            catalogo_ids.add(produto.id)

    db.commit()
    flash("Envio registrado. Catálogo do parceiro atualizado automaticamente.", "success")
    return redirect(f"/parceiros/{parceiro_id}")


@bp.route("/<int:parceiro_id>/solicitar-devolucao", methods=["POST"])
@admin_required
def solicitar_devolucao_admin(parceiro_id):
    """Rota mantida por compatibilidade — devoluções agora são iniciadas pelo parceiro via /meu-catalogo."""
    return redirect(f"/parceiros/{parceiro_id}")


@bp.route("/<int:parceiro_id>/devolucao/<int:sol_id>/confirmar", methods=["POST"])
@admin_required
def confirmar_devolucao(parceiro_id, sol_id):
    """Confirma solicitação de devolução: cria Devolucao, restaura estoque do almoxarifado."""
    db = get_db()
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    sol = db.query(models.SolicitacaoDevolucao).options(
        joinedload(models.SolicitacaoDevolucao.itens).joinedload(models.ItemSolicitacaoDevolucao.produto)
    ).filter(
        models.SolicitacaoDevolucao.id == sol_id,
        models.SolicitacaoDevolucao.parceiro_id == parceiro_id,
        models.SolicitacaoDevolucao.status == "pendente",
    ).first()

    if not sol or not parceiro:
        flash("Solicitação não encontrada.", "warning")
        return redirect(f"/parceiros/{parceiro_id}")

    dev_obj = models.Devolucao(parceiro_id=parceiro_id, observacoes=sol.motivo)
    db.add(dev_obj)
    db.flush()

    for item in sol.itens:
        produto = item.produto
        if produto:
            produto.quantidade += item.quantidade
            db.add(models.MovimentacaoEstoque(
                produto_id=produto.id, tipo="entrada", quantidade=item.quantidade,
                motivo=f"Devolução confirmada do parceiro {parceiro.nome}",
            ))
        preco = produto.preco_venda if produto else 0.0
        db.add(models.ItemDevolucao(
            devolucao_id=dev_obj.id, produto_id=item.produto_id,
            quantidade=item.quantidade, preco_unitario=preco,
        ))

    sol.status = "confirmada"
    sol.confirmado_em = datetime.now()
    db.commit()
    flash("Devolução confirmada. Estoque restaurado.", "success")
    return redirect(f"/parceiros/{parceiro_id}")


@bp.route("/<int:parceiro_id>/devolucao/<int:sol_id>/rejeitar", methods=["POST"])
@admin_required
def rejeitar_devolucao(parceiro_id, sol_id):
    db = get_db()
    sol = db.query(models.SolicitacaoDevolucao).filter(
        models.SolicitacaoDevolucao.id == sol_id,
        models.SolicitacaoDevolucao.parceiro_id == parceiro_id,
    ).first()
    if sol:
        sol.status = "rejeitada"
        db.commit()
        flash("Solicitação de devolução rejeitada.", "warning")
    return redirect(f"/parceiros/{parceiro_id}")


@bp.route("/<int:parceiro_id>/venda", methods=["POST"])
@admin_required
def venda(parceiro_id):
    """Registra venda manual (legado). Novas vendas usam o fluxo QR → caixa.py."""
    db = get_db()
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        flash("Parceiro não encontrado.", "warning")
        return redirect("/parceiros")
    itens = _parse_itens()
    if not itens:
        flash("Informe ao menos um produto para a venda.", "warning")
        return redirect(f"/parceiros/{parceiro_id}")

    venda_obj = models.Venda(parceiro_id=parceiro_id, observacoes=request.form.get("observacoes") or None)
    db.add(venda_obj)
    db.flush()

    total = 0.0
    for item in itens:
        db.add(models.ItemVenda(venda_id=venda_obj.id, produto_id=item["produto_id"], quantidade=item["quantidade"], preco_unitario=item["preco_unitario"]))
        total += item["quantidade"] * item["preco_unitario"]

    if total > 0:
        db.add(models.MovimentacaoFinanceira(tipo="entrada", categoria="Venda Revendedor", descricao=f"Venda pelo parceiro {parceiro.nome}", valor=total))

    db.commit()
    flash("Venda registrada com sucesso.", "success")
    return redirect(f"/parceiros/{parceiro_id}")


@bp.route("/<int:parceiro_id>/devolucao", methods=["POST"])
@admin_required
def devolucao(parceiro_id):
    """Registra devolução manual (legado) — restaura estoque do almoxarifado."""
    db = get_db()
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        flash("Parceiro não encontrado.", "warning")
        return redirect("/parceiros")
    itens = _parse_itens()
    if not itens:
        flash("Informe ao menos um produto para a devolução.", "warning")
        return redirect(f"/parceiros/{parceiro_id}")

    dev_obj = models.Devolucao(parceiro_id=parceiro_id, observacoes=request.form.get("observacoes") or None)
    db.add(dev_obj)
    db.flush()

    for item in itens:
        produto = db.query(models.Produto).filter(models.Produto.id == item["produto_id"]).first()
        if produto:
            produto.quantidade += item["quantidade"]
            db.add(models.MovimentacaoEstoque(produto_id=produto.id, tipo="entrada", quantidade=item["quantidade"], motivo=f"Devolução do parceiro {parceiro.nome}"))
        db.add(models.ItemDevolucao(devolucao_id=dev_obj.id, produto_id=item["produto_id"], quantidade=item["quantidade"], preco_unitario=item["preco_unitario"]))

    db.commit()
    flash("Devolução registrada com sucesso.", "success")
    return redirect(f"/parceiros/{parceiro_id}")

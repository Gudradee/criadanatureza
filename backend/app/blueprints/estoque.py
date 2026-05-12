import os
import secrets
from collections import defaultdict

from flask import Blueprint, render_template, request, redirect, flash
from sqlalchemy.orm import joinedload

from ..database import get_db
from .. import models
from .auth import admin_required

# ── Configuração de upload de imagens ─────────────────────────────────────────
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
# blueprints/ → app/ → backend/ → uploads/produtos/
PRODUTOS_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "produtos")


def _salvar_imagem(arquivo):
    """Valida extensão, gera nome único e salva o arquivo. Retorna URL pública ou None."""
    if not arquivo or not arquivo.filename:
        return None
    ext = arquivo.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        return None
    nome = f"{secrets.token_hex(12)}.{ext}"
    arquivo.save(os.path.join(PRODUTOS_UPLOAD_DIR, nome))
    return f"/uploads/produtos/{nome}"

bp = Blueprint("estoque", __name__, url_prefix="/estoque")


def _categorias(db):
    return db.query(models.Categoria).order_by(models.Categoria.nome).all()


def _estoque_parceiro(parceiro, db):
    """
    Retorna lista de {nome, produto_id, quantidade} representando
    o estoque atual (em mãos) do parceiro.
    """
    enviado   = defaultdict(int)
    vendido   = defaultdict(int)
    devolvido = defaultdict(int)

    for envio in parceiro.envios:
        for item in envio.itens:
            enviado[item.produto_id] += item.quantidade

    for vf in (
        db.query(models.VendaFinal)
        .filter(models.VendaFinal.parceiro_id == parceiro.id)
        .options(joinedload(models.VendaFinal.itens))
        .all()
    ):
        for item in vf.itens:
            vendido[item.produto_id] += item.quantidade

    for dev in parceiro.devolucoes:
        for item in dev.itens:
            devolvido[item.produto_id] += item.quantidade

    produto_map = {p.id: p.nome for p in db.query(models.Produto).all()}
    resultado = []
    for pid, qtd_env in enviado.items():
        em_maos = max(qtd_env - vendido[pid] - devolvido[pid], 0)
        resultado.append({
            "produto_id": pid,
            "nome": produto_map.get(pid, f"Produto #{pid}"),
            "quantidade": em_maos,
        })
    resultado.sort(key=lambda x: x["nome"])
    return resultado


# ── Listagem e busca de produtos ──────────────────────────────────────────────

@bp.route("")
@admin_required
def listar():
    db = get_db()
    busca = request.args.get("busca")
    categoria_id = request.args.get("categoria_id", type=int)

    query = db.query(models.Produto)
    if busca:
        query = query.filter(models.Produto.nome.ilike(f"%{busca}%"))
    if categoria_id:
        query = query.filter(models.Produto.categoria_id == categoria_id)
    produtos = query.order_by(models.Produto.nome).all()

    # Todos os produtos com estoque (para popup)
    todos_produtos = db.query(models.Produto).order_by(models.Produto.nome).all()

    # Parceiros ativos com estoque em mãos
    parceiros = (
        db.query(models.Parceiro)
        .options(
            joinedload(models.Parceiro.envios).joinedload(models.Envio.itens),
            joinedload(models.Parceiro.devolucoes).joinedload(models.Devolucao.itens),
        )
        .filter(models.Parceiro.status == "ativo")
        .order_by(models.Parceiro.nome)
        .all()
    )
    parceiros_estoque = [
        {"parceiro": p, "itens": _estoque_parceiro(p, db)}
        for p in parceiros
    ]

    total_itens_admin = sum(p.quantidade for p in todos_produtos)
    total_itens_parceiros = sum(
        sum(item["quantidade"] for item in pe["itens"])
        for pe in parceiros_estoque
    )

    return render_template("estoque.html",
        active_page="estoque",
        produtos=produtos,
        categorias=_categorias(db),
        busca=busca,
        categoria_id=categoria_id,
        todos_produtos=todos_produtos,
        parceiros_estoque=parceiros_estoque,
        total_itens_admin=total_itens_admin,
        total_itens_parceiros=total_itens_parceiros,
    )


# ── Criação de produto ────────────────────────────────────────────────────────

@bp.route("/novo", methods=["GET"])
@admin_required
def form_novo():
    db = get_db()
    return render_template("estoque_form.html",
        active_page="estoque",
        produto=None,
        categorias=_categorias(db),
    )


@bp.route("/novo", methods=["POST"])
@admin_required
def criar():
    db = get_db()
    nome = request.form["nome"]
    cat_id = request.form.get("categoria_id") or None
    if cat_id:
        cat_id = int(cat_id)

    imagem_url = _salvar_imagem(request.files.get("imagem"))

    produto = models.Produto(
        nome=nome,
        categoria_id=cat_id,
        descricao=request.form.get("descricao") or None,
        quantidade=int(request.form.get("quantidade", 0)),
        estoque_minimo=int(request.form.get("estoque_minimo", 5)),
        preco_custo=float(request.form.get("preco_custo", 0)),
        preco_venda=float(request.form.get("preco_venda", 0)),
        imagem_url=imagem_url,
    )
    db.add(produto)
    db.commit()
    db.refresh(produto)

    # Se o produto já foi criado com estoque inicial, registra movimentação e custo
    if produto.quantidade > 0:
        db.add(models.MovimentacaoEstoque(
            produto_id=produto.id, tipo="entrada",
            quantidade=produto.quantidade, motivo="Estoque inicial"
        ))
        if produto.preco_custo > 0:
            db.add(models.MovimentacaoFinanceira(
                tipo="saida",
                categoria="Custo de Produção",
                descricao=f"Produção: {produto.nome} × {produto.quantidade} un.",
                valor=round(produto.preco_custo * produto.quantidade, 2),
            ))
        db.commit()

    flash(f"Produto '{nome}' criado com sucesso.", "success")
    return redirect("/estoque")


# ── Edição de produto ─────────────────────────────────────────────────────────

@bp.route("/<int:produto_id>/editar", methods=["GET"])
@admin_required
def form_editar(produto_id):
    db = get_db()
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        flash("Produto não encontrado.", "warning")
        return redirect("/estoque")
    return render_template("estoque_form.html",
        active_page="estoque",
        produto=produto,
        categorias=_categorias(db),
    )


@bp.route("/<int:produto_id>/editar", methods=["POST"])
@admin_required
def atualizar(produto_id):
    db = get_db()
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        flash("Produto não encontrado.", "warning")
        return redirect("/estoque")

    produto.nome = request.form["nome"]
    produto.categoria_id = int(request.form["categoria_id"]) if request.form.get("categoria_id") else None
    produto.descricao = request.form.get("descricao") or None
    produto.quantidade = int(request.form.get("quantidade", 0))
    produto.estoque_minimo = int(request.form.get("estoque_minimo", 5))
    produto.preco_custo = float(request.form.get("preco_custo", 0))
    produto.preco_venda = float(request.form.get("preco_venda", 0))

    nova_imagem = _salvar_imagem(request.files.get("imagem"))
    if nova_imagem:
        produto.imagem_url = nova_imagem

    db.commit()

    flash(f"Produto '{produto.nome}' atualizado.", "success")
    return redirect("/estoque")


# ── Exclusão de produto ───────────────────────────────────────────────────────

@bp.route("/<int:produto_id>/deletar", methods=["POST"])
@admin_required
def deletar(produto_id):
    db = get_db()
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if produto:
        nome = produto.nome
        db.delete(produto)
        db.commit()
        flash(f"Produto '{nome}' excluído.", "success")
    return redirect("/estoque")


# ── Ajuste manual de estoque ──────────────────────────────────────────────────

@bp.route("/<int:produto_id>/ajuste", methods=["GET"])
@admin_required
def form_ajuste(produto_id):
    db = get_db()
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        flash("Produto não encontrado.", "warning")
        return redirect("/estoque")
    return render_template("estoque_ajuste.html",
        active_page="estoque",
        produto=produto,
    )


@bp.route("/<int:produto_id>/ajuste", methods=["POST"])
@admin_required
def ajustar(produto_id):
    db = get_db()
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        flash("Produto não encontrado.", "warning")
        return redirect("/estoque")

    tipo = request.form["tipo"]
    quantidade = int(request.form["quantidade"])
    motivo = request.form.get("motivo") or None

    # entrada: soma ao estoque e registra custo de produção se houver preco_custo
    if tipo == "entrada":
        produto.quantidade += quantidade
        if produto.preco_custo > 0:
            db.add(models.MovimentacaoFinanceira(
                tipo="saida",
                categoria="Custo de Produção",
                descricao=f"Produção: {produto.nome} × {quantidade} un.",
                valor=round(produto.preco_custo * quantidade, 2),
            ))
    # saida: subtrai do estoque (com verificação de saldo)
    elif tipo == "saida":
        if produto.quantidade < quantidade:
            flash("Estoque insuficiente para esta saída.", "warning")
            return redirect(f"/estoque/{produto_id}/ajuste")
        produto.quantidade -= quantidade
    # ajuste: sobrescreve o valor absoluto do estoque
    elif tipo == "ajuste":
        produto.quantidade = quantidade

    db.add(models.MovimentacaoEstoque(produto_id=produto.id, tipo=tipo, quantidade=quantidade, motivo=motivo))
    db.commit()

    flash(f"Estoque de '{produto.nome}' ajustado com sucesso.", "success")
    return redirect("/estoque")

# Responsabilidade: CRUD completo de produtos e ajustes de estoque.
# Toda entrada de estoque registra automaticamente uma MovimentacaoEstoque
# e, se o produto tiver preco_custo, uma MovimentacaoFinanceira de "Custo de Produção".
# Upload de imagens salvo em backend/uploads/produtos/ e servido via /uploads/.

import os
import secrets

from flask import Blueprint, render_template, request, redirect, flash

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

    return render_template("estoque.html",
        active_page="estoque",
        produtos=produtos,
        categorias=_categorias(db),
        busca=busca,
        categoria_id=categoria_id,
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

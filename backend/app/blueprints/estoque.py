import os
import secrets
from collections import defaultdict
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, flash, jsonify
from sqlalchemy.orm import joinedload

from ..database import get_db
from .. import models
from .auth import admin_required
from .historico import criar_parcela_default

ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif"}

_DEFAULT_UPLOADS = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
PRODUTOS_UPLOAD_DIR = os.path.join(
    os.environ.get("UPLOADS_DIR", _DEFAULT_UPLOADS),
    "produtos",
)
os.makedirs(PRODUTOS_UPLOAD_DIR, exist_ok=True)

def _salvar_imagem(arquivo):

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

@bp.route("")
@admin_required
def listar():
    db = get_db()
    busca = request.args.get("busca")
    categoria_id = request.args.get("categoria_id", type=int)
    produto_id   = request.args.get("produto_id",   type=int)
    incluir_arquivados = request.args.get("arquivados") == "1"

    query = db.query(models.Produto)
    if not incluir_arquivados:
        query = query.filter(models.Produto.ativo.is_(True))
    if busca:
        query = query.filter(models.Produto.nome.ilike(f"%{busca}%"))
    if categoria_id:
        query = query.filter(models.Produto.categoria_id == categoria_id)
    if produto_id:
        query = query.filter(models.Produto.id == produto_id)
    produtos = query.order_by(models.Produto.ativo.desc(), models.Produto.nome).all()

    todos_produtos = (
        db.query(models.Produto)
        .filter(models.Produto.ativo.is_(True))
        .order_by(models.Produto.nome)
        .all()
    )

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

    historico = (
        db.query(models.MovimentacaoEstoque)
        .options(joinedload(models.MovimentacaoEstoque.produto))
        .order_by(models.MovimentacaoEstoque.criado_em.desc())
        .limit(60)
        .all()
    )

    return render_template("estoque.html",
        active_page="estoque",
        produtos=produtos,
        categorias=_categorias(db),
        busca=busca,
        categoria_id=categoria_id,
        produto_id=produto_id,
        todos_produtos=todos_produtos,
        parceiros_estoque=parceiros_estoque,
        total_itens_admin=total_itens_admin,
        total_itens_parceiros=total_itens_parceiros,
        historico=historico,
        incluir_arquivados=incluir_arquivados,
    )

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

    if produto.quantidade > 0:
        db.add(models.MovimentacaoEstoque(
            produto_id=produto.id, tipo="entrada",
            quantidade=produto.quantidade, motivo="Estoque inicial",
            preco_custo_unitario=produto.preco_custo,
            preco_venda_unitario=produto.preco_venda,
        ))
        if produto.preco_custo > 0:
            hoje = datetime.now()
            desp = models.Despesa(
                descricao        = f"Produção: {produto.nome} × {produto.quantidade} un.",
                valor            = round(produto.preco_custo * produto.quantidade, 2),
                tipo             = "variavel",
                categoria        = "Custo de Produção",
                data_competencia = datetime(hoje.year, hoje.month, 1),
            )
            db.add(desp)
            db.flush()
            criar_parcela_default(db, desp)
        db.commit()

    flash(f"Produto '{nome}' criado com sucesso.", "success")
    return redirect("/estoque")

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

    nova_qtd     = int(request.form.get("quantidade", 0))
    qtd_anterior = produto.quantidade
    diff         = nova_qtd - qtd_anterior

    custo_anterior = produto.preco_custo
    venda_anterior = produto.preco_venda

    novo_custo = float(request.form.get("preco_custo", 0))
    novo_venda = float(request.form.get("preco_venda", 0))

    produto.nome           = request.form["nome"]
    produto.categoria_id   = int(request.form["categoria_id"]) if request.form.get("categoria_id") else None
    produto.descricao      = request.form.get("descricao") or None
    produto.quantidade     = nova_qtd
    produto.estoque_minimo = int(request.form.get("estoque_minimo", 5))
    produto.preco_custo    = novo_custo
    produto.preco_venda    = novo_venda

    nova_imagem = _salvar_imagem(request.files.get("imagem"))
    if nova_imagem:
        produto.imagem_url = nova_imagem

    notas_mudanca = []
    if abs(novo_custo - custo_anterior) > 0.001:
        notas_mudanca.append(
            f"Custo de produção: R${custo_anterior:.2f} → R${novo_custo:.2f}"
        )
    if abs(novo_venda - venda_anterior) > 0.001:
        notas_mudanca.append(
            f"Preço de venda: R${venda_anterior:.2f} → R${novo_venda:.2f}"
        )

    if diff != 0:
        tipo_mov = "entrada" if diff > 0 else "saida"
        partes = []
        if diff > 0:
            partes.append(f"Reposição via edição (+{diff} un.)")
        else:
            partes.append(f"Saída via edição ({diff} un.)")

        if notas_mudanca and diff > 0:
            partes.append(" · ".join(notas_mudanca))
        motivo = " — ".join(partes)

        db.add(models.MovimentacaoEstoque(
            produto_id           = produto.id,
            tipo                 = tipo_mov,
            quantidade           = abs(diff),
            motivo               = motivo,
            preco_custo_unitario = novo_custo if diff > 0 else None,
            preco_venda_unitario = novo_venda if diff > 0 else None,
        ))

        if diff > 0 and novo_custo > 0:
            hoje = datetime.now()
            desp = models.Despesa(
                descricao        = f"Produção: {produto.nome} × {diff} un. (reposição)",
                valor            = round(novo_custo * diff, 2),
                tipo             = "variavel",
                categoria        = "Custo de Produção",
                data_competencia = datetime(hoje.year, hoje.month, 1),
            )
            db.add(desp)
            db.flush()
            criar_parcela_default(db, desp)
    elif notas_mudanca:

        db.add(models.MovimentacaoEstoque(
            produto_id           = produto.id,
            tipo                 = "ajuste",
            quantidade           = 0,
            motivo               = "Atualização de preço — " + " · ".join(notas_mudanca),
            preco_custo_unitario = novo_custo,
            preco_venda_unitario = novo_venda,
        ))

    db.commit()

    flash(f"Produto '{produto.nome}' atualizado.", "success")
    return redirect("/estoque")

def _dependencias_produto(db, produto_id):

    return {
        "movimentacoes":   db.query(models.MovimentacaoEstoque).filter_by(produto_id=produto_id).count(),
        "itens_envio":     db.query(models.ItemEnvio).filter_by(produto_id=produto_id).count(),
        "itens_venda":     db.query(models.ItemVenda).filter_by(produto_id=produto_id).count(),
        "itens_devolucao": db.query(models.ItemDevolucao).filter_by(produto_id=produto_id).count(),
        "itens_pre_venda": db.query(models.ItemPreVenda).filter_by(produto_id=produto_id).count(),
        "itens_venda_final": db.query(models.ItemVendaFinal).filter_by(produto_id=produto_id).count(),
    }

@bp.route("/<int:produto_id>/deletar", methods=["POST"])
@admin_required
def deletar(produto_id):

    db = get_db()
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        flash("Produto não encontrado.", "warning")
        return redirect("/estoque")

    dep = _dependencias_produto(db, produto_id)
    total = sum(dep.values())
    if total > 0:
        partes = []
        if dep["movimentacoes"]:     partes.append(f"{dep['movimentacoes']} movimentação(ões) de estoque")
        if dep["itens_venda_final"]: partes.append(f"{dep['itens_venda_final']} item(ns) em vendas pelo caixa")
        if dep["itens_envio"]:       partes.append(f"{dep['itens_envio']} item(ns) em envios a parceiros")
        if dep["itens_devolucao"]:   partes.append(f"{dep['itens_devolucao']} item(ns) em devoluções")
        if dep["itens_pre_venda"]:   partes.append(f"{dep['itens_pre_venda']} item(ns) em pré-vendas (QR)")
        if dep["itens_venda"]:       partes.append(f"{dep['itens_venda']} item(ns) em vendas manuais (legado)")
        flash(
            f"Produto '{produto.nome}' tem histórico no sistema "
            f"({' · '.join(partes)}) e não pode ser excluído sem perder esses "
            "dados. Use 'Arquivar' para ocultá-lo das listas sem apagar o histórico.",
            "warning"
        )
        return redirect("/estoque")

    produto.parceiros_catalogo.clear()
    nome = produto.nome
    db.delete(produto)
    db.commit()
    flash(f"Produto '{nome}' excluído.", "success")
    return redirect("/estoque")

@bp.route("/<int:produto_id>/arquivar", methods=["POST"])
@admin_required
def arquivar(produto_id):

    db = get_db()
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        flash("Produto não encontrado.", "warning")
        return redirect(request.referrer or "/estoque")
    produto.ativo = not produto.ativo
    db.commit()
    if produto.ativo:
        flash(f"Produto '{produto.nome}' reativado.", "success")
    else:
        flash(f"Produto '{produto.nome}' arquivado. Histórico preservado.", "success")
    return redirect(request.referrer or "/estoque")

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

    custo_anterior = produto.preco_custo
    venda_anterior = produto.preco_venda
    novo_custo = request.form.get("preco_custo")
    novo_venda = request.form.get("preco_venda")
    novo_custo = float(novo_custo) if novo_custo not in (None, "") else custo_anterior
    novo_venda = float(novo_venda) if novo_venda not in (None, "") else venda_anterior

    notas_mudanca = []
    if abs(novo_custo - custo_anterior) > 0.001:
        notas_mudanca.append(f"Custo de produção: R${custo_anterior:.2f} → R${novo_custo:.2f}")
    if abs(novo_venda - venda_anterior) > 0.001:
        notas_mudanca.append(f"Preço de venda: R${venda_anterior:.2f} → R${novo_venda:.2f}")

    if tipo == "entrada":
        if novo_custo != custo_anterior:
            produto.preco_custo = novo_custo
        if novo_venda != venda_anterior:
            produto.preco_venda = novo_venda

        produto.quantidade += quantidade
        if produto.preco_custo > 0:
            hoje = datetime.now()
            desp = models.Despesa(
                descricao        = f"Produção: {produto.nome} × {quantidade} un.",
                valor            = round(produto.preco_custo * quantidade, 2),
                tipo             = "variavel",
                categoria        = "Custo de Produção",
                data_competencia = datetime(hoje.year, hoje.month, 1),
            )
            db.add(desp)
            db.flush()
            criar_parcela_default(db, desp)
    elif tipo == "saida":
        if produto.quantidade < quantidade:
            flash("Estoque insuficiente para esta saída.", "warning")
            return redirect(f"/estoque/{produto_id}/ajuste")
        produto.quantidade -= quantidade
    elif tipo == "ajuste":
        produto.quantidade = quantidade

    motivo_partes = []
    if motivo:
        motivo_partes.append(motivo)
    if tipo == "entrada" and notas_mudanca:
        motivo_partes.append(" · ".join(notas_mudanca))
    motivo_final = " — ".join(motivo_partes) if motivo_partes else None

    db.add(models.MovimentacaoEstoque(
        produto_id           = produto.id,
        tipo                 = tipo,
        quantidade           = quantidade,
        motivo               = motivo_final,
        preco_custo_unitario = (produto.preco_custo if tipo == "entrada" else None),
        preco_venda_unitario = (produto.preco_venda if tipo == "entrada" else None),
    ))
    db.commit()

    flash(f"Estoque de '{produto.nome}' ajustado com sucesso.", "success")
    return redirect("/estoque")

@bp.route("/<int:produto_id>/historico.json")
@admin_required
def historico_json(produto_id):

    db = get_db()
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        return jsonify({"erro": "Produto não encontrado"}), 404

    movs = (
        db.query(models.MovimentacaoEstoque)
        .filter(models.MovimentacaoEstoque.produto_id == produto_id)
        .order_by(models.MovimentacaoEstoque.criado_em.desc())
        .all()
    )

    entradas = [m for m in movs if m.tipo == "entrada"]
    total_qtd_entrada = sum(m.quantidade for m in entradas)
    total_custo_entrada = sum(
        ((m.preco_custo_unitario if m.preco_custo_unitario is not None else produto.preco_custo) or 0)
        * m.quantidade
        for m in entradas
    )
    custo_medio = (total_custo_entrada / total_qtd_entrada) if total_qtd_entrada > 0 else (produto.preco_custo or 0.0)

    lotes_resumo = []
    for m in sorted(entradas, key=lambda x: x.criado_em or datetime.min):
        custo_un = m.preco_custo_unitario if m.preco_custo_unitario is not None else produto.preco_custo
        venda_un = m.preco_venda_unitario if m.preco_venda_unitario is not None else produto.preco_venda
        lotes_resumo.append({
            "data":                 m.criado_em.isoformat() if m.criado_em else None,
            "quantidade":           m.quantidade,
            "preco_custo_unitario": round(custo_un or 0, 2),
            "preco_venda_unitario": round(venda_un or 0, 2),
            "custo_lote":           round((custo_un or 0) * m.quantidade, 2),
            "lucro_unit_epoca":     round((venda_un or 0) - (custo_un or 0), 2),
        })

    return jsonify({
        "produto": {
            "id":             produto.id,
            "nome":           produto.nome,
            "quantidade":     produto.quantidade,
            "preco_custo":    produto.preco_custo,
            "preco_venda":    produto.preco_venda,
            "estoque_minimo": produto.estoque_minimo,
        },
        "movimentacoes": [
            {
                "id":                   m.id,
                "tipo":                 m.tipo,
                "quantidade":           m.quantidade,
                "motivo":               m.motivo,
                "data":                 m.criado_em.isoformat() if m.criado_em else None,
                "preco_custo_unitario": m.preco_custo_unitario,
                "preco_venda_unitario": m.preco_venda_unitario,
            }
            for m in movs
        ],
        "lotes": lotes_resumo,
        "resumo": {
            "total_quantidade_entrada": total_qtd_entrada,
            "total_custo_entrada":      round(total_custo_entrada, 2),
            "custo_medio_ponderado":    round(custo_medio, 2),
            "lucro_un_atual":           round((produto.preco_venda or 0) - custo_medio, 2),
        },
    })


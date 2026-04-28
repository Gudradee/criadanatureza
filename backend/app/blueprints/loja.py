import secrets
import io
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, session, flash, abort, send_file
from sqlalchemy.orm import joinedload

from ..database import get_db
from .. import models

bp = Blueprint("loja", __name__, url_prefix="/loja")

# Pedido expira em 30 minutos — cliente precisa gerar novo QR se ultrapassar
EXPIRACAO_MINUTOS = 30


# ── Cálculo de estoque do parceiro (modelo consignado) ───────────────────────

def _parceiro_em_maos(parceiro_id, db):
    """Retorna {produto_id: quantidade_em_maos} para o parceiro.
    em_maos = enviado − vendido (via VendaFinal) − devolvido (confirmado pelo admin)."""
    enviado   = defaultdict(int)
    vendido   = defaultdict(int)
    devolvido = defaultdict(int)

    for envio in db.query(models.Envio).filter_by(parceiro_id=parceiro_id).all():
        for item in db.query(models.ItemEnvio).filter_by(envio_id=envio.id).all():
            enviado[item.produto_id] += item.quantidade

    # Vendas via QR (VendaFinal) vinculadas a este parceiro
    for vf in (
        db.query(models.VendaFinal)
        .join(models.PreVenda, models.VendaFinal.pre_venda_id == models.PreVenda.id)
        .filter(models.PreVenda.parceiro_id == parceiro_id)
        .options(joinedload(models.VendaFinal.itens))
        .all()
    ):
        for item in vf.itens:
            vendido[item.produto_id] += item.quantidade

    # Devoluções confirmadas (Devolucao = já aceita pelo admin)
    for dev in db.query(models.Devolucao).filter_by(parceiro_id=parceiro_id).all():
        for item in db.query(models.ItemDevolucao).filter_by(devolucao_id=dev.id).all():
            devolvido[item.produto_id] += item.quantidade

    return {
        pid: max(enviado[pid] - vendido[pid] - devolvido[pid], 0)
        for pid in enviado
    }


# ── Catálogo público ──────────────────────────────────────────────────────────

@bp.route("")
def catalogo():
    db = get_db()

    # ?p=<parceiro_id> identifica qual catálogo exibir; salvo na sessão do cliente
    parceiro_id_param = request.args.get("p", type=int)
    if parceiro_id_param:
        session["loja_parceiro_id"] = parceiro_id_param
    parceiro_id = session.get("loja_parceiro_id")

    parceiro    = None
    em_maos_map = {}

    if parceiro_id:
        parceiro = db.query(models.Parceiro).filter_by(
            id=parceiro_id, status="ativo"
        ).first()

    if parceiro:
        # Catálogo do parceiro: mostra apenas produtos que ele tem em mãos (> 0)
        em_maos_map = _parceiro_em_maos(parceiro.id, db)
        ids_disponiveis = [pid for pid, qty in em_maos_map.items() if qty > 0]
        produtos = (
            db.query(models.Produto)
            .filter(models.Produto.id.in_(ids_disponiveis))
            .order_by(models.Produto.nome)
            .all()
        ) if ids_disponiveis else []
    else:
        # Catálogo geral: produtos com estoque no almoxarifado do admin
        produtos = (
            db.query(models.Produto)
            .filter(models.Produto.quantidade > 0)
            .order_by(models.Produto.nome)
            .all()
        )

    carrinho    = session.get("carrinho", {})
    total_itens = sum(carrinho.values())
    return render_template("loja/catalogo.html",
        produtos    = produtos,
        carrinho    = carrinho,
        total_itens = total_itens,
        parceiro    = parceiro,
        em_maos_map = em_maos_map,
    )


# ── Carrinho (sessão do cliente) ──────────────────────────────────────────────

@bp.route("/carrinho/adicionar", methods=["POST"])
def adicionar():
    produto_id = request.form.get("produto_id", "")
    try:
        quantidade = max(1, int(request.form.get("quantidade", 1)))
    except ValueError:
        quantidade = 1

    if not produto_id:
        return redirect("/loja")

    db      = get_db()
    produto = db.query(models.Produto).get(int(produto_id))
    if not produto:
        flash("Produto indisponível.", "warning")
        return redirect("/loja")

    # Limite de quantidade: usa estoque do parceiro ou do almoxarifado conforme o contexto
    parceiro_id = session.get("loja_parceiro_id")
    if parceiro_id:
        em_maos = _parceiro_em_maos(parceiro_id, db)
        estoque_disponivel = em_maos.get(produto.id, 0)
    else:
        estoque_disponivel = produto.quantidade

    if estoque_disponivel <= 0:
        flash("Produto indisponível.", "warning")
        return redirect("/loja")

    carrinho = session.get("carrinho", {})
    atual    = carrinho.get(produto_id, 0) + quantidade

    if atual > estoque_disponivel:
        atual = estoque_disponivel
        flash(f"Quantidade máxima disponível: {estoque_disponivel}.", "warning")

    carrinho[produto_id] = atual
    session["carrinho"]  = carrinho
    return redirect("/loja")


@bp.route("/carrinho/atualizar", methods=["POST"])
def atualizar():
    produto_id = request.form.get("produto_id", "")
    try:
        quantidade = int(request.form.get("quantidade", 0))
    except ValueError:
        quantidade = 0

    carrinho = session.get("carrinho", {})
    if quantidade <= 0:
        carrinho.pop(produto_id, None)
    else:
        carrinho[produto_id] = quantidade
    session["carrinho"] = carrinho
    return redirect("/loja/carrinho")


@bp.route("/carrinho/remover", methods=["POST"])
def remover():
    produto_id = request.form.get("produto_id", "")
    carrinho   = session.get("carrinho", {})
    carrinho.pop(produto_id, None)
    session["carrinho"] = carrinho
    return redirect("/loja/carrinho")


@bp.route("/carrinho")
def ver_carrinho():
    db       = get_db()
    carrinho = session.get("carrinho", {})
    itens    = []
    total    = 0.0

    for pid, qtd in list(carrinho.items()):
        produto = db.query(models.Produto).get(int(pid))
        if not produto:
            continue
        qtd_real = min(qtd, produto.quantidade)
        sub      = produto.preco_venda * qtd_real
        total   += sub
        itens.append({"produto": produto, "quantidade": qtd_real, "subtotal": sub})

    return render_template("loja/carrinho.html", itens=itens, total=total)


# ── Finalização: gera PreVenda e redireciona para o QR Code ──────────────────

@bp.route("/finalizar", methods=["POST"])
def finalizar():
    """Converte o carrinho em uma PreVenda com token único e expiração de 30 min."""
    db       = get_db()
    carrinho = session.get("carrinho", {})

    if not carrinho:
        flash("Seu carrinho está vazio.", "warning")
        return redirect("/loja")

    itens_validos = []
    for pid, qtd in carrinho.items():
        produto = db.query(models.Produto).get(int(pid))
        if not produto or produto.quantidade <= 0:
            continue
        qtd_real = min(qtd, produto.quantidade)
        itens_validos.append((produto, qtd_real))

    if not itens_validos:
        flash("Nenhum produto disponível no carrinho.", "warning")
        return redirect("/loja")

    token       = secrets.token_urlsafe(32)
    parceiro_id = session.get("loja_parceiro_id")

    pre_venda = models.PreVenda(
        token       = token,
        status      = models.StatusPreVenda.aguardando,
        expira_em   = datetime.now() + timedelta(minutes=EXPIRACAO_MINUTOS),
        parceiro_id = parceiro_id,
    )
    db.add(pre_venda)
    db.flush()

    for produto, qtd in itens_validos:
        db.add(models.ItemPreVenda(
            pre_venda_id = pre_venda.id,
            produto_id   = produto.id,
            quantidade   = qtd,
            preco_ref    = produto.preco_venda,
        ))

    db.commit()
    session.pop("carrinho", None)
    return redirect(f"/loja/pedido/{token}")


# ── Página do pedido: cliente visualiza o QR Code ────────────────────────────

@bp.route("/pedido/<token>")
def pedido(token):
    db        = get_db()
    pre_venda = db.query(models.PreVenda).filter_by(token=token).first()
    if not pre_venda:
        abort(404)

    expirado = pre_venda.expira_em and datetime.now() > pre_venda.expira_em
    return render_template("loja/qrcode.html", pre_venda=pre_venda, expirado=expirado)


# ── Imagem do QR Code (PNG inline) ───────────────────────────────────────────

@bp.route("/pedido/<token>/qr.png")
def qr_image(token):
    """Gera dinamicamente a imagem PNG do QR Code que aponta para /caixa/pedido/<token>."""
    try:
        import qrcode
    except ImportError:
        abort(500, "Biblioteca qrcode não instalada. Execute: pip install qrcode[pil]")

    db        = get_db()
    pre_venda = db.query(models.PreVenda).filter_by(token=token).first()
    if not pre_venda:
        abort(404)

    url_caixa = f"{request.host_url}caixa/pedido/{token}"
    img       = qrcode.make(url_caixa)
    buf       = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# Responsabilidade: vitrine pública e fluxo de compra do cliente.
# Fluxo: cliente acessa /loja?p=<id> → monta carrinho → /loja/finalizar → PreVenda criada
# → exibe QR Code → operador lê no caixa → /caixa/pedido/<token> confirma e finaliza.
# Sem autenticação — qualquer cliente com o link pode acessar.

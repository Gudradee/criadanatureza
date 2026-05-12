from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, abort, render_template, request, redirect, flash
from sqlalchemy.orm import joinedload

from .. import models
from ..database import get_db
from .auth import get_usuario_atual, login_required

bp = Blueprint("parceiro_area", __name__)


def _require_parceiro():
    usuario = get_usuario_atual()
    if not usuario or usuario.role == "admin" or not usuario.parceiro_id:
        abort(403)
    return usuario


def _load_parceiro(parceiro_id):
    db = get_db()
    return (
        db.query(models.Parceiro)
        .options(
            joinedload(models.Parceiro.envios).joinedload(models.Envio.itens).joinedload(models.ItemEnvio.produto),
            joinedload(models.Parceiro.devolucoes).joinedload(models.Devolucao.itens).joinedload(models.ItemDevolucao.produto),
        )
        .filter(models.Parceiro.id == parceiro_id)
        .first()
    )


def _venda_date(dt):
    if dt is None:
        return datetime.now().date()
    if dt.tzinfo:
        return dt.astimezone().date()
    return dt.date()


def _naive(dt):
    if dt is None:
        return None
    if dt.tzinfo:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def _parse_periodo():
    periodo      = request.args.get("periodo", "hoje")
    hoje         = datetime.now()
    data_ini_str = request.args.get("data_ini", "")
    data_fim_str = request.args.get("data_fim", "")

    if periodo == "hoje":
        inicio = hoje.replace(hour=0, minute=0, second=0, microsecond=0)
        fim    = hoje
    elif periodo == "semana":
        inicio = (hoje - timedelta(days=hoje.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        fim    = hoje
    elif periodo == "personalizado":
        try:
            inicio = datetime.strptime(data_ini_str, "%Y-%m-%d")
            fim    = datetime.strptime(data_fim_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except (TypeError, ValueError):
            inicio = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            fim    = hoje
    else:
        periodo = "mes"
        inicio  = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fim     = hoje

    return periodo, inicio, fim, data_ini_str, data_fim_str


def _build_estoque_map(parceiro, db):
    """
    Retorna {produto_id: em_maos}.
    em_maos = enviado − vendido (VendaFinal.parceiro_id) − devolvido confirmado.
    """
    enviado   = defaultdict(int)
    vendido   = defaultdict(int)
    devolvido = defaultdict(int)

    for envio in parceiro.envios:
        for item in envio.itens:
            enviado[item.produto_id] += item.quantidade

    # Todas as VendaFinal atribuídas a este parceiro (QR legado ou manual novo)
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

    return {pid: max(enviado[pid] - vendido[pid] - devolvido[pid], 0) for pid in enviado}


# ── Dashboard ─────────────────────────────────────────────────────────────────

@bp.route("/meu-painel")
@login_required
def meu_painel():
    usuario = _require_parceiro()
    parceiro = _load_parceiro(usuario.parceiro_id)
    if not parceiro:
        abort(403)

    db = get_db()
    periodo, inicio, fim, data_ini_str, data_fim_str = _parse_periodo()

    estoque_map   = _build_estoque_map(parceiro, db)
    em_maos       = sum(estoque_map.values())
    total_enviado = sum(item.quantidade for e in parceiro.envios for item in e.itens)

    # Todas as vendas finais do parceiro
    todas_vf = (
        db.query(models.VendaFinal)
        .filter(models.VendaFinal.parceiro_id == parceiro.id)
        .options(joinedload(models.VendaFinal.itens))
        .all()
    )

    inicio_date    = inicio.date()
    fim_date       = fim.date()
    vendas_periodo = [
        vf for vf in todas_vf
        if inicio_date <= _venda_date(vf.data_venda) <= fim_date
    ]

    devolucoes_periodo = [
        d for d in parceiro.devolucoes
        if _naive(d.criado_em) and inicio <= _naive(d.criado_em) <= fim
    ]

    qtd_vendida       = sum(i.quantidade for vf in vendas_periodo for i in vf.itens)
    valor_vendido     = sum(vf.valor_total_liquido for vf in vendas_periodo)
    qtd_devolvida     = sum(i.quantidade for d in devolucoes_periodo for i in d.itens)
    qtd_vendida_total = sum(i.quantidade for vf in todas_vf for i in vf.itens)

    produtos_map = defaultdict(lambda: {"quantidade": 0, "valor": 0.0})
    for vf in vendas_periodo:
        for item in vf.itens:
            nome = item.nome_produto or "—"
            produtos_map[nome]["quantidade"] += item.quantidade
            produtos_map[nome]["valor"]      += item.subtotal_liquido

    produtos_lista = sorted(produtos_map.items(), key=lambda x: x[1]["quantidade"], reverse=True)

    return render_template("parceiro_painel.html",
        active_page       = "meu_painel",
        parceiro          = parceiro,
        periodo           = periodo,
        data_ini          = data_ini_str,
        data_fim          = data_fim_str,
        em_maos           = em_maos,
        total_enviado     = total_enviado,
        qtd_vendida       = qtd_vendida,
        qtd_vendida_total = qtd_vendida_total,
        valor_vendido     = round(valor_vendido, 2),
        qtd_devolvida     = qtd_devolvida,
        produtos_lista    = produtos_lista,
    )


# ── Catálogo (estoque em mãos + solicitação de devolução) ────────────────────

@bp.route("/meu-catalogo")
@login_required
def meu_catalogo():
    usuario = _require_parceiro()
    parceiro = _load_parceiro(usuario.parceiro_id)
    if not parceiro:
        abort(403)

    db          = get_db()
    estoque_map = _build_estoque_map(parceiro, db)

    produto_ids = [pid for pid, qty in estoque_map.items() if qty > 0]
    produtos = (
        db.query(models.Produto)
        .filter(models.Produto.id.in_(produto_ids))
        .order_by(models.Produto.nome)
        .all()
    ) if produto_ids else []

    return render_template("parceiro_catalogo.html",
        active_page = "meu_catalogo",
        parceiro    = parceiro,
        produtos    = produtos,
        estoque_map = estoque_map,
    )


@bp.route("/meu-catalogo/solicitar-devolucao", methods=["POST"])
@login_required
def solicitar_devolucao():
    usuario = _require_parceiro()
    db      = get_db()

    produto_ids = request.form.getlist("produto_id")
    quantidades = request.form.getlist("quantidade")
    motivo      = request.form.get("motivo", "").strip()

    itens = []
    for pid_str, qty_str in zip(produto_ids, quantidades):
        try:
            pid = int(pid_str)
            qty = int(qty_str)
            if pid and qty > 0:
                itens.append({"produto_id": pid, "quantidade": qty})
        except (ValueError, TypeError):
            pass

    if not itens:
        flash("Selecione ao menos um produto para devolver.", "warning")
        return redirect("/meu-catalogo")

    sol = models.SolicitacaoDevolucao(
        parceiro_id = usuario.parceiro_id,
        motivo      = motivo or None,
        status      = "pendente",
    )
    db.add(sol)
    db.flush()

    for item in itens:
        db.add(models.ItemSolicitacaoDevolucao(
            solicitacao_id = sol.id,
            produto_id     = item["produto_id"],
            quantidade     = item["quantidade"],
        ))

    db.commit()
    flash("Solicitação de devolução enviada. Aguarde a confirmação do administrador.", "success")
    return redirect("/meu-catalogo")


# ── Configurações do parceiro ─────────────────────────────────────────────────

@bp.route("/minhas-configuracoes")
@login_required
def minhas_configuracoes():
    usuario  = _require_parceiro()
    db       = get_db()
    parceiro = db.query(models.Parceiro).filter_by(id=usuario.parceiro_id).first()
    if not parceiro:
        abort(403)
    metodos = (
        db.query(models.MetodoParceiro)
        .filter_by(parceiro_id=usuario.parceiro_id)
        .order_by(models.MetodoParceiro.nome)
        .all()
    )
    return render_template("parceiro_configuracoes.html",
        active_page = "minhas_config",
        parceiro    = parceiro,
        metodos     = metodos,
    )


@bp.route("/minhas-configuracoes/metodos/novo", methods=["POST"])
@login_required
def metodo_parceiro_criar():
    usuario = _require_parceiro()
    db      = get_db()
    nome    = request.form.get("nome", "").strip()
    if not nome:
        flash("Informe o nome do método.", "warning")
        return redirect("/minhas-configuracoes")
    existe = db.query(models.MetodoParceiro).filter_by(
        parceiro_id=usuario.parceiro_id, nome=nome
    ).first()
    if existe:
        flash(f"Método '{nome}' já existe.", "warning")
        return redirect("/minhas-configuracoes")
    db.add(models.MetodoParceiro(parceiro_id=usuario.parceiro_id, nome=nome))
    db.commit()
    flash(f"Método '{nome}' adicionado.", "success")
    return redirect("/minhas-configuracoes")


@bp.route("/minhas-configuracoes/metodos/<int:metodo_id>/deletar", methods=["POST"])
@login_required
def metodo_parceiro_deletar(metodo_id):
    usuario = _require_parceiro()
    db      = get_db()
    metodo  = db.query(models.MetodoParceiro).filter_by(
        id=metodo_id, parceiro_id=usuario.parceiro_id
    ).first()
    if metodo:
        nome = metodo.nome
        db.delete(metodo)
        db.commit()
        flash(f"Método '{nome}' removido.", "success")
    return redirect("/minhas-configuracoes")

from flask import Blueprint, render_template
from sqlalchemy import func
from datetime import datetime, timedelta

from ..database import get_db
from .. import models
from .auth import admin_required

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@admin_required
def index():
    db = get_db()
    hoje = datetime.now()
    inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ── KPIs financeiros do mês atual ─────────────────────────────────────────
    def _soma(tipo, desde=None, categoria=None):
        q = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
            models.MovimentacaoFinanceira.tipo == tipo
        )
        if desde:
            q = q.filter(models.MovimentacaoFinanceira.data >= desde)
        if categoria:
            q = q.filter(models.MovimentacaoFinanceira.categoria == categoria)
        return q.scalar() or 0.0

    entradas_mes      = _soma("entrada", inicio_mes)
    saidas_mes        = _soma("saida",   inicio_mes)
    custo_prod_mes    = _soma("saida",   inicio_mes, "Custo de Produção")
    outras_saidas_mes = saidas_mes - custo_prod_mes

    # ── Resumo de estoque ─────────────────────────────────────────────────────
    total_produtos = db.query(func.count(models.Produto.id)).scalar() or 0
    total_itens = db.query(func.sum(models.Produto.quantidade)).scalar() or 0

    # Produtos abaixo do estoque mínimo (alertas)
    alertas = db.query(models.Produto).filter(
        models.Produto.quantidade <= models.Produto.estoque_minimo
    ).all()

    # ── Parceiros ativos (prévia no dashboard) ────────────────────────────────
    parceiros = db.query(models.Parceiro).filter(
        models.Parceiro.status == "ativo"
    ).order_by(models.Parceiro.nome).limit(6).all()

    # ── Gráfico de fluxo de caixa: últimos 6 meses ───────────────────────────
    fluxo_mensal = []
    for i in range(5, -1, -1):
        ref = hoje - timedelta(days=30 * i)
        mes_inicio = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        mes_fim = hoje if i == 0 else (ref.replace(day=28) + timedelta(days=4)) - timedelta(days=(ref.replace(day=28) + timedelta(days=4)).day)

        ent = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
            models.MovimentacaoFinanceira.tipo == "entrada",
            models.MovimentacaoFinanceira.data >= mes_inicio,
            models.MovimentacaoFinanceira.data <= mes_fim,
        ).scalar() or 0.0

        sai = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
            models.MovimentacaoFinanceira.tipo == "saida",
            models.MovimentacaoFinanceira.data >= mes_inicio,
            models.MovimentacaoFinanceira.data <= mes_fim,
        ).scalar() or 0.0

        custo = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
            models.MovimentacaoFinanceira.tipo == "saida",
            models.MovimentacaoFinanceira.categoria == "Custo de Produção",
            models.MovimentacaoFinanceira.data >= mes_inicio,
            models.MovimentacaoFinanceira.data <= mes_fim,
        ).scalar() or 0.0

        fluxo_mensal.append({
            "mes":         mes_inicio.strftime("%b/%Y"),
            "entradas":    round(ent, 2),
            "saidas":      round(sai, 2),
            "custo_prod":  round(custo, 2),
            "outras":      round(sai - custo, 2),
            "lucro":       round(ent - sai, 2),
        })

    return render_template("index.html",
        active_page="dashboard",
        hoje=hoje.strftime("%d de %B de %Y"),
        financeiro={
            "entradas_mes":      round(entradas_mes, 2),
            "saidas_mes":        round(saidas_mes, 2),
            "custo_prod_mes":    round(custo_prod_mes, 2),
            "outras_saidas_mes": round(outras_saidas_mes, 2),
            "lucro_mes":         round(entradas_mes - saidas_mes, 2),
        },
        estoque={
            "total_produtos": total_produtos,
            "total_itens": int(total_itens or 0),
            "alertas": [{"id": p.id, "nome": p.nome, "quantidade": p.quantidade, "estoque_minimo": p.estoque_minimo} for p in alertas],
        },
        parceiros=parceiros,
        fluxo_mensal=fluxo_mensal,
    )


@bp.route("/apresentacao")
@admin_required
def apresentacao():
    return render_template("apresentacao.html", active_page="apresentacao")

# Responsabilidade: dashboard principal do administrador (rota /).
# Agrega KPIs financeiros do mês, alertas de estoque mínimo, lista de parceiros
# ativos e dados dos últimos 6 meses para o gráfico de fluxo de caixa.

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import datetime, timedelta
from ..database import get_db
from .. import models

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(db: Session = Depends(get_db)):
    hoje = datetime.now()
    inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Resumo financeiro do mês
    entradas_mes = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "entrada",
        models.MovimentacaoFinanceira.data >= inicio_mes
    ).scalar() or 0.0

    saidas_mes = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "saida",
        models.MovimentacaoFinanceira.data >= inicio_mes
    ).scalar() or 0.0

    # Totais gerais
    total_entradas = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "entrada"
    ).scalar() or 0.0

    total_saidas = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "saida"
    ).scalar() or 0.0

    # Estoque
    total_produtos = db.query(func.count(models.Produto.id)).scalar() or 0
    total_itens = db.query(func.sum(models.Produto.quantidade)).scalar() or 0

    # Estoque baixo
    alertas = db.query(models.Produto).filter(
        models.Produto.quantidade <= models.Produto.estoque_minimo
    ).all()

    alertas_list = [
        {
            "id": p.id,
            "nome": p.nome,
            "quantidade": p.quantidade,
            "estoque_minimo": p.estoque_minimo
        }
        for p in alertas
    ]

    # Parceiros ativos
    parceiros_ativos = db.query(func.count(models.Parceiro.id)).filter(
        models.Parceiro.status == "ativo"
    ).scalar() or 0

    # Fluxo dos últimos 6 meses
    fluxo_mensal = []
    for i in range(5, -1, -1):
        ref = hoje - timedelta(days=30 * i)
        mes_inicio = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if i == 0:
            mes_fim = hoje
        else:
            proximo = ref.replace(day=28) + timedelta(days=4)
            mes_fim = proximo - timedelta(days=proximo.day)

        ent = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
            models.MovimentacaoFinanceira.tipo == "entrada",
            models.MovimentacaoFinanceira.data >= mes_inicio,
            models.MovimentacaoFinanceira.data <= mes_fim
        ).scalar() or 0.0

        sai = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
            models.MovimentacaoFinanceira.tipo == "saida",
            models.MovimentacaoFinanceira.data >= mes_inicio,
            models.MovimentacaoFinanceira.data <= mes_fim
        ).scalar() or 0.0

        fluxo_mensal.append({
            "mes": mes_inicio.strftime("%b/%Y"),
            "entradas": round(ent, 2),
            "saidas": round(sai, 2),
            "lucro": round(ent - sai, 2)
        })

    return {
        "financeiro": {
            "entradas_mes": round(entradas_mes, 2),
            "saidas_mes": round(saidas_mes, 2),
            "lucro_mes": round(entradas_mes - saidas_mes, 2),
            "total_entradas": round(total_entradas, 2),
            "total_saidas": round(total_saidas, 2),
            "lucro_total": round(total_entradas - total_saidas, 2),
        },
        "estoque": {
            "total_produtos": total_produtos,
            "total_itens": int(total_itens),
            "alertas_estoque_baixo": len(alertas_list),
            "alertas": alertas_list
        },
        "parceiros": {
            "ativos": parceiros_ativos
        },
        "fluxo_mensal": fluxo_mensal
    }

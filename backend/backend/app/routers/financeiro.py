from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime
from ..database import get_db
from .. import models
from ..schemas.financeiro import (
    MovimentacaoFinanceira, MovimentacaoFinanceiraCreate, ResumoFinanceiro
)

router = APIRouter(prefix="/api/financeiro", tags=["financeiro"])


@router.get("/resumo", response_model=ResumoFinanceiro)
def resumo_financeiro(db: Session = Depends(get_db)):
    hoje = datetime.now()
    inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_entradas = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "entrada"
    ).scalar() or 0.0

    total_saidas = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "saida"
    ).scalar() or 0.0

    mes_entradas = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "entrada",
        models.MovimentacaoFinanceira.data >= inicio_mes
    ).scalar() or 0.0

    mes_saidas = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
        models.MovimentacaoFinanceira.tipo == "saida",
        models.MovimentacaoFinanceira.data >= inicio_mes
    ).scalar() or 0.0

    return ResumoFinanceiro(
        total_entradas=round(total_entradas, 2),
        total_saidas=round(total_saidas, 2),
        lucro_estimado=round(total_entradas - total_saidas, 2),
        mes_atual_entradas=round(mes_entradas, 2),
        mes_atual_saidas=round(mes_saidas, 2),
        mes_atual_lucro=round(mes_entradas - mes_saidas, 2)
    )


@router.get("", response_model=List[MovimentacaoFinanceira])
def listar_movimentacoes(
    tipo: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(models.MovimentacaoFinanceira)
    if tipo:
        query = query.filter(models.MovimentacaoFinanceira.tipo == tipo)
    if categoria:
        query = query.filter(models.MovimentacaoFinanceira.categoria == categoria)
    return query.order_by(models.MovimentacaoFinanceira.data.desc()).limit(200).all()


@router.post("", response_model=MovimentacaoFinanceira, status_code=201)
def criar_movimentacao(data: MovimentacaoFinanceiraCreate, db: Session = Depends(get_db)):
    mov = models.MovimentacaoFinanceira(**data.model_dump())
    if not mov.data:
        mov.data = datetime.now()
    db.add(mov)
    db.commit()
    db.refresh(mov)
    return mov


@router.delete("/{movimentacao_id}", status_code=204)
def deletar_movimentacao(movimentacao_id: int, db: Session = Depends(get_db)):
    mov = db.query(models.MovimentacaoFinanceira).filter(
        models.MovimentacaoFinanceira.id == movimentacao_id
    ).first()
    if not mov:
        raise HTTPException(status_code=404, detail="Movimentação não encontrada.")
    db.delete(mov)
    db.commit()

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MovimentacaoFinanceiraBase(BaseModel):
    tipo: str  # entrada, saida
    categoria: Optional[str] = None
    descricao: str
    valor: float
    data: Optional[datetime] = None


class MovimentacaoFinanceiraCreate(MovimentacaoFinanceiraBase):
    pass


class MovimentacaoFinanceira(MovimentacaoFinanceiraBase):
    id: int
    criado_em: datetime

    class Config:
        from_attributes = True


class ResumoFinanceiro(BaseModel):
    total_entradas: float
    total_saidas: float
    lucro_estimado: float
    mes_atual_entradas: float
    mes_atual_saidas: float
    mes_atual_lucro: float

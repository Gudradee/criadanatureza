from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ParceiroBase(BaseModel):
    nome: str
    contato: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    observacoes: Optional[str] = None
    status: str = "ativo"


class ParceiroCreate(ParceiroBase):
    pass


class ParceiroUpdate(BaseModel):
    nome: Optional[str] = None
    contato: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    observacoes: Optional[str] = None
    status: Optional[str] = None


class Parceiro(ParceiroBase):
    id: int
    criado_em: datetime

    class Config:
        from_attributes = True


class ItemMovimentacaoBase(BaseModel):
    produto_id: int
    quantidade: int
    preco_unitario: float = 0.0


class EnvioCreate(BaseModel):
    parceiro_id: int
    itens: List[ItemMovimentacaoBase]
    observacoes: Optional[str] = None


class VendaCreate(BaseModel):
    parceiro_id: int
    itens: List[ItemMovimentacaoBase]
    observacoes: Optional[str] = None


class DevolucaoCreate(BaseModel):
    parceiro_id: int
    itens: List[ItemMovimentacaoBase]
    observacoes: Optional[str] = None


class SaldoParceiro(BaseModel):
    parceiro_id: int
    nome: str
    status: str
    total_enviado: int
    total_vendido: int
    total_devolvido: int
    em_maos: int
    valor_em_maos: float


class HistoricoItem(BaseModel):
    id: int
    tipo: str  # envio, venda, devolucao
    data: datetime
    observacoes: Optional[str]
    itens: list

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CategoriaBase(BaseModel):
    nome: str


class CategoriaCreate(CategoriaBase):
    pass


class Categoria(CategoriaBase):
    id: int
    criado_em: datetime

    class Config:
        from_attributes = True


class ProdutoBase(BaseModel):
    nome: str
    categoria_id: Optional[int] = None
    descricao: Optional[str] = None
    quantidade: int = 0
    estoque_minimo: int = 5
    preco_custo: float = 0.0
    preco_venda: float = 0.0
    imagem_url: Optional[str] = None


class ProdutoCreate(ProdutoBase):
    pass


class ProdutoUpdate(BaseModel):
    nome: Optional[str] = None
    categoria_id: Optional[int] = None
    descricao: Optional[str] = None
    quantidade: Optional[int] = None
    estoque_minimo: Optional[int] = None
    preco_custo: Optional[float] = None
    preco_venda: Optional[float] = None
    imagem_url: Optional[str] = None


class Produto(ProdutoBase):
    id: int
    criado_em: datetime
    atualizado_em: datetime
    categoria: Optional[Categoria] = None

    class Config:
        from_attributes = True


class AjusteEstoque(BaseModel):
    quantidade: int
    tipo: str  # entrada, saida, ajuste
    motivo: Optional[str] = None

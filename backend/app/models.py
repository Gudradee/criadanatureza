from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import enum


class StatusParceiro(str, enum.Enum):
    ativo = "ativo"
    inativo = "inativo"


class TipoMovimentacao(str, enum.Enum):
    entrada = "entrada"
    saida = "saida"
    ajuste = "ajuste"


class TipoFinanceiro(str, enum.Enum):
    entrada = "entrada"
    saida = "saida"


class Categoria(Base):
    __tablename__ = "categorias"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), unique=True, nullable=False)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    produtos = relationship("Produto", back_populates="categoria")


class Produto(Base):
    __tablename__ = "produtos"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(200), nullable=False)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    descricao = Column(Text, nullable=True)
    quantidade = Column(Integer, default=0)
    estoque_minimo = Column(Integer, default=5)
    preco_custo = Column(Float, default=0.0)
    preco_venda = Column(Float, default=0.0)
    imagem_url = Column(String(500), nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    categoria = relationship("Categoria", back_populates="produtos")
    movimentacoes = relationship("MovimentacaoEstoque", back_populates="produto")
    envios = relationship("ItemEnvio", back_populates="produto")
    vendas = relationship("ItemVenda", back_populates="produto")
    devolucoes = relationship("ItemDevolucao", back_populates="produto")


class MovimentacaoEstoque(Base):
    __tablename__ = "movimentacoes_estoque"

    id = Column(Integer, primary_key=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    tipo = Column(String(20), nullable=False)  # entrada, saida, ajuste
    quantidade = Column(Integer, nullable=False)
    motivo = Column(String(300), nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    produto = relationship("Produto", back_populates="movimentacoes")


class Parceiro(Base):
    __tablename__ = "parceiros"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(200), nullable=False)
    contato = Column(String(200), nullable=True)
    telefone = Column(String(50), nullable=True)
    email = Column(String(200), nullable=True)
    observacoes = Column(Text, nullable=True)
    status = Column(String(20), default="ativo")
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    envios = relationship("Envio", back_populates="parceiro")
    vendas = relationship("Venda", back_populates="parceiro")
    devolucoes = relationship("Devolucao", back_populates="parceiro")


class Envio(Base):
    __tablename__ = "envios"

    id = Column(Integer, primary_key=True, index=True)
    parceiro_id = Column(Integer, ForeignKey("parceiros.id"), nullable=False)
    observacoes = Column(Text, nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    parceiro = relationship("Parceiro", back_populates="envios")
    itens = relationship("ItemEnvio", back_populates="envio")


class ItemEnvio(Base):
    __tablename__ = "itens_envio"

    id = Column(Integer, primary_key=True, index=True)
    envio_id = Column(Integer, ForeignKey("envios.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantidade = Column(Integer, nullable=False)
    preco_unitario = Column(Float, default=0.0)

    envio = relationship("Envio", back_populates="itens")
    produto = relationship("Produto", back_populates="envios")


class Venda(Base):
    __tablename__ = "vendas"

    id = Column(Integer, primary_key=True, index=True)
    parceiro_id = Column(Integer, ForeignKey("parceiros.id"), nullable=False)
    observacoes = Column(Text, nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    parceiro = relationship("Parceiro", back_populates="vendas")
    itens = relationship("ItemVenda", back_populates="venda")


class ItemVenda(Base):
    __tablename__ = "itens_venda"

    id = Column(Integer, primary_key=True, index=True)
    venda_id = Column(Integer, ForeignKey("vendas.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantidade = Column(Integer, nullable=False)
    preco_unitario = Column(Float, default=0.0)

    venda = relationship("Venda", back_populates="itens")
    produto = relationship("Produto", back_populates="vendas")


class Devolucao(Base):
    __tablename__ = "devolucoes"

    id = Column(Integer, primary_key=True, index=True)
    parceiro_id = Column(Integer, ForeignKey("parceiros.id"), nullable=False)
    observacoes = Column(Text, nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    parceiro = relationship("Parceiro", back_populates="devolucoes")
    itens = relationship("ItemDevolucao", back_populates="devolucao")


class ItemDevolucao(Base):
    __tablename__ = "itens_devolucao"

    id = Column(Integer, primary_key=True, index=True)
    devolucao_id = Column(Integer, ForeignKey("devolucoes.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantidade = Column(Integer, nullable=False)
    preco_unitario = Column(Float, default=0.0)

    devolucao = relationship("Devolucao", back_populates="itens")
    produto = relationship("Produto", back_populates="devolucoes")


class MovimentacaoFinanceira(Base):
    __tablename__ = "movimentacoes_financeiras"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String(20), nullable=False)  # entrada, saida
    categoria = Column(String(100), nullable=True)
    descricao = Column(String(300), nullable=False)
    valor = Column(Float, nullable=False)
    data = Column(DateTime(timezone=True), server_default=func.now())
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Enum, Boolean, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import enum


# ── Enums ─────────────────────────────────────────────────────────────────────

class StatusParceiro(str, enum.Enum):
    ativo   = "ativo"
    inativo = "inativo"


class TipoMovimentacao(str, enum.Enum):
    entrada = "entrada"
    saida   = "saida"
    ajuste  = "ajuste"


class TipoFinanceiro(str, enum.Enum):
    entrada = "entrada"
    saida   = "saida"


class StatusPreVenda(str, enum.Enum):
    aguardando = "aguardando"
    confirmada = "confirmada"
    cancelada  = "cancelada"


class RoleUsuario(str, enum.Enum):
    admin    = "admin"
    parceiro = "parceiro"


# ── Associação: produtos por catálogo de parceiro ──────────────────────────────

produto_parceiro = Table(
    "produtos_parceiros",
    Base.metadata,
    Column("parceiro_id", Integer, ForeignKey("parceiros.id"), primary_key=True),
    Column("produto_id",  Integer, ForeignKey("produtos.id"),  primary_key=True),
)


# ── Usuários (autenticação interna) ───────────────────────────────────────────

class Usuario(Base):
    """
    Conta de acesso ao painel administrativo.
    - role='admin'    → acesso total (dono/gerente)
    - role='parceiro' → acesso restrito ao próprio caixa e financeiro
    senha_hash nunca é exposta em templates ou respostas HTTP.
    """
    __tablename__ = "usuarios"

    id          = Column(Integer, primary_key=True, index=True)
    nome        = Column(String(200), nullable=False)
    username    = Column(String(100), unique=True, nullable=False, index=True)
    senha_hash  = Column(String(256), nullable=False)          # NUNCA expor
    role        = Column(String(20),  nullable=False, default="parceiro")
    parceiro_id = Column(Integer, ForeignKey("parceiros.id"), nullable=True)
    ativo       = Column(Boolean, nullable=False, default=True)
    criado_em   = Column(DateTime(timezone=True), server_default=func.now())

    parceiro = relationship("Parceiro", back_populates="usuario")


# ── Catálogo ──────────────────────────────────────────────────────────────────

class Categoria(Base):
    __tablename__ = "categorias"

    id        = Column(Integer, primary_key=True, index=True)
    nome      = Column(String(100), unique=True, nullable=False)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    produtos  = relationship("Produto", back_populates="categoria")


class Produto(Base):
    __tablename__ = "produtos"

    id             = Column(Integer, primary_key=True, index=True)
    nome           = Column(String(200), nullable=False)
    categoria_id   = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    descricao      = Column(Text, nullable=True)
    quantidade     = Column(Integer, default=0)
    estoque_minimo = Column(Integer, default=5)
    preco_custo    = Column(Float, default=0.0)
    preco_venda    = Column(Float, default=0.0)
    imagem_url     = Column(String(500), nullable=True)
    criado_em      = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    categoria          = relationship("Categoria", back_populates="produtos")
    movimentacoes      = relationship("MovimentacaoEstoque", back_populates="produto")
    envios             = relationship("ItemEnvio", back_populates="produto")
    vendas             = relationship("ItemVenda", back_populates="produto")
    devolucoes         = relationship("ItemDevolucao", back_populates="produto")
    itens_pre_venda    = relationship("ItemPreVenda", back_populates="produto")
    itens_venda_final  = relationship("ItemVendaFinal", back_populates="produto")
    parceiros_catalogo = relationship("Parceiro", secondary=produto_parceiro, back_populates="produtos_catalogo")


# ── Estoque ───────────────────────────────────────────────────────────────────

class MovimentacaoEstoque(Base):
    __tablename__ = "movimentacoes_estoque"

    id         = Column(Integer, primary_key=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    tipo       = Column(String(20), nullable=False)
    quantidade = Column(Integer, nullable=False)
    motivo     = Column(String(300), nullable=True)
    criado_em  = Column(DateTime(timezone=True), server_default=func.now())

    produto    = relationship("Produto", back_populates="movimentacoes")


# ── Parceiros ─────────────────────────────────────────────────────────────────

class Parceiro(Base):
    __tablename__ = "parceiros"

    id                   = Column(Integer, primary_key=True, index=True)
    nome                 = Column(String(200), nullable=False)
    contato              = Column(String(200), nullable=True)
    telefone             = Column(String(50),  nullable=True)
    email                = Column(String(200), nullable=True)
    observacoes          = Column(Text, nullable=True)
    status               = Column(String(20), default="ativo")
    comissao_percentual  = Column(Float, default=0.0, nullable=False)
    criado_em            = Column(DateTime(timezone=True), server_default=func.now())

    usuario          = relationship("Usuario", back_populates="parceiro", uselist=False)
    envios           = relationship("Envio",     back_populates="parceiro")
    vendas           = relationship("Venda",     back_populates="parceiro")
    devolucoes       = relationship("Devolucao", back_populates="parceiro")
    pre_vendas       = relationship("PreVenda",  back_populates="parceiro")
    produtos_catalogo = relationship("Produto", secondary=produto_parceiro, back_populates="parceiros_catalogo")
    solicitacoes_devolucao = relationship("SolicitacaoDevolucao", back_populates="parceiro")


class Envio(Base):
    __tablename__ = "envios"

    id          = Column(Integer, primary_key=True, index=True)
    parceiro_id = Column(Integer, ForeignKey("parceiros.id"), nullable=False)
    observacoes = Column(Text, nullable=True)
    criado_em   = Column(DateTime(timezone=True), server_default=func.now())

    parceiro    = relationship("Parceiro", back_populates="envios")
    itens       = relationship("ItemEnvio", back_populates="envio")


class ItemEnvio(Base):
    __tablename__ = "itens_envio"

    id             = Column(Integer, primary_key=True, index=True)
    envio_id       = Column(Integer, ForeignKey("envios.id"), nullable=False)
    produto_id     = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantidade     = Column(Integer, nullable=False)
    preco_unitario = Column(Float, default=0.0)

    envio          = relationship("Envio",   back_populates="itens")
    produto        = relationship("Produto", back_populates="envios")


class Venda(Base):
    __tablename__ = "vendas"

    id          = Column(Integer, primary_key=True, index=True)
    parceiro_id = Column(Integer, ForeignKey("parceiros.id"), nullable=False)
    observacoes = Column(Text, nullable=True)
    criado_em   = Column(DateTime(timezone=True), server_default=func.now())

    parceiro    = relationship("Parceiro", back_populates="vendas")
    itens       = relationship("ItemVenda", back_populates="venda")


class ItemVenda(Base):
    __tablename__ = "itens_venda"

    id             = Column(Integer, primary_key=True, index=True)
    venda_id       = Column(Integer, ForeignKey("vendas.id"), nullable=False)
    produto_id     = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantidade     = Column(Integer, nullable=False)
    preco_unitario = Column(Float, default=0.0)

    venda          = relationship("Venda",   back_populates="itens")
    produto        = relationship("Produto", back_populates="vendas")


class Devolucao(Base):
    __tablename__ = "devolucoes"

    id          = Column(Integer, primary_key=True, index=True)
    parceiro_id = Column(Integer, ForeignKey("parceiros.id"), nullable=False)
    observacoes = Column(Text, nullable=True)
    criado_em   = Column(DateTime(timezone=True), server_default=func.now())

    parceiro    = relationship("Parceiro",    back_populates="devolucoes")
    itens       = relationship("ItemDevolucao", back_populates="devolucao")


class ItemDevolucao(Base):
    __tablename__ = "itens_devolucao"

    id             = Column(Integer, primary_key=True, index=True)
    devolucao_id   = Column(Integer, ForeignKey("devolucoes.id"), nullable=False)
    produto_id     = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantidade     = Column(Integer, nullable=False)
    preco_unitario = Column(Float, default=0.0)

    devolucao      = relationship("Devolucao", back_populates="itens")
    produto        = relationship("Produto",   back_populates="devolucoes")


# ── Financeiro ────────────────────────────────────────────────────────────────

class MovimentacaoFinanceira(Base):
    __tablename__ = "movimentacoes_financeiras"

    id          = Column(Integer, primary_key=True, index=True)
    tipo        = Column(String(20),  nullable=False)
    categoria   = Column(String(100), nullable=True)
    descricao   = Column(String(300), nullable=False)
    valor       = Column(Float, nullable=False)
    data        = Column(DateTime(timezone=True), server_default=func.now())
    criado_em   = Column(DateTime(timezone=True), server_default=func.now())
    parceiro_id = Column(Integer, ForeignKey("parceiros.id"), nullable=True)

    parceiro    = relationship("Parceiro")


# ── Fluxo de venda por QR Code ────────────────────────────────────────────────

class PreVenda(Base):
    """
    Intenção de compra criada pelo cliente no painel público.
    parceiro_id identifica qual parceiro gerou o QR Code do catálogo.
    """
    __tablename__ = "pre_vendas"

    id            = Column(Integer, primary_key=True, index=True)
    token         = Column(String(64), unique=True, nullable=False, index=True)
    status        = Column(String(20), default=StatusPreVenda.aguardando, nullable=False)
    observacoes   = Column(Text, nullable=True)
    criado_em     = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expira_em     = Column(DateTime(timezone=True), nullable=True)
    parceiro_id   = Column(Integer, ForeignKey("parceiros.id"), nullable=True)

    parceiro    = relationship("Parceiro", back_populates="pre_vendas")
    itens       = relationship("ItemPreVenda", back_populates="pre_venda", cascade="all, delete-orphan")
    venda_final = relationship("VendaFinal",   back_populates="pre_venda", uselist=False)


class ItemPreVenda(Base):
    __tablename__ = "itens_pre_venda"

    id           = Column(Integer, primary_key=True, index=True)
    pre_venda_id = Column(Integer, ForeignKey("pre_vendas.id"), nullable=False)
    produto_id   = Column(Integer, ForeignKey("produtos.id"),   nullable=False)
    quantidade   = Column(Integer, nullable=False)
    preco_ref    = Column(Float,   nullable=False)

    pre_venda    = relationship("PreVenda", back_populates="itens")
    produto      = relationship("Produto",  back_populates="itens_pre_venda")


class VendaFinal(Base):
    __tablename__ = "vendas_finais"

    id                   = Column(Integer, primary_key=True, index=True)
    pre_venda_id         = Column(Integer, ForeignKey("pre_vendas.id"), nullable=True)
    data_venda           = Column(DateTime(timezone=True), server_default=func.now())
    forma_pagamento      = Column(String(50), nullable=True)
    valor_total_bruto    = Column(Float, nullable=False)
    valor_total_desconto = Column(Float, default=0.0)
    valor_total_liquido  = Column(Float, nullable=False)
    observacoes          = Column(Text, nullable=True)

    pre_venda = relationship("PreVenda",      back_populates="venda_final")
    itens     = relationship("ItemVendaFinal", back_populates="venda", cascade="all, delete-orphan")


class ItemVendaFinal(Base):
    __tablename__ = "itens_venda_final"

    id                     = Column(Integer, primary_key=True, index=True)
    venda_id               = Column(Integer, ForeignKey("vendas_finais.id"), nullable=False)
    produto_id             = Column(Integer, ForeignKey("produtos.id"),      nullable=False)
    nome_produto           = Column(String(200), nullable=False)

    quantidade             = Column(Integer, nullable=False)
    preco_unitario_bruto   = Column(Float, nullable=False)
    desconto_valor         = Column(Float, default=0.0)
    desconto_percentual    = Column(Float, default=0.0)
    preco_unitario_liquido = Column(Float, nullable=False)
    subtotal_bruto         = Column(Float, nullable=False)
    subtotal_liquido       = Column(Float, nullable=False)

    venda   = relationship("VendaFinal", back_populates="itens")
    produto = relationship("Produto",    back_populates="itens_venda_final")


# ── Solicitações de devolução (iniciadas pelo parceiro) ───────────────────────

class SolicitacaoDevolucao(Base):
    __tablename__ = "solicitacoes_devolucao"

    id            = Column(Integer, primary_key=True, index=True)
    parceiro_id   = Column(Integer, ForeignKey("parceiros.id"), nullable=False)
    status        = Column(String(20), default="pendente", nullable=False)  # pendente/confirmada/rejeitada
    motivo        = Column(Text, nullable=True)
    criado_em     = Column(DateTime(timezone=True), server_default=func.now())
    confirmado_em = Column(DateTime(timezone=True), nullable=True)

    parceiro = relationship("Parceiro", back_populates="solicitacoes_devolucao")
    itens    = relationship("ItemSolicitacaoDevolucao", back_populates="solicitacao", cascade="all, delete-orphan")


class ItemSolicitacaoDevolucao(Base):
    __tablename__ = "itens_solicitacao_devolucao"

    id             = Column(Integer, primary_key=True, index=True)
    solicitacao_id = Column(Integer, ForeignKey("solicitacoes_devolucao.id"), nullable=False)
    produto_id     = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantidade     = Column(Integer, nullable=False)

    solicitacao = relationship("SolicitacaoDevolucao", back_populates="itens")
    produto     = relationship("Produto")

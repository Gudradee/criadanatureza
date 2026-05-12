from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from .. import models
from ..schemas.produto import (
    Produto, ProdutoCreate, ProdutoUpdate,
    Categoria, CategoriaCreate, AjusteEstoque
)

router = APIRouter(prefix="/api", tags=["estoque"])


# ── Categorias ──────────────────────────────────────────────────────────────

@router.get("/categorias", response_model=List[Categoria])
def listar_categorias(db: Session = Depends(get_db)):
    return db.query(models.Categoria).order_by(models.Categoria.nome).all()


@router.post("/categorias", response_model=Categoria, status_code=201)
def criar_categoria(data: CategoriaCreate, db: Session = Depends(get_db)):
    existente = db.query(models.Categoria).filter(models.Categoria.nome == data.nome).first()
    if existente:
        raise HTTPException(status_code=400, detail="Categoria já existe.")
    categoria = models.Categoria(nome=data.nome)
    db.add(categoria)
    db.commit()
    db.refresh(categoria)
    return categoria


@router.delete("/categorias/{categoria_id}", status_code=204)
def deletar_categoria(categoria_id: int, db: Session = Depends(get_db)):
    categoria = db.query(models.Categoria).filter(models.Categoria.id == categoria_id).first()
    if not categoria:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    db.delete(categoria)
    db.commit()


# ── Produtos ─────────────────────────────────────────────────────────────────

@router.get("/produtos", response_model=List[Produto])
def listar_produtos(
    busca: Optional[str] = Query(None),
    categoria_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(models.Produto)
    if busca:
        query = query.filter(models.Produto.nome.ilike(f"%{busca}%"))
    if categoria_id:
        query = query.filter(models.Produto.categoria_id == categoria_id)
    return query.order_by(models.Produto.nome).all()


@router.get("/produtos/{produto_id}", response_model=Produto)
def obter_produto(produto_id: int, db: Session = Depends(get_db)):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")
    return produto


@router.post("/produtos", response_model=Produto, status_code=201)
def criar_produto(data: ProdutoCreate, db: Session = Depends(get_db)):
    produto = models.Produto(**data.model_dump())
    db.add(produto)
    db.commit()
    db.refresh(produto)

    # Registra movimentação inicial se quantidade > 0
    if produto.quantidade > 0:
        mov = models.MovimentacaoEstoque(
            produto_id=produto.id,
            tipo="entrada",
            quantidade=produto.quantidade,
            motivo="Estoque inicial"
        )
        db.add(mov)
        db.commit()

    return produto


@router.put("/produtos/{produto_id}", response_model=Produto)
def atualizar_produto(produto_id: int, data: ProdutoUpdate, db: Session = Depends(get_db)):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(produto, campo, valor)

    db.commit()
    db.refresh(produto)
    return produto


@router.delete("/produtos/{produto_id}", status_code=204)
def deletar_produto(produto_id: int, db: Session = Depends(get_db)):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")
    db.delete(produto)
    db.commit()


@router.post("/produtos/{produto_id}/ajuste", response_model=Produto)
def ajustar_estoque(produto_id: int, data: AjusteEstoque, db: Session = Depends(get_db)):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    if data.tipo == "entrada":
        produto.quantidade += data.quantidade
    elif data.tipo == "saida":
        if produto.quantidade < data.quantidade:
            raise HTTPException(status_code=400, detail="Estoque insuficiente.")
        produto.quantidade -= data.quantidade
    elif data.tipo == "ajuste":
        produto.quantidade = data.quantidade
    else:
        raise HTTPException(status_code=400, detail="Tipo inválido. Use: entrada, saida ou ajuste.")

    mov = models.MovimentacaoEstoque(
        produto_id=produto.id,
        tipo=data.tipo,
        quantidade=data.quantidade,
        motivo=data.motivo
    )
    db.add(mov)
    db.commit()
    db.refresh(produto)
    return produto


@router.get("/produtos/{produto_id}/movimentacoes")
def historico_produto(produto_id: int, db: Session = Depends(get_db)):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")
    movs = (
        db.query(models.MovimentacaoEstoque)
        .filter(models.MovimentacaoEstoque.produto_id == produto_id)
        .order_by(models.MovimentacaoEstoque.criado_em.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": m.id,
            "tipo": m.tipo,
            "quantidade": m.quantidade,
            "motivo": m.motivo,
            "data": m.criado_em.isoformat() if m.criado_em else None
        }
        for m in movs
    ]

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List
from ..database import get_db
from .. import models
from ..schemas.parceiro import (
    Parceiro, ParceiroCreate, ParceiroUpdate,
    EnvioCreate, VendaCreate, DevolucaoCreate, SaldoParceiro
)

router = APIRouter(prefix="/api/parceiros", tags=["parceiros"])


def _calcular_saldo(parceiro: models.Parceiro) -> dict:
    enviado = sum(
        item.quantidade
        for envio in parceiro.envios
        for item in envio.itens
    )
    vendido = sum(
        item.quantidade
        for venda in parceiro.vendas
        for item in venda.itens
    )
    devolvido = sum(
        item.quantidade
        for dev in parceiro.devolucoes
        for item in dev.itens
    )
    em_maos = enviado - vendido - devolvido

    valor_em_maos = sum(
        item.quantidade * item.preco_unitario
        for envio in parceiro.envios
        for item in envio.itens
    ) - sum(
        item.quantidade * item.preco_unitario
        for venda in parceiro.vendas
        for item in venda.itens
    ) - sum(
        item.quantidade * item.preco_unitario
        for dev in parceiro.devolucoes
        for item in dev.itens
    )

    return {
        "parceiro_id": parceiro.id,
        "nome": parceiro.nome,
        "status": parceiro.status,
        "total_enviado": enviado,
        "total_vendido": vendido,
        "total_devolvido": devolvido,
        "em_maos": max(em_maos, 0),
        "valor_em_maos": round(max(valor_em_maos, 0), 2)
    }


@router.get("", response_model=List[Parceiro])
def listar_parceiros(db: Session = Depends(get_db)):
    return db.query(models.Parceiro).order_by(models.Parceiro.nome).all()


@router.get("/saldos")
def saldos_parceiros(db: Session = Depends(get_db)):
    parceiros = (
        db.query(models.Parceiro)
        .options(
            joinedload(models.Parceiro.envios).joinedload(models.Envio.itens),
            joinedload(models.Parceiro.vendas).joinedload(models.Venda.itens),
            joinedload(models.Parceiro.devolucoes).joinedload(models.Devolucao.itens),
        )
        .all()
    )
    return [_calcular_saldo(p) for p in parceiros]


@router.get("/{parceiro_id}", response_model=Parceiro)
def obter_parceiro(parceiro_id: int, db: Session = Depends(get_db)):
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        raise HTTPException(status_code=404, detail="Parceiro não encontrado.")
    return parceiro


@router.get("/{parceiro_id}/saldo")
def saldo_parceiro(parceiro_id: int, db: Session = Depends(get_db)):
    parceiro = (
        db.query(models.Parceiro)
        .options(
            joinedload(models.Parceiro.envios).joinedload(models.Envio.itens),
            joinedload(models.Parceiro.vendas).joinedload(models.Venda.itens),
            joinedload(models.Parceiro.devolucoes).joinedload(models.Devolucao.itens),
        )
        .filter(models.Parceiro.id == parceiro_id)
        .first()
    )
    if not parceiro:
        raise HTTPException(status_code=404, detail="Parceiro não encontrado.")
    return _calcular_saldo(parceiro)


@router.get("/{parceiro_id}/historico")
def historico_parceiro(parceiro_id: int, db: Session = Depends(get_db)):
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        raise HTTPException(status_code=404, detail="Parceiro não encontrado.")

    historico = []

    envios = (
        db.query(models.Envio)
        .options(joinedload(models.Envio.itens).joinedload(models.ItemEnvio.produto))
        .filter(models.Envio.parceiro_id == parceiro_id)
        .all()
    )
    for e in envios:
        historico.append({
            "id": e.id,
            "tipo": "envio",
            "data": e.criado_em.isoformat() if e.criado_em else None,
            "observacoes": e.observacoes,
            "itens": [
                {
                    "produto": i.produto.nome if i.produto else "—",
                    "quantidade": i.quantidade,
                    "preco_unitario": i.preco_unitario
                }
                for i in e.itens
            ]
        })

    vendas = (
        db.query(models.Venda)
        .options(joinedload(models.Venda.itens).joinedload(models.ItemVenda.produto))
        .filter(models.Venda.parceiro_id == parceiro_id)
        .all()
    )
    for v in vendas:
        historico.append({
            "id": v.id,
            "tipo": "venda",
            "data": v.criado_em.isoformat() if v.criado_em else None,
            "observacoes": v.observacoes,
            "itens": [
                {
                    "produto": i.produto.nome if i.produto else "—",
                    "quantidade": i.quantidade,
                    "preco_unitario": i.preco_unitario
                }
                for i in v.itens
            ]
        })

    devolucoes = (
        db.query(models.Devolucao)
        .options(joinedload(models.Devolucao.itens).joinedload(models.ItemDevolucao.produto))
        .filter(models.Devolucao.parceiro_id == parceiro_id)
        .all()
    )
    for d in devolucoes:
        historico.append({
            "id": d.id,
            "tipo": "devolucao",
            "data": d.criado_em.isoformat() if d.criado_em else None,
            "observacoes": d.observacoes,
            "itens": [
                {
                    "produto": i.produto.nome if i.produto else "—",
                    "quantidade": i.quantidade,
                    "preco_unitario": i.preco_unitario
                }
                for i in d.itens
            ]
        })

    historico.sort(key=lambda x: x["data"] or "", reverse=True)
    return historico


@router.post("", response_model=Parceiro, status_code=201)
def criar_parceiro(data: ParceiroCreate, db: Session = Depends(get_db)):
    parceiro = models.Parceiro(**data.model_dump())
    db.add(parceiro)
    db.commit()
    db.refresh(parceiro)
    return parceiro


@router.put("/{parceiro_id}", response_model=Parceiro)
def atualizar_parceiro(parceiro_id: int, data: ParceiroUpdate, db: Session = Depends(get_db)):
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        raise HTTPException(status_code=404, detail="Parceiro não encontrado.")
    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(parceiro, campo, valor)
    db.commit()
    db.refresh(parceiro)
    return parceiro


@router.delete("/{parceiro_id}", status_code=204)
def deletar_parceiro(parceiro_id: int, db: Session = Depends(get_db)):
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        raise HTTPException(status_code=404, detail="Parceiro não encontrado.")
    db.delete(parceiro)
    db.commit()


@router.post("/{parceiro_id}/envio", status_code=201)
def registrar_envio(parceiro_id: int, data: EnvioCreate, db: Session = Depends(get_db)):
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        raise HTTPException(status_code=404, detail="Parceiro não encontrado.")

    envio = models.Envio(parceiro_id=parceiro_id, observacoes=data.observacoes)
    db.add(envio)
    db.flush()

    for item in data.itens:
        produto = db.query(models.Produto).filter(models.Produto.id == item.produto_id).first()
        if not produto:
            raise HTTPException(status_code=404, detail=f"Produto {item.produto_id} não encontrado.")
        if produto.quantidade < item.quantidade:
            raise HTTPException(status_code=400, detail=f"Estoque insuficiente para '{produto.nome}'.")

        produto.quantidade -= item.quantidade
        mov = models.MovimentacaoEstoque(
            produto_id=produto.id,
            tipo="saida",
            quantidade=item.quantidade,
            motivo=f"Envio ao parceiro {parceiro.nome}"
        )
        db.add(mov)

        item_envio = models.ItemEnvio(
            envio_id=envio.id,
            produto_id=item.produto_id,
            quantidade=item.quantidade,
            preco_unitario=item.preco_unitario
        )
        db.add(item_envio)

    db.commit()
    return {"mensagem": "Envio registrado com sucesso.", "envio_id": envio.id}


@router.post("/{parceiro_id}/venda", status_code=201)
def registrar_venda(parceiro_id: int, data: VendaCreate, db: Session = Depends(get_db)):
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        raise HTTPException(status_code=404, detail="Parceiro não encontrado.")

    venda = models.Venda(parceiro_id=parceiro_id, observacoes=data.observacoes)
    db.add(venda)
    db.flush()

    total_venda = 0.0
    for item in data.itens:
        item_venda = models.ItemVenda(
            venda_id=venda.id,
            produto_id=item.produto_id,
            quantidade=item.quantidade,
            preco_unitario=item.preco_unitario
        )
        db.add(item_venda)
        total_venda += item.quantidade * item.preco_unitario

    # Registra entrada financeira automaticamente
    if total_venda > 0:
        mov_fin = models.MovimentacaoFinanceira(
            tipo="entrada",
            categoria="Venda Revendedor",
            descricao=f"Venda registrada pelo parceiro {parceiro.nome}",
            valor=total_venda
        )
        db.add(mov_fin)

    db.commit()
    return {"mensagem": "Venda registrada com sucesso.", "venda_id": venda.id}


@router.post("/{parceiro_id}/devolucao", status_code=201)
def registrar_devolucao(parceiro_id: int, data: DevolucaoCreate, db: Session = Depends(get_db)):
    parceiro = db.query(models.Parceiro).filter(models.Parceiro.id == parceiro_id).first()
    if not parceiro:
        raise HTTPException(status_code=404, detail="Parceiro não encontrado.")

    devolucao = models.Devolucao(parceiro_id=parceiro_id, observacoes=data.observacoes)
    db.add(devolucao)
    db.flush()

    for item in data.itens:
        produto = db.query(models.Produto).filter(models.Produto.id == item.produto_id).first()
        if produto:
            produto.quantidade += item.quantidade
            mov = models.MovimentacaoEstoque(
                produto_id=produto.id,
                tipo="entrada",
                quantidade=item.quantidade,
                motivo=f"Devolução do parceiro {parceiro.nome}"
            )
            db.add(mov)

        item_dev = models.ItemDevolucao(
            devolucao_id=devolucao.id,
            produto_id=item.produto_id,
            quantidade=item.quantidade,
            preco_unitario=item.preco_unitario
        )
        db.add(item_dev)

    db.commit()
    return {"mensagem": "Devolução registrada com sucesso.", "devolucao_id": devolucao.id}

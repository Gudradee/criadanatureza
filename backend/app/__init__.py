import os
import secrets as _secrets
from datetime import timedelta, timezone
from pathlib import Path

from flask import Flask, g, send_from_directory

from .database import Base, engine, SessionLocal, get_db
from . import models

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

UPLOADS_DIR = os.environ.get(
    "UPLOADS_DIR",
    os.path.join(os.path.dirname(__file__), "..", "uploads"),
)

os.makedirs(os.path.join(UPLOADS_DIR, "produtos"), exist_ok=True)

def _brl(value):
    try:
        v = float(value)
        formatted = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {formatted}"
    except (TypeError, ValueError):
        return "R$ 0,00"

_BRT = timezone(timedelta(hours=-3))

def _localdt(value, fmt="%d/%m/%Y %H:%M"):

    if value is None:
        return "—"
    try:

        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(_BRT).strftime(fmt)
    except Exception:
        return str(value)

def _sync_admin():
    username = os.environ.get("ADMIN_USERNAME", "admin").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()

    if not password:
        print("\n[CDN] AVISO: ADMIN_PASSWORD não definido no .env — admin não será criado/atualizado.\n")
        return

    from .models import Usuario
    from werkzeug.security import generate_password_hash

    db = SessionLocal()
    try:
        admin = db.query(Usuario).filter_by(username=username).first()
        if admin:
            admin.senha_hash = generate_password_hash(password)
            admin.ativo      = True
            db.commit()
        else:
            db.add(Usuario(
                nome       = "Administrador",
                username   = username,
                senha_hash = generate_password_hash(password),
                role       = "admin",
                ativo      = True,
            ))
            db.commit()
            print(f"\n[CDN] Admin '{username}' criado a partir do .env.\n")
    except Exception as e:
        db.rollback()
        print(f"\n[CDN] Erro ao sincronizar admin: {e}\n")
    finally:
        db.close()

def _migrate_db():
    from sqlalchemy import text, inspect
    db = SessionLocal()
    try:
        insp = inspect(engine)

        cols_parceiros = [c["name"] for c in insp.get_columns("parceiros")]
        if "comissao_percentual" not in cols_parceiros:
            db.execute(text("ALTER TABLE parceiros ADD COLUMN comissao_percentual REAL NOT NULL DEFAULT 0.0"))
            db.execute(text("UPDATE parceiros SET comissao_percentual = 0.02"))
            db.commit()
            print("[CDN] Migração: comissao_percentual adicionado.")

        tabelas = insp.get_table_names()
        if "vendas_finais" in tabelas:
            cols_vf = [c["name"] for c in insp.get_columns("vendas_finais")]
            if "metodo_recebimento_id" not in cols_vf:
                db.execute(text("ALTER TABLE vendas_finais ADD COLUMN metodo_recebimento_id INTEGER REFERENCES metodos_recebimento(id)"))
                db.commit()
                print("[CDN] Migração: metodo_recebimento_id adicionado em vendas_finais.")
            if "ponto_venda_id" not in cols_vf:
                db.execute(text("ALTER TABLE vendas_finais ADD COLUMN ponto_venda_id INTEGER REFERENCES pontos_venda(id)"))
                db.commit()
                print("[CDN] Migração: ponto_venda_id adicionado em vendas_finais.")
            if "parceiro_id" not in cols_vf:
                db.execute(text("ALTER TABLE vendas_finais ADD COLUMN parceiro_id INTEGER REFERENCES parceiros(id)"))
                db.commit()
                print("[CDN] Migração: parceiro_id adicionado em vendas_finais.")

        cols_mov = [c["name"] for c in insp.get_columns("movimentacoes_financeiras")]
        if "parceiro_id" not in cols_mov:
            db.execute(text("ALTER TABLE movimentacoes_financeiras ADD COLUMN parceiro_id INTEGER REFERENCES parceiros(id)"))
            db.commit()
            print("[CDN] Migração: parceiro_id adicionado em movimentacoes_financeiras.")

        cols_me = [c["name"] for c in insp.get_columns("movimentacoes_estoque")]
        if "preco_custo_unitario" not in cols_me:
            db.execute(text("ALTER TABLE movimentacoes_estoque ADD COLUMN preco_custo_unitario REAL"))
            db.commit()
            print("[CDN] Migração: preco_custo_unitario adicionado em movimentacoes_estoque.")
        if "preco_venda_unitario" not in cols_me:
            db.execute(text("ALTER TABLE movimentacoes_estoque ADD COLUMN preco_venda_unitario REAL"))
            db.commit()
            print("[CDN] Migração: preco_venda_unitario adicionado em movimentacoes_estoque.")

        if "vendas_finais" in insp.get_table_names():
            cols_vf2 = [c["name"] for c in insp.get_columns("vendas_finais")]
            if "recebido" not in cols_vf2:
                db.execute(text("ALTER TABLE vendas_finais ADD COLUMN recebido BOOLEAN NOT NULL DEFAULT 0"))
                db.commit()
                print("[CDN] Migração: recebido adicionado em vendas_finais.")
            if "recebido_em" not in cols_vf2:
                db.execute(text("ALTER TABLE vendas_finais ADD COLUMN recebido_em DATETIME"))
                db.commit()
                print("[CDN] Migração: recebido_em adicionado em vendas_finais.")

        cols_prod = [c["name"] for c in insp.get_columns("produtos")]
        if "ativo" not in cols_prod:
            db.execute(text("ALTER TABLE produtos ADD COLUMN ativo BOOLEAN NOT NULL DEFAULT 1"))
            db.commit()
            print("[CDN] Migração: ativo adicionado em produtos.")

        cols_desp = [c["name"] for c in insp.get_columns("despesas")]
        if "parceiro_id" not in cols_desp:
            db.execute(text("ALTER TABLE despesas ADD COLUMN parceiro_id INTEGER REFERENCES parceiros(id)"))
            db.commit()
            print("[CDN] Migração: parceiro_id adicionado em despesas.")

        if "produto_id" not in cols_desp:
            db.execute(text("ALTER TABLE despesas ADD COLUMN produto_id INTEGER REFERENCES produtos(id)"))
            db.commit()
            print("[CDN] Migração: produto_id adicionado em despesas.")
            # Backfill: vincula despesas de 'Custo de Produção' ao produto pelo nome
            # (apenas quando o nome corresponde a um único produto, para evitar erro).
            try:
                prod_rows = db.execute(text("SELECT id, nome FROM produtos")).fetchall()
                nome_para_ids = {}
                for pid, pnome in prod_rows:
                    nome_para_ids.setdefault(pnome, []).append(pid)
                desp_rows = db.execute(text(
                    "SELECT id, descricao FROM despesas "
                    "WHERE categoria = 'Custo de Produção' AND produto_id IS NULL"
                )).fetchall()
                vinculadas = 0
                for did, descricao in desp_rows:
                    if not descricao or not descricao.startswith("Produção: "):
                        continue
                    nome = descricao[len("Produção: "):].split(" × ")[0].strip()
                    ids = nome_para_ids.get(nome)
                    if ids and len(ids) == 1:
                        db.execute(text("UPDATE despesas SET produto_id = :pid WHERE id = :did"),
                                   {"pid": ids[0], "did": did})
                        vinculadas += 1
                if vinculadas:
                    db.commit()
                    print(f"[CDN] Migração: {vinculadas} despesa(s) de produção vinculadas a produtos.")
            except Exception as e:
                db.rollback()
                print(f"[CDN] Backfill produto_id em despesas falhou: {e}")
    except Exception as e:
        db.rollback()
        print(f"[CDN] Erro na migração: {e}")
    finally:
        db.close()

def _backfill_financeiro():
    from sqlalchemy import func, text
    from sqlalchemy.orm import joinedload
    db = SessionLocal()
    try:

        orfas = db.query(models.MovimentacaoFinanceira).filter(
            models.MovimentacaoFinanceira.categoria == "Custo de Produção",
            models.MovimentacaoFinanceira.descricao.like("Custo retroativo:%"),
        ).all()
        for o in orfas:
            db.delete(o)
            print(f"[CDN] Removida MF obsoleta: {o.descricao}")
        db.flush()

        producao_mfs = db.query(models.MovimentacaoFinanceira).filter(
            models.MovimentacaoFinanceira.categoria == "Custo de Produção",
            models.MovimentacaoFinanceira.descricao.like("Produção:%"),
        ).all()
        for mf in producao_mfs:
            tem_despesa = db.query(models.Despesa).filter(
                models.Despesa.categoria == "Custo de Produção",
                models.Despesa.descricao == mf.descricao,
            ).first()
            if tem_despesa:
                db.delete(mf)
                print(f"[CDN] Removida MF legada duplicada com Despesa: {mf.descricao}")
        db.flush()

        vendas = (
            db.query(models.VendaFinal)
            .join(models.PreVenda, models.VendaFinal.pre_venda_id == models.PreVenda.id)
            .filter(models.PreVenda.parceiro_id.isnot(None))
            .all()
        )
        for vf in vendas:
            pv = db.query(models.PreVenda).filter_by(id=vf.pre_venda_id).first()
            if not pv or not pv.parceiro_id:
                continue

            parceiro = db.query(models.Parceiro).filter_by(id=pv.parceiro_id).first()
            if not parceiro or parceiro.comissao_percentual <= 0:
                continue

            token_ref = pv.token[:8] if pv.token else str(vf.id)
            comissao_correta = round(vf.valor_total_liquido * parceiro.comissao_percentual, 2)

            ja_tem = db.query(models.MovimentacaoFinanceira).filter(
                models.MovimentacaoFinanceira.categoria == "Comissão Parceiro",
                models.MovimentacaoFinanceira.descricao.contains(token_ref),
            ).first()

            if ja_tem:
                if abs(ja_tem.valor - comissao_correta) > 0.01:
                    print(f"[CDN] Corrigindo comissão {parceiro.nome} venda #{token_ref}: R${ja_tem.valor:.2f} → R${comissao_correta:.2f}")
                    ja_tem.valor = comissao_correta
                    ja_tem.descricao = f"Comissão {parceiro.nome} — Venda #{token_ref} ({parceiro.comissao_percentual * 100:.1f}% sobre receita líquida)"
                continue

            if comissao_correta > 0.01:
                db.add(models.MovimentacaoFinanceira(
                    tipo="saida",
                    categoria="Comissão Parceiro",
                    descricao=f"Comissão {parceiro.nome} — Venda #{token_ref} ({parceiro.comissao_percentual * 100:.1f}% sobre receita líquida)",
                    valor=comissao_correta,
                    parceiro_id=parceiro.id,
                ))
                print(f"[CDN] Backfill comissão {parceiro.nome}: R${comissao_correta:.2f}")

        mfs_comissao = db.query(models.MovimentacaoFinanceira).filter(
            models.MovimentacaoFinanceira.tipo == "saida",
            models.MovimentacaoFinanceira.categoria == "Comissão Parceiro",
        ).all()
        for mf in mfs_comissao:

            despesa_existente = db.query(models.Despesa).filter(
                models.Despesa.categoria == "Comissão Parceiro",
                models.Despesa.descricao == mf.descricao,
            ).first()
            if not despesa_existente:
                desp = models.Despesa(
                    descricao        = mf.descricao,
                    valor            = float(mf.valor or 0),
                    tipo             = "variavel",
                    categoria        = "Comissão Parceiro",
                    data_competencia = mf.data or mf.criado_em or func.now(),
                    parceiro_id      = mf.parceiro_id,
                )
                db.add(desp)
                db.flush()

                db.add(models.ParcelaPagamento(
                    despesa_id = desp.id,
                    numero     = 1,
                    total      = 1,
                    valor      = desp.valor,
                    vencimento = desp.data_competencia,
                    pago       = True,
                    pago_em    = mf.data or mf.criado_em,
                ))
                print(f"[CDN] Comissão MF → Despesa: {mf.descricao}")

            db.delete(mf)
        if mfs_comissao:
            db.flush()

        despesas_sem_parcela = (
            db.query(models.Despesa)
            .outerjoin(models.ParcelaPagamento)
            .filter(models.ParcelaPagamento.id.is_(None))
            .all()
        )
        for d in despesas_sem_parcela:
            db.add(models.ParcelaPagamento(
                despesa_id = d.id,
                numero     = 1,
                total      = 1,
                valor      = d.valor,
                vencimento = d.data_competencia,
                pago       = False,
            ))
        if despesas_sem_parcela:
            print(f"[CDN] Backfill: {len(despesas_sem_parcela)} parcela(s) default criada(s) para despesas legadas.")

        vendas_sem_parcela = (
            db.query(models.VendaFinal)
            .outerjoin(models.ParcelaRecebimento)
            .filter(models.ParcelaRecebimento.id.is_(None))
            .all()
        )
        for vf in vendas_sem_parcela:
            db.add(models.ParcelaRecebimento(
                venda_id    = vf.id,
                numero      = 1,
                total       = 1,
                valor       = float(vf.valor_total_liquido or 0),
                vencimento  = vf.data_venda,
                recebido    = bool(vf.recebido),
                recebido_em = vf.recebido_em,
            ))
        if vendas_sem_parcela:
            print(f"[CDN] Backfill: {len(vendas_sem_parcela)} parcela(s) default criada(s) para vendas legadas.")

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[CDN] Erro no backfill financeiro: {e}")
    finally:
        db.close()

def create_app():
    FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder=FRONTEND_DIR,
        static_url_path="/static",
    )

    _PLACEHOLDER = "troque-esta-chave-por-um-valor-gerado-aleatoriamente"
    _raw_key = os.environ.get("CDN_SECRET_KEY", "").strip()
    if not _raw_key or _raw_key == _PLACEHOLDER:
        raise RuntimeError(
            "[CDN] CDN_SECRET_KEY não está configurada. "
            "Gere um valor seguro com: python -c \"import secrets; print(secrets.token_hex(32))\" "
            "e defina no arquivo .env antes de iniciar."
        )
    app.secret_key                = _raw_key
    app.permanent_session_lifetime = timedelta(hours=12)

    from flask_wtf.csrf import CSRFProtect
    CSRFProtect(app)

    Base.metadata.create_all(bind=engine)
    _migrate_db()
    _sync_admin()
    _backfill_financeiro()

    app.jinja_env.filters["brl"]     = _brl
    app.jinja_env.filters["localdt"] = _localdt

    @app.context_processor
    def _inject_usuario():

        from .blueprints.auth import get_usuario_atual, usuario_para_template
        return {"usuario_atual": usuario_para_template(get_usuario_atual())}

    @app.teardown_appcontext
    def close_db(error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    LANDING_DIR = os.path.join(FRONTEND_DIR, "landing")

    @app.route("/")
    @app.route("/landing/v3")
    @app.route("/landing/v3/")
    def landing_v3():
        return send_from_directory(os.path.join(LANDING_DIR, "v3"), "index.html")

    @app.route("/landing/v1")
    @app.route("/landing/v1/")
    def landing_v1():
        return send_from_directory(os.path.join(LANDING_DIR, "v1"), "index.html")

    @app.route("/landing/v2")
    @app.route("/landing/v2/")
    def landing_v2():
        return send_from_directory(os.path.join(LANDING_DIR, "v2"), "index.html")

    @app.route("/landing/<path:filename>")
    def landing(filename):
        return send_from_directory(LANDING_DIR, filename)

    @app.route("/api/catalogo")
    def api_catalogo():
        from flask import jsonify
        db = SessionLocal()
        try:
            produtos = (
                db.query(models.Produto)
                .filter(models.Produto.quantidade > 0, models.Produto.ativo.is_(True))
                .order_by(models.Produto.nome)
                .all()
            )
            return jsonify([
                {
                    "id":         p.id,
                    "nome":       p.nome,
                    "descricao":  p.descricao or "",
                    "preco":      p.preco_venda,
                    "imagem":     p.imagem_url or "",
                    "categoria":  p.categoria.nome if p.categoria else "",
                }
                for p in produtos
            ])
        finally:
            db.close()

    @app.route("/uploads/<path:filename>")
    def uploads(filename):

        return send_from_directory(os.path.abspath(UPLOADS_DIR), filename)

    from .blueprints.auth          import bp as auth_bp
    from .blueprints.dashboard     import bp as dashboard_bp
    from .blueprints.estoque       import bp as estoque_bp
    from .blueprints.parceiros     import bp as parceiros_bp
    from .blueprints.financeiro    import bp as financeiro_bp
    from .blueprints.configuracoes import bp as configuracoes_bp
    from .blueprints.caixa         import bp as caixa_bp
    from .blueprints.parceiro_area import bp as parceiro_area_bp
    from .blueprints.vendas        import bp as vendas_bp
    from .blueprints.despesas      import bp as despesas_bp
    from .blueprints.kpis          import bp as kpis_bp
    from .blueprints.historico     import bp as historico_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(estoque_bp)
    app.register_blueprint(parceiros_bp)
    app.register_blueprint(financeiro_bp)
    app.register_blueprint(configuracoes_bp)
    app.register_blueprint(caixa_bp)
    app.register_blueprint(parceiro_area_bp)
    app.register_blueprint(vendas_bp)
    app.register_blueprint(despesas_bp)
    app.register_blueprint(kpis_bp)
    app.register_blueprint(historico_bp)

    return app

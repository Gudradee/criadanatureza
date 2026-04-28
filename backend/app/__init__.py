import os
import secrets as _secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, g, send_from_directory

from .database import Base, engine, SessionLocal, get_db
from . import models  # garante que todos os models estão registrados antes do create_all

# ── Variáveis de ambiente ─────────────────────────────────────────────────────
# Carrega o arquivo .env que fica em backend/ (um nível acima de app/)
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")


# ── Filtro de template: formata valores como moeda brasileira ────────────────
def _brl(value):
    try:
        v = float(value)
        formatted = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {formatted}"
    except (TypeError, ValueError):
        return "R$ 0,00"


# ── Sincronização do usuário admin com o .env ────────────────────────────────
# Executado a cada inicialização — o .env é sempre a fonte de verdade para o admin.
# Se a senha mudar no .env, ela é atualizada automaticamente ao reiniciar.
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


# ── Migração de schema incremental ───────────────────────────────────────────
# create_all() só cria tabelas novas, não adiciona colunas em tabelas existentes.
# Este helper aplica ALTER TABLE manualmente para colunas adicionadas após o MVP.
def _migrate_db():
    from sqlalchemy import text, inspect
    db = SessionLocal()
    try:
        cols = [c["name"] for c in inspect(engine).get_columns("parceiros")]
        if "comissao_percentual" not in cols:
            db.execute(text("ALTER TABLE parceiros ADD COLUMN comissao_percentual REAL NOT NULL DEFAULT 0.0"))
            db.execute(text("UPDATE parceiros SET comissao_percentual = 0.02"))
            db.commit()
            print("[CDN] Migração: comissao_percentual adicionado (2% para parceiros existentes).")
    except Exception as e:
        db.rollback()
        print(f"[CDN] Erro na migração: {e}")
    finally:
        db.close()


# ── Backfill financeiro retroativo ───────────────────────────────────────────
# Garante que custos de produção e comissões de parceiros estejam registrados
# nas MovimentacoesFinanceiras. Idempotente: só cria registros ausentes.
# Corrige automaticamente comissões calculadas com a fórmula antiga (margem-based).
def _backfill_financeiro():
    from sqlalchemy import func, text
    from sqlalchemy.orm import joinedload
    db = SessionLocal()
    try:
        # ── 1. Custo de produção por produto ───────────────────────────────────
        for produto in db.query(models.Produto).filter(models.Produto.preco_custo > 0).all():
            total_entrada = db.query(func.sum(models.MovimentacaoEstoque.quantidade)).filter(
                models.MovimentacaoEstoque.produto_id == produto.id,
                models.MovimentacaoEstoque.tipo == "entrada",
            ).scalar() or 0

            if not total_entrada:
                continue

            custo_registrado = db.query(func.sum(models.MovimentacaoFinanceira.valor)).filter(
                models.MovimentacaoFinanceira.categoria == "Custo de Produção",
                models.MovimentacaoFinanceira.descricao.contains(produto.nome),
            ).scalar() or 0.0

            esperado = round(total_entrada * produto.preco_custo, 2)
            gap = round(esperado - custo_registrado, 2)
            if gap > 0.01:
                db.add(models.MovimentacaoFinanceira(
                    tipo="saida",
                    categoria="Custo de Produção",
                    descricao=f"Custo retroativo: {produto.nome} × {total_entrada} un.",
                    valor=gap,
                ))
                print(f"[CDN] Backfill custo produção: {produto.nome} = R${gap:.2f}")

        # ── 2. Comissões de vendas de parceiros (base = receita líquida) ───────
        # Modelo consignado: comissão = valor_total_liquido × comissao_percentual.
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

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[CDN] Erro no backfill financeiro: {e}")
    finally:
        db.close()


# ── Fábrica principal do app Flask ───────────────────────────────────────────
def create_app():
    FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

    # Instância Flask: templates em app/templates/, CSS servido de frontend/css/
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder=os.path.join(FRONTEND_DIR, "css"),
        static_url_path="/static/css",
    )

    # ── Configurações de sessão ───────────────────────────────────────────────
    app.secret_key                = os.environ.get("CDN_SECRET_KEY") or _secrets.token_hex(32)
    app.permanent_session_lifetime = timedelta(hours=12)

    # ── Inicialização do banco de dados ───────────────────────────────────────
    Base.metadata.create_all(bind=engine)   # cria tabelas que ainda não existem
    _migrate_db()                           # adiciona colunas novas em tabelas existentes
    _sync_admin()                           # garante que o admin do .env existe
    _backfill_financeiro()                  # preenche registros financeiros retroativos

    # ── Filtros e contexto global de templates ───────────────────────────────
    app.jinja_env.filters["brl"] = _brl

    @app.context_processor
    def _inject_usuario():
        # Injeta usuario_atual em todos os templates sem precisar passar manualmente
        from .blueprints.auth import get_usuario_atual, usuario_para_template
        return {"usuario_atual": usuario_para_template(get_usuario_atual())}

    # ── Fechamento de sessão DB ao fim de cada requisição ────────────────────
    @app.teardown_appcontext
    def close_db(error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    # ── Rotas de arquivos estáticos ───────────────────────────────────────────
    LANDING_DIR = os.path.join(FRONTEND_DIR, "landing")

    @app.route("/landing/<path:filename>")
    def landing(filename):
        return send_from_directory(LANDING_DIR, filename)

    @app.route("/uploads/<path:filename>")
    def uploads(filename):
        # Serve imagens de produtos enviadas via upload
        return send_from_directory(os.path.abspath(UPLOADS_DIR), filename)

    # ── Registro dos blueprints (módulos de rotas) ────────────────────────────
    from .blueprints.auth          import bp as auth_bp
    from .blueprints.dashboard     import bp as dashboard_bp
    from .blueprints.estoque       import bp as estoque_bp
    from .blueprints.parceiros     import bp as parceiros_bp
    from .blueprints.financeiro    import bp as financeiro_bp
    from .blueprints.configuracoes import bp as configuracoes_bp
    from .blueprints.loja          import bp as loja_bp
    from .blueprints.caixa         import bp as caixa_bp
    from .blueprints.parceiro_area import bp as parceiro_area_bp

    app.register_blueprint(auth_bp)           # /login, /logout
    app.register_blueprint(dashboard_bp)      # / (admin)
    app.register_blueprint(estoque_bp)        # /estoque
    app.register_blueprint(parceiros_bp)      # /parceiros
    app.register_blueprint(financeiro_bp)     # /financeiro
    app.register_blueprint(configuracoes_bp)  # /configuracoes
    app.register_blueprint(loja_bp)           # /loja (público)
    app.register_blueprint(caixa_bp)          # /caixa
    app.register_blueprint(parceiro_area_bp)  # /meu-painel, /meu-catalogo

    return app

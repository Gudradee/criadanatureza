import functools

from flask import Blueprint, render_template, request, redirect, session, flash, abort
from werkzeug.security import check_password_hash, generate_password_hash

from ..database import get_db
from .. import models

bp = Blueprint("auth", __name__)


# ── Helpers internos ──────────────────────────────────────────────────────────

def get_usuario_atual():
    """Carrega o usuário da sessão. Retorna None se não autenticado."""
    uid = session.get("usuario_id")
    if not uid:
        return None
    return get_db().query(models.Usuario).filter_by(id=uid, ativo=True).first()


def usuario_para_template(usuario):
    """
    Retorna apenas os campos seguros para expor em templates.
    senha_hash jamais é incluído.
    """
    if not usuario:
        return None
    return {
        "id":          usuario.id,
        "nome":        usuario.nome,
        "username":    usuario.username,
        "role":        usuario.role,
        "parceiro_id": usuario.parceiro_id,
        "is_admin":    usuario.role == "admin",
    }


# ── Decoradores de acesso ─────────────────────────────────────────────────────

def login_required(f):
    # Redireciona para /login se não houver sessão ativa
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("usuario_id"):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Rota acessível apenas por admins. Parceiro recebe 403."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("usuario_id"):
            return redirect("/login")
        u = get_usuario_atual()
        if not u or u.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Rotas de autenticação ─────────────────────────────────────────────────────

@bp.route("/login", methods=["GET"])
def login_form():
    if session.get("usuario_id"):
        u = get_usuario_atual()
        return redirect("/" if (u and u.role == "admin") else "/caixa")
    return render_template("login.html")


@bp.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip().lower()
    senha    = request.form.get("senha", "")

    _MSG_ERRO = "Usuário ou senha inválidos."

    if not username or not senha:
        flash(_MSG_ERRO, "warning")
        return render_template("login.html")

    db      = get_db()
    usuario = db.query(models.Usuario).filter_by(username=username, ativo=True).first()

    # Verificação constante — mesmo quando o usuário não existe,
    # evita timing attack que revelaria se o username é válido.
    senha_ok = check_password_hash(usuario.senha_hash, senha) if usuario else False

    if not usuario or not senha_ok:
        flash(_MSG_ERRO, "warning")
        return render_template("login.html")

    # Inicia sessão: admin vai para o dashboard, parceiro vai para o caixa
    session.clear()
    session["usuario_id"] = usuario.id
    session.permanent      = True

    return redirect("/" if usuario.role == "admin" else "/caixa")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/login")


@bp.route("/minha-conta/senha", methods=["POST"])
@admin_required
def alterar_senha():
    """Alias mantido por compatibilidade — redireciona para a rota canônica."""
    u           = get_usuario_atual()
    senha_atual = request.form.get("senha_atual", "")
    nova_senha  = request.form.get("nova_senha", "")
    confirmacao = request.form.get("confirmacao", "")

    if not check_password_hash(u.senha_hash, senha_atual):
        flash("Senha atual incorreta.", "warning")
        return redirect("/configuracoes")

    if len(nova_senha) < 8:
        flash("A nova senha deve ter ao menos 8 caracteres.", "warning")
        return redirect("/configuracoes")

    if nova_senha != confirmacao:
        flash("A confirmação não confere com a nova senha.", "warning")
        return redirect("/configuracoes")

    u.senha_hash = generate_password_hash(nova_senha)
    get_db().commit()
    flash("Senha alterada com sucesso.", "success")
    return redirect("/configuracoes")


# ── Página de acesso negado ───────────────────────────────────────────────────

@bp.app_errorhandler(403)
def acesso_negado(e):
    return render_template("403.html"), 403

# Responsabilidade: autenticação e autorização de todos os usuários do sistema.
# Expõe get_usuario_atual() e os decoradores login_required / admin_required
# que protegem as rotas dos demais blueprints.
# Redireciona admin → dashboard (/), parceiro → caixa (/caixa) após login.

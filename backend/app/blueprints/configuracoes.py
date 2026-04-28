import io

from flask import Blueprint, render_template, request, redirect, flash, send_file
from werkzeug.security import generate_password_hash

from ..database import get_db
from .. import models
from .auth import admin_required, login_required, get_usuario_atual

bp = Blueprint("configuracoes", __name__, url_prefix="/configuracoes")


@bp.route("")
@admin_required
def listar():
    db         = get_db()
    categorias = db.query(models.Categoria).order_by(models.Categoria.nome).all()
    parceiros  = db.query(models.Parceiro).order_by(models.Parceiro.nome).all()
    usuarios   = db.query(models.Usuario).order_by(models.Usuario.nome).all()
    return render_template("configuracoes.html",
        active_page = "config",
        categorias  = categorias,
        parceiros   = parceiros,
        usuarios    = usuarios,
    )


# ── Categorias ────────────────────────────────────────────────────────────────

@bp.route("/categorias", methods=["POST"])
@admin_required
def criar_categoria():
    db   = get_db()
    nome = request.form["nome"].strip()
    if db.query(models.Categoria).filter(models.Categoria.nome == nome).first():
        flash(f"Categoria '{nome}' já existe.", "warning")
        return redirect("/configuracoes")
    db.add(models.Categoria(nome=nome))
    db.commit()
    flash(f"Categoria '{nome}' criada com sucesso.", "success")
    return redirect("/configuracoes")


@bp.route("/categorias/<int:categoria_id>/deletar", methods=["POST"])
@admin_required
def deletar_categoria(categoria_id):
    db  = get_db()
    cat = db.query(models.Categoria).filter(models.Categoria.id == categoria_id).first()
    if cat:
        nome = cat.nome
        db.delete(cat)
        db.commit()
        flash(f"Categoria '{nome}' excluída.", "success")
    return redirect("/configuracoes")


# ── QR Code do catálogo geral ─────────────────────────────────────────────────

@bp.route("/qr-catalogo.png")
@admin_required
def qr_catalogo():
    try:
        import qrcode
    except ImportError:
        from flask import abort
        abort(500, "qrcode não instalado. Execute: pip install qrcode[pil]")

    url = f"{request.host_url}loja"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# ── QR Code do catálogo de um parceiro específico ────────────────────────────

@bp.route("/qr-parceiro/<int:parceiro_id>.png")
@admin_required
def qr_parceiro(parceiro_id):
    try:
        import qrcode
    except ImportError:
        from flask import abort
        abort(500, "qrcode não instalado.")

    url = f"{request.host_url}loja?p={parceiro_id}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# ── Gerenciamento de usuários ─────────────────────────────────────────────────

@bp.route("/usuarios/novo", methods=["POST"])
@admin_required
def criar_usuario():
    db       = get_db()
    username = request.form.get("username", "").strip().lower()
    nome     = request.form.get("nome", "").strip()
    senha    = request.form.get("senha", "")
    role     = request.form.get("role", "parceiro")
    parceiro_id = request.form.get("parceiro_id") or None
    if parceiro_id:
        parceiro_id = int(parceiro_id)

    if not username or not nome or not senha:
        flash("Preencha todos os campos obrigatórios.", "warning")
        return redirect("/configuracoes")

    if len(senha) < 8:
        flash("A senha deve ter ao menos 8 caracteres.", "warning")
        return redirect("/configuracoes")

    if db.query(models.Usuario).filter_by(username=username).first():
        flash(f"O usuário '{username}' já existe.", "warning")
        return redirect("/configuracoes")

    db.add(models.Usuario(
        nome        = nome,
        username    = username,
        senha_hash  = generate_password_hash(senha),
        role        = role,
        parceiro_id = parceiro_id,
        ativo       = True,
    ))
    db.commit()
    flash(f"Usuário '{username}' criado com sucesso.", "success")
    return redirect("/configuracoes")


@bp.route("/usuarios/<int:usuario_id>/desativar", methods=["POST"])
@admin_required
def desativar_usuario(usuario_id):
    db      = get_db()
    usuario = db.query(models.Usuario).filter_by(id=usuario_id).first()
    # Impede desativar o próprio admin logado
    atual = get_usuario_atual()
    if usuario and usuario.id != atual.id:
        usuario.ativo = False
        db.commit()
        flash(f"Usuário '{usuario.username}' desativado.", "success")
    else:
        flash("Não é possível desativar o próprio usuário.", "warning")
    return redirect("/configuracoes")


@bp.route("/usuarios/<int:usuario_id>/redefinir-senha", methods=["POST"])
@admin_required
def redefinir_senha(usuario_id):
    db       = get_db()
    usuario  = db.query(models.Usuario).filter_by(id=usuario_id).first()
    nova     = request.form.get("nova_senha", "")
    if not usuario:
        flash("Usuário não encontrado.", "warning")
        return redirect("/configuracoes")
    if len(nova) < 8:
        flash("A senha deve ter ao menos 8 caracteres.", "warning")
        return redirect("/configuracoes")
    usuario.senha_hash = generate_password_hash(nova)
    db.commit()
    flash(f"Senha de '{usuario.username}' redefinida com sucesso.", "success")
    return redirect("/configuracoes")


# ── Alterar senha — exclusivo para administradores ───────────────────────────

@bp.route("/minha-senha", methods=["POST"])
@admin_required
def minha_senha():
    from werkzeug.security import check_password_hash
    db          = get_db()
    u           = get_usuario_atual()
    senha_atual = request.form.get("senha_atual", "")
    nova        = request.form.get("nova_senha", "")
    confirmacao = request.form.get("confirmacao", "")

    if not check_password_hash(u.senha_hash, senha_atual):
        flash("Senha atual incorreta.", "warning")
        return redirect("/configuracoes" if u.role == "admin" else "/caixa")

    if len(nova) < 8:
        flash("A nova senha deve ter ao menos 8 caracteres.", "warning")
        return redirect("/configuracoes" if u.role == "admin" else "/caixa")

    if nova != confirmacao:
        flash("A confirmação não confere.", "warning")
        return redirect("/configuracoes" if u.role == "admin" else "/caixa")

    u.senha_hash = generate_password_hash(nova)
    db.commit()
    flash("Senha alterada com sucesso.", "success")
    return redirect("/configuracoes" if u.role == "admin" else "/caixa")

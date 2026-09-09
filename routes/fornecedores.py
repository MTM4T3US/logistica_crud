from flask import Blueprint, render_template, request, redirect, url_for, flash

from extensions import db
from models import Fornecedor, Cidade

fornecedores_bp = Blueprint(
    "fornecedores", __name__, template_folder="../templates/fornecedores"
)


def email_duplicado(email, for_codigo=None):
    query = Fornecedor.query.filter(Fornecedor.for_email == email)
    if for_codigo:
        query = query.filter(Fornecedor.for_codigo != for_codigo)
    return query.first() is not None


@fornecedores_bp.route("/")
def listar():
    fornecedores = Fornecedor.query.join(Cidade).order_by(Fornecedor.for_nome).all()
    return render_template("fornecedores/list.html", fornecedores=fornecedores)


@fornecedores_bp.route("/novo", methods=["GET", "POST"])
def criar():
    cidades = Cidade.query.order_by(Cidade.cid_nome).all()

    if request.method == "POST":
        email = request.form["for_email"].strip()

        if email and email_duplicado(email):
            flash("Já existe um fornecedor cadastrado com este e-mail.", "danger")
            return render_template("fornecedores/form.html", fornecedor=None, cidades=cidades)

        fornecedor = Fornecedor(
            for_nome=request.form["for_nome"].strip(),
            for_email=email,
            for_telefone=request.form["for_telefone"].strip(),
            cid_codigo=request.form["cid_codigo"],
        )
        db.session.add(fornecedor)
        db.session.commit()
        flash("Fornecedor cadastrado com sucesso!", "success")
        return redirect(url_for("fornecedores.listar"))

    return render_template("fornecedores/form.html", fornecedor=None, cidades=cidades)


@fornecedores_bp.route("/editar/<int:for_codigo>", methods=["GET", "POST"])
def editar(for_codigo):
    fornecedor = Fornecedor.query.get_or_404(for_codigo)
    cidades = Cidade.query.order_by(Cidade.cid_nome).all()

    if request.method == "POST":
        email = request.form["for_email"].strip()

        if email and email_duplicado(email, for_codigo):
            flash("Já existe um fornecedor cadastrado com este e-mail.", "danger")
            return render_template("fornecedores/form.html", fornecedor=fornecedor, cidades=cidades)

        fornecedor.for_nome = request.form["for_nome"].strip()
        fornecedor.for_email = email
        fornecedor.for_telefone = request.form["for_telefone"].strip()
        fornecedor.cid_codigo = request.form["cid_codigo"]
        db.session.commit()
        flash("Fornecedor atualizado com sucesso!", "success")
        return redirect(url_for("fornecedores.listar"))

    return render_template("fornecedores/form.html", fornecedor=fornecedor, cidades=cidades)


@fornecedores_bp.route("/excluir/<int:for_codigo>", methods=["POST"])
def excluir(for_codigo):
    fornecedor = Fornecedor.query.get_or_404(for_codigo)
    db.session.delete(fornecedor)
    db.session.commit()
    flash("Fornecedor excluído com sucesso!", "success")
    return redirect(url_for("fornecedores.listar"))

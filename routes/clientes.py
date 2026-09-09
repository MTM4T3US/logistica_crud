from flask import Blueprint, render_template, request, redirect, url_for, flash

from extensions import db
from models import Cliente, Cidade

clientes_bp = Blueprint("clientes", __name__, template_folder="../templates/clientes")


def email_duplicado(email, cli_codigo=None):
    query = Cliente.query.filter(Cliente.cli_email == email)
    if cli_codigo:
        query = query.filter(Cliente.cli_codigo != cli_codigo)
    return query.first() is not None


@clientes_bp.route("/")
def listar():
    clientes = Cliente.query.join(Cidade).order_by(Cliente.cli_nome).all()
    return render_template("clientes/list.html", clientes=clientes)


@clientes_bp.route("/novo", methods=["GET", "POST"])
def criar():
    cidades = Cidade.query.order_by(Cidade.cid_nome).all()

    if request.method == "POST":
        email = request.form["cli_email"].strip()

        if email and email_duplicado(email):
            flash("Já existe um cliente cadastrado com este e-mail.", "danger")
            return render_template("clientes/form.html", cliente=None, cidades=cidades)

        cliente = Cliente(
            cli_nome=request.form["cli_nome"].strip(),
            cli_email=email,
            cli_telefone=request.form["cli_telefone"].strip(),
            cid_codigo=request.form["cid_codigo"],
        )
        db.session.add(cliente)
        db.session.commit()
        flash("Cliente cadastrado com sucesso!", "success")
        return redirect(url_for("clientes.listar"))

    return render_template("clientes/form.html", cliente=None, cidades=cidades)


@clientes_bp.route("/editar/<int:cli_codigo>", methods=["GET", "POST"])
def editar(cli_codigo):
    cliente = Cliente.query.get_or_404(cli_codigo)
    cidades = Cidade.query.order_by(Cidade.cid_nome).all()

    if request.method == "POST":
        email = request.form["cli_email"].strip()

        if email and email_duplicado(email, cli_codigo):
            flash("Já existe um cliente cadastrado com este e-mail.", "danger")
            return render_template("clientes/form.html", cliente=cliente, cidades=cidades)

        cliente.cli_nome = request.form["cli_nome"].strip()
        cliente.cli_email = email
        cliente.cli_telefone = request.form["cli_telefone"].strip()
        cliente.cid_codigo = request.form["cid_codigo"]
        db.session.commit()
        flash("Cliente atualizado com sucesso!", "success")
        return redirect(url_for("clientes.listar"))

    return render_template("clientes/form.html", cliente=cliente, cidades=cidades)


@clientes_bp.route("/excluir/<int:cli_codigo>", methods=["POST"])
def excluir(cli_codigo):
    cliente = Cliente.query.get_or_404(cli_codigo)
    db.session.delete(cliente)
    db.session.commit()
    flash("Cliente excluído com sucesso!", "success")
    return redirect(url_for("clientes.listar"))

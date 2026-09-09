from flask import Blueprint, render_template, request, redirect, url_for, flash

from extensions import db
from models import Funcionario, Cidade, Departamento

funcionarios_bp = Blueprint(
    "funcionarios", __name__, template_folder="../templates/funcionarios"
)


def email_duplicado(email, fun_codigo=None):
    query = Funcionario.query.filter(Funcionario.fun_email == email)
    if fun_codigo:
        query = query.filter(Funcionario.fun_codigo != fun_codigo)
    return query.first() is not None


@funcionarios_bp.route("/")
def listar():
    # Consulta com INNER JOIN para exibir nome da cidade/departamento em vez do ID
    funcionarios = (
        Funcionario.query.join(Cidade).join(Departamento).order_by(Funcionario.fun_nome).all()
    )
    return render_template("funcionarios/list.html", funcionarios=funcionarios)


@funcionarios_bp.route("/novo", methods=["GET", "POST"])
def criar():
    cidades = Cidade.query.order_by(Cidade.cid_nome).all()
    departamentos = Departamento.query.order_by(Departamento.dep_nome).all()

    if request.method == "POST":
        email = request.form["fun_email"].strip()

        if email and email_duplicado(email):
            flash("Já existe um funcionário cadastrado com este e-mail.", "danger")
            return render_template(
                "funcionarios/form.html", funcionario=None, cidades=cidades, departamentos=departamentos
            )

        funcionario = Funcionario(
            fun_nome=request.form["fun_nome"].strip(),
            fun_email=email,
            fun_telefone=request.form["fun_telefone"].strip(),
            cid_codigo=request.form["cid_codigo"],
            dep_codigo=request.form["dep_codigo"],
        )
        db.session.add(funcionario)
        db.session.commit()
        flash("Funcionário cadastrado com sucesso!", "success")
        return redirect(url_for("funcionarios.listar"))

    return render_template(
        "funcionarios/form.html", funcionario=None, cidades=cidades, departamentos=departamentos
    )


@funcionarios_bp.route("/editar/<int:fun_codigo>", methods=["GET", "POST"])
def editar(fun_codigo):
    funcionario = Funcionario.query.get_or_404(fun_codigo)
    cidades = Cidade.query.order_by(Cidade.cid_nome).all()
    departamentos = Departamento.query.order_by(Departamento.dep_nome).all()

    if request.method == "POST":
        email = request.form["fun_email"].strip()

        if email and email_duplicado(email, fun_codigo):
            flash("Já existe um funcionário cadastrado com este e-mail.", "danger")
            return render_template(
                "funcionarios/form.html",
                funcionario=funcionario,
                cidades=cidades,
                departamentos=departamentos,
            )

        funcionario.fun_nome = request.form["fun_nome"].strip()
        funcionario.fun_email = email
        funcionario.fun_telefone = request.form["fun_telefone"].strip()
        funcionario.cid_codigo = request.form["cid_codigo"]
        funcionario.dep_codigo = request.form["dep_codigo"]
        db.session.commit()
        flash("Funcionário atualizado com sucesso!", "success")
        return redirect(url_for("funcionarios.listar"))

    return render_template(
        "funcionarios/form.html",
        funcionario=funcionario,
        cidades=cidades,
        departamentos=departamentos,
    )


@funcionarios_bp.route("/excluir/<int:fun_codigo>", methods=["POST"])
def excluir(fun_codigo):
    funcionario = Funcionario.query.get_or_404(fun_codigo)
    db.session.delete(funcionario)
    db.session.commit()
    flash("Funcionário excluído com sucesso!", "success")
    return redirect(url_for("funcionarios.listar"))

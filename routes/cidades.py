from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Cidade

cidades_bp = Blueprint("cidades", __name__, template_folder="../templates/cidades")


@cidades_bp.route("/")
def listar():
    cidades = Cidade.query.order_by(Cidade.cid_nome).all()
    return render_template("cidades/list.html", cidades=cidades)


@cidades_bp.route("/nova", methods=["GET", "POST"])
def criar():
    if request.method == "POST":
        cidade = Cidade(
            cid_nome=request.form["cid_nome"].strip(),
            cid_UF=request.form["cid_UF"].strip().upper(),
        )
        db.session.add(cidade)
        db.session.commit()
        flash("Cidade cadastrada com sucesso!", "success")
        return redirect(url_for("cidades.listar"))

    return render_template("cidades/form.html", cidade=None)


@cidades_bp.route("/editar/<int:cid_codigo>", methods=["GET", "POST"])
def editar(cid_codigo):
    cidade = Cidade.query.get_or_404(cid_codigo)

    if request.method == "POST":
        cidade.cid_nome = request.form["cid_nome"].strip()
        cidade.cid_UF = request.form["cid_UF"].strip().upper()
        db.session.commit()
        flash("Cidade atualizada com sucesso!", "success")
        return redirect(url_for("cidades.listar"))

    return render_template("cidades/form.html", cidade=cidade)


@cidades_bp.route("/excluir/<int:cid_codigo>", methods=["POST"])
def excluir(cid_codigo):
    cidade = Cidade.query.get_or_404(cid_codigo)

    # Verificação prévia de integridade referencial (Regra de Negócio)
    vinculos = len(cidade.funcionarios) + len(cidade.clientes) + len(cidade.fornecedores)
    if vinculos > 0:
        flash(
            f"Não é possível excluir '{cidade.cid_nome}': existem {vinculos} "
            "registro(s) (funcionários, clientes ou fornecedores) vinculados a esta cidade.",
            "danger",
        )
        return redirect(url_for("cidades.listar"))

    try:
        db.session.delete(cidade)
        db.session.commit()
        flash("Cidade excluída com sucesso!", "success")
    except IntegrityError:
        db.session.rollback()
        flash(
            "Não é possível excluir esta cidade: existem registros vinculados "
            "a ela (violação de integridade referencial).",
            "danger",
        )

    return redirect(url_for("cidades.listar"))

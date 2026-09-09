from flask import Blueprint, render_template

from models import Funcionario, Cliente, Fornecedor, Cidade, Departamento

relatorios_bp = Blueprint("relatorios", __name__, template_folder="../templates/relatorios")


@relatorios_bp.route("/")
def index():
    # As três consultas abaixo usam INNER JOIN para exibir nomes
    # (cidade/departamento) em vez de apenas o código (FK), conforme exigido.
    funcionarios = (
        Funcionario.query.join(Cidade, Funcionario.cid_codigo == Cidade.cid_codigo)
        .join(Departamento, Funcionario.dep_codigo == Departamento.dep_codigo)
        .add_columns(
            Funcionario.fun_codigo,
            Funcionario.fun_nome,
            Funcionario.fun_email,
            Cidade.cid_nome,
            Cidade.cid_UF,
            Departamento.dep_nome,
        )
        .order_by(Funcionario.fun_nome)
        .all()
    )

    clientes = (
        Cliente.query.join(Cidade, Cliente.cid_codigo == Cidade.cid_codigo)
        .add_columns(
            Cliente.cli_codigo,
            Cliente.cli_nome,
            Cliente.cli_email,
            Cidade.cid_nome,
            Cidade.cid_UF,
        )
        .order_by(Cliente.cli_nome)
        .all()
    )

    fornecedores = (
        Fornecedor.query.join(Cidade, Fornecedor.cid_codigo == Cidade.cid_codigo)
        .add_columns(
            Fornecedor.for_codigo,
            Fornecedor.for_nome,
            Fornecedor.for_email,
            Cidade.cid_nome,
            Cidade.cid_UF,
        )
        .order_by(Fornecedor.for_nome)
        .all()
    )

    return render_template(
        "relatorios/index.html",
        funcionarios=funcionarios,
        clientes=clientes,
        fornecedores=fornecedores,
    )

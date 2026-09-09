from extensions import db


class Cidade(db.Model):
    __tablename__ = "tbl_cidades"

    cid_codigo = db.Column(db.Integer, primary_key=True)
    cid_nome = db.Column(db.String(100), nullable=False)
    cid_UF = db.Column(db.String(2), nullable=False)

    funcionarios = db.relationship("Funcionario", backref="cidade", lazy=True)
    clientes = db.relationship("Cliente", backref="cidade", lazy=True)
    fornecedores = db.relationship("Fornecedor", backref="cidade", lazy=True)

    def __repr__(self):
        return f"{self.cid_nome}/{self.cid_UF}"


class Departamento(db.Model):
    __tablename__ = "tbl_departamentos"

    dep_codigo = db.Column(db.Integer, primary_key=True)
    dep_nome = db.Column(db.String(100), nullable=False)
    dep_telefone = db.Column(db.String(15))
    dep_email = db.Column(db.String(100), unique=True)

    funcionarios = db.relationship("Funcionario", backref="departamento", lazy=True)


class Funcionario(db.Model):
    __tablename__ = "tbl_funcionarios"

    fun_codigo = db.Column(db.Integer, primary_key=True)
    fun_nome = db.Column(db.String(100), nullable=False)
    fun_email = db.Column(db.String(100), unique=True)
    fun_telefone = db.Column(db.String(15))

    cid_codigo = db.Column(db.Integer, db.ForeignKey("tbl_cidades.cid_codigo"))
    dep_codigo = db.Column(db.Integer, db.ForeignKey("tbl_departamentos.dep_codigo"))


class Cliente(db.Model):
    __tablename__ = "tbl_clientes"

    cli_codigo = db.Column(db.Integer, primary_key=True)
    cli_nome = db.Column(db.String(100), nullable=False)
    cli_email = db.Column(db.String(100), unique=True)
    cli_telefone = db.Column(db.String(15))

    cid_codigo = db.Column(db.Integer, db.ForeignKey("tbl_cidades.cid_codigo"))


class Fornecedor(db.Model):
    __tablename__ = "tbl_fornecedores"

    for_codigo = db.Column(db.Integer, primary_key=True)
    for_nome = db.Column(db.String(100), nullable=False)
    for_telefone = db.Column(db.String(100))
    for_email = db.Column(db.String(100), unique=True)

    cid_codigo = db.Column(db.Integer, db.ForeignKey("tbl_cidades.cid_codigo"))

# Sistema de Logística — CRUD Web (SENAI/GO)

Aplicação Web (Flask + MySQL) para gerenciar as entidades do banco `db_logistica`:
Cidades, Departamentos, Funcionários, Clientes e Fornecedores.

## 1. Sobre o script SQL

O arquivo `database/logistica.sql` fornecido pelo professor **já usa o prefixo
`tbl_` de forma consistente** em `CREATE TABLE`, `FOREIGN KEY` e `INSERT` — não
foi necessário corrigir inconsistência de nomes. Foram adicionadas apenas
restrições `UNIQUE` nos campos de e-mail, para viabilizar a regra de negócio
de não permitir cadastros duplicados (o schema original não possui campos de
CPF/CNPJ, por isso a validação de duplicidade foi aplicada ao e-mail, que é o
identificador único mais próximo disso em cada entidade).

## 2. Estrutura do projeto

```
logistica_crud/
├── app.py                 # Ponto de entrada da aplicação (application factory)
├── config.py               # Configurações (lê variáveis do .env)
├── extensions.py           # Instância do SQLAlchemy
├── models.py                # Mapeamento das tabelas (ORM)
├── requirements.txt
├── database/logistica.sql   # Script de criação e carga do banco
├── routes/                  # Blueprints (rotas) por entidade
│   ├── cidades.py
│   ├── departamentos.py
│   ├── funcionarios.py      # Trata a dupla FK (cidade + departamento)
│   ├── clientes.py
│   ├── fornecedores.py
│   └── relatorios.py        # Consultas com INNER JOIN
├── templates/                # HTML (Jinja2 + Bootstrap 5, responsivo)
└── static/css/style.css
```

## 3. Pré-requisitos

- Python 3.10+
- MySQL Server 8+ em execução localmente (ou acessível pela rede)
- Git

## 4. Passo a passo — Criação do banco de dados

1. Acesse o cliente MySQL:
   ```bash
   mysql -u root -p
   ```
2. Execute o script de criação:
   ```bash
   source database/logistica.sql;
   ```
   ou, pelo terminal (fora do MySQL):
   ```bash
   mysql -u root -p < database/logistica.sql
   ```
   Isso cria o banco `db_logistica`, as 5 tabelas e insere os dados iniciais.

## 5. Instalação das dependências

```bash
# clonar o repositório
git clone <URL_DO_SEU_REPOSITORIO>
cd logistica_crud

# criar e ativar ambiente virtual
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows

# instalar dependências
pip install -r requirements.txt
```

## 6. Configuração das variáveis de ambiente

Copie o arquivo de exemplo e ajuste usuário/senha do seu MySQL:

```bash
cp .env.example .env
```

Edite `.env`:
```
SECRET_KEY=troque-esta-chave
DB_USER=root
DB_PASSWORD=sua_senha
DB_HOST=localhost
DB_PORT=3306
DB_NAME=db_logistica
```

## 7. Rodando o servidor local

```bash
python app.py
```

A aplicação sobe em `http://127.0.0.1:5000`.

## 8. Funcionalidades implementadas

- **CRUD completo** (Create, Read, Update, Delete) para as 5 entidades.
- **Telas responsivas** (Bootstrap 5) com formulários de cadastro/edição e
  tabelas de listagem.
- **Funcionários** com dupla chave estrangeira (cidade e departamento),
  exibidas via `<select>` no formulário.
- **Validação de duplicidade** de e-mail antes de inserir/atualizar
  (regra de negócio equivalente à checagem de CPF/CNPJ pedida no roteiro,
  adaptada ao schema fornecido).
- **Tratamento de integridade referencial**: ao tentar excluir uma cidade (ou
  departamento) com registros vinculados, o sistema impede a exclusão e
  mostra uma mensagem explicando o motivo, em vez de deixar o erro do banco
  estourar (`routes/cidades.py` e `routes/departamentos.py`).
- **Relatório com INNER JOIN** (`/relatorios`): três listagens que exibem o
  nome da cidade/departamento em vez do código (FK) — funcionários,
  clientes e fornecedores agrupados por cidade.

## 9. Próximos passos sugeridos (opcional)

- Adicionar autenticação de usuários.
- Exportar relatórios em PDF/Excel.
- Paginação nas listagens para bases maiores.

-- Banco de dados: Sistema de Logística
-- Observação: o script original já usa o prefixo tbl_ de forma consistente
-- em CREATE TABLE, FOREIGN KEY e INSERT (não há a inconsistência de nomes
-- citada no roteiro da atividade). Foram adicionadas apenas restrições
-- UNIQUE nos campos de e-mail para suportar a regra de negócio de não
-- permitir cadastros duplicados.

CREATE DATABASE IF NOT EXISTS db_logistica;
USE db_logistica;

DROP TABLE IF EXISTS tbl_funcionarios;
DROP TABLE IF EXISTS tbl_clientes;
DROP TABLE IF EXISTS tbl_fornecedores;
DROP TABLE IF EXISTS tbl_departamentos;
DROP TABLE IF EXISTS tbl_cidades;

CREATE TABLE tbl_departamentos(
    dep_codigo INT AUTO_INCREMENT PRIMARY KEY,
    dep_nome VARCHAR(100) NOT NULL,
    dep_telefone VARCHAR(15),
    dep_email VARCHAR(100) UNIQUE
);

CREATE TABLE tbl_cidades(
    cid_codigo INT AUTO_INCREMENT PRIMARY KEY,
    cid_nome VARCHAR(100) NOT NULL,
    cid_UF VARCHAR(2) NOT NULL
);

CREATE TABLE tbl_funcionarios(
    fun_codigo INT AUTO_INCREMENT PRIMARY KEY,
    fun_nome VARCHAR(100) NOT NULL,
    fun_email VARCHAR(100) UNIQUE,
    fun_telefone VARCHAR(15),
    cid_codigo INT,
    CONSTRAINT fk_funcionarios_cidades FOREIGN KEY (cid_codigo)
        REFERENCES tbl_cidades(cid_codigo),
    dep_codigo INT,
    CONSTRAINT fk_funcionarios_departamentos FOREIGN KEY (dep_codigo)
        REFERENCES tbl_departamentos(dep_codigo)
);

CREATE TABLE tbl_clientes(
    cli_codigo INT AUTO_INCREMENT PRIMARY KEY,
    cli_nome VARCHAR(100) NOT NULL,
    cli_email VARCHAR(100) UNIQUE,
    cli_telefone VARCHAR(15),
    cid_codigo INT,
    CONSTRAINT fk_clientes_cidades FOREIGN KEY (cid_codigo)
        REFERENCES tbl_cidades(cid_codigo)
);

CREATE TABLE tbl_fornecedores(
    for_codigo INT AUTO_INCREMENT PRIMARY KEY,
    for_nome VARCHAR(100) NOT NULL,
    for_telefone VARCHAR(100),
    for_email VARCHAR(100) UNIQUE,
    cid_codigo INT,
    CONSTRAINT fk_fornecedores_cidades FOREIGN KEY (cid_codigo)
        REFERENCES tbl_cidades(cid_codigo)
);

INSERT INTO tbl_cidades (cid_nome, cid_UF) VALUES
('Goiânia', 'GO'),
('Itumbiara', 'GO'),
('Uberlândia', 'MG'),
('Brasília', 'DF'),
('São Paulo', 'SP'),
('Belo Horizonte', 'MG'),
('Anápolis', 'GO'),
('Catalão', 'GO');

INSERT INTO tbl_departamentos
(dep_nome, dep_telefone, dep_email) VALUES
('Administrativo', '(64) 3431-2847', 'administrativo@logistica.com'),
('Financeiro', '(64) 3432-7195', 'financeiro@logistica.com'),
('Recursos Humanos', '(62) 3221-5836', 'rh@logistica.com'),
('Tecnologia da Informação', '(62) 3098-4621', 'ti@logistica.com'),
('Logística', '(34) 3234-8175', 'logistica@logistica.com');

INSERT INTO tbl_funcionarios
(fun_nome, fun_email, fun_telefone, cid_codigo, dep_codigo) VALUES
('Carlos Henrique', 'carlos@logistica.com', '(64) 99234-1876', 1, 1),
('Mariana Oliveira', 'mariana@logistica.com', '(62) 99817-4523', 7, 2),
('João Pedro', 'joao@logistica.com', '(34) 99128-7364', 3, 5),
('Ana Beatriz', 'ana@logistica.com', '(61) 99642-8157', 4, 3),
('Lucas Martins', 'lucas@logistica.com', '(11) 98731-2645', 5, 4),
('Gabriel Souza', 'gabriel@logistica.com', '(64) 99385-4217', 2, 5),
('Juliana Costa', 'juliana@logistica.com', '(62) 99472-6381', 1, 3);

INSERT INTO tbl_clientes
(cli_nome, cli_email, cli_telefone, cid_codigo) VALUES
('Pedro Almeida', 'pedro@gmail.com', '(64) 99124-5738', 1),
('Beatriz Lima', 'beatriz@gmail.com', '(64) 99285-1467', 2),
('Fernando Rocha', 'fernando@gmail.com', '(34) 99831-7254', 3),
('Larissa Mendes', 'larissa@gmail.com', '(61) 99572-4816', 4),
('Gustavo Pereira', 'gustavo@gmail.com', '(11) 98764-2135', 5),
('Camila Ferreira', 'camila@gmail.com', '(31) 99173-6852', 6),
('Thiago Alves', 'thiago@gmail.com', '(62) 99428-7315', 7);

INSERT INTO tbl_fornecedores
(for_nome, for_telefone, for_email, cid_codigo) VALUES
('Tech Solutions', '(62) 99821-4736', 'contato@techsolutions.com', 1),
('Distribuidora Central', '(64) 99317-5824', 'contato@distribuidoracentral.com', 2),
('Mega Transportes', '(34) 99146-8273', 'contato@megatransportes.com', 3),
('Brasília Suprimentos', '(61) 99632-7158', 'contato@bsuprimentos.com', 4),
('SP Equipamentos', '(11) 98842-6317', 'contato@spequipamentos.com', 5);

-- Noite 1 · Ingestão bronze
--
-- A bronze preserva o dado como veio. Nada de limpeza aqui: se der problema
-- depois, a gente precisa poder voltar na origem e comparar.
--
-- O poder do read_files: o MESMO comando lê CSV, planilha Excel, JSON e XML.
-- Ninguém converte nada antes. A Vértice tem projetos em três ferramentas:
--   · Excel       20 planilhas, uma por projeto, cada gerente do seu jeito
--   · ClickUp     25 exports da API em JSON (tarefas dentro de uma lista)
--   · MS Project  15 arquivos XML (uma <Task> por tarefa, com fases e baseline)
--
-- Duas coisas que valem explicar:
--   inferColumnTypes => false  ->  TUDO entra como texto (CSV e Excel). Se o
--                                  Databricks adivinhasse o tipo, ele erraria as
--                                  datas que vêm em dois formatos e o valor com
--                                  vírgula decimal. A sujeira sumiria antes de a
--                                  gente ver. No JSON e no XML deixamos inferir:
--                                  é o que mantém a estrutura (lista dentro de lista).
--   EXCEPT (_rescued_data)     ->  o read_files cria sozinho a coluna _rescued_data,
--                                  a "rede de segurança": o que não couber nas colunas
--                                  (uma coluna a mais numa linha, por exemplo) cai ali
--                                  em vez de sumir. Nos nossos arquivos ela vem vazia,
--                                  então a gente tira da tabela.

-- São 9 tabelas, uma pergunta do dono por trás de cada uma:
--   projetos, status_semanal                          o cadastro do PMO e o farol de toda sexta
--   excel_tarefas, clickup_tarefas, msproject_tarefas as 3 ferramentas (pergunta 1: quem atrasa)
--   custos                                            o financeiro (pergunta 2: quanto custa)
--   colaboradores, apontamentos                       RH e timesheet (pergunta 3: gente parada)
--   entregas_fornecedor                               compras (a consultoria que atrasa)
--
-- Antes de rodar, os arquivos precisam estar no volume (passos 3 e 4 do README):
--   /Volumes/lakehouse_vertice/bronze/raw/<sistema>/...
--
-- Rode com:
--   python3 scripts/run_sql.py setup/01-ingestao-bronze.sql --profile SEU-PERFIL

-- ---------- pmo ----------
-- projetos: o cadastro do PMO: cliente, valor, prazo e EM QUAL FERRAMENTA o projeto vive
CREATE OR REPLACE TABLE lakehouse_vertice.bronze.projetos AS
SELECT * EXCEPT (_rescued_data)
FROM read_files('/Volumes/lakehouse_vertice/bronze/raw/pmo/projetos.csv',
                format => 'csv', header => true, inferColumnTypes => false);
-- status_semanal: toda sexta o gerente publica avanço, farol e bloqueios (texto livre)
CREATE OR REPLACE TABLE lakehouse_vertice.bronze.status_semanal AS
SELECT * EXCEPT (_rescued_data)
FROM read_files('/Volumes/lakehouse_vertice/bronze/raw/pmo/status_semanal.csv',
                format => 'csv', header => true, inferColumnTypes => false);

-- ---------- as três ferramentas de projeto ----------
-- excel_tarefas: as 20 planilhas de uma vez (é só apontar para a pasta).
-- A planilha tem cabeçalho escrito por gente ("% Concluído", "Início previsto"),
-- e tabela não aceita espaço no nome da coluna: renomeamos, sem mexer no valor.
CREATE OR REPLACE TABLE lakehouse_vertice.bronze.excel_tarefas AS
SELECT `ID`               AS id,
       `Fase`             AS fase,
       `Tarefa`           AS tarefa,
       `Responsável`      AS responsavel,
       `Início previsto`  AS inicio_previsto,
       `Término previsto` AS termino_previsto,
       `Início real`      AS inicio_real,
       `Término real`     AS termino_real,
       `% Concluído`      AS pct_concluido,
       `Horas previstas`  AS horas_previstas,
       url_decode(_metadata.file_name) AS arquivo
FROM read_files('/Volumes/lakehouse_vertice/bronze/raw/excel/',
                format => 'excel', headerRows => 1, inferColumnTypes => false);

-- clickup_tarefas: cada arquivo é UMA lista (um projeto) com as tarefas dentro.
-- explode() abre a lista: uma linha por tarefa. O resto fica como veio:
-- status é uma estrutura, datas são milissegundos, campos personalizados são uma lista.
CREATE OR REPLACE TABLE lakehouse_vertice.bronze.clickup_tarefas AS
SELECT list.id   AS list_id,
       list.name AS list_name,
       t.*,
       url_decode(_metadata.file_name) AS arquivo
FROM (
    SELECT list, explode(tasks) AS t, _metadata
    FROM read_files('/Volumes/lakehouse_vertice/bronze/raw/clickup/',
                    format => 'json', multiLine => true)
);

-- msproject_tarefas: cada <Task> do XML vira uma linha. Inclui as tarefas-resumo
-- (as fases e o projeto inteiro), que somam as horas das tarefas de baixo.
CREATE OR REPLACE TABLE lakehouse_vertice.bronze.msproject_tarefas AS
SELECT * EXCEPT (_rescued_data),
       url_decode(_metadata.file_name) AS arquivo
FROM read_files('/Volumes/lakehouse_vertice/bronze/raw/msproject/',
                format => 'xml', rowTag => 'Task');

-- ---------- rh e timesheet ----------
-- colaboradores: as 520 pessoas: papel, senioridade, custo/hora, admissão e desligamento
CREATE OR REPLACE TABLE lakehouse_vertice.bronze.colaboradores AS
SELECT * EXCEPT (_rescued_data)
FROM read_files('/Volumes/lakehouse_vertice/bronze/raw/rh/colaboradores.csv',
                format => 'csv', header => true, inferColumnTypes => false);
-- apontamentos: horas disponíveis x horas apontadas, por pessoa, projeto e semana
CREATE OR REPLACE TABLE lakehouse_vertice.bronze.apontamentos AS
SELECT * EXCEPT (_rescued_data)
FROM read_files('/Volumes/lakehouse_vertice/bronze/raw/timesheet/apontamentos.csv',
                format => 'csv', header => true, inferColumnTypes => false);

-- ---------- financeiro ----------
-- custos: cada lançamento de custo real (folha alocada, consultoria, cloud, licenças...)
CREATE OR REPLACE TABLE lakehouse_vertice.bronze.custos AS
SELECT * EXCEPT (_rescued_data)
FROM read_files('/Volumes/lakehouse_vertice/bronze/raw/financeiro/custos.csv',
                format => 'csv', header => true, inferColumnTypes => false);

-- ---------- compras ----------
-- entregas_fornecedor: o que cada consultoria prometeu entregar, e quando entregou
CREATE OR REPLACE TABLE lakehouse_vertice.bronze.entregas_fornecedor AS
SELECT * EXCEPT (_rescued_data)
FROM read_files('/Volumes/lakehouse_vertice/bronze/raw/compras/entregas_fornecedor.csv',
                format => 'csv', header => true, inferColumnTypes => false);

-- ---------- conferência ----------
-- 9 tabelas. Se alguma vier com 0 linhas, o arquivo não subiu para o volume.
SELECT 'projetos' AS tabela, COUNT(*) AS linhas FROM lakehouse_vertice.bronze.projetos
UNION ALL SELECT 'status_semanal', COUNT(*) FROM lakehouse_vertice.bronze.status_semanal
UNION ALL SELECT 'excel_tarefas', COUNT(*) FROM lakehouse_vertice.bronze.excel_tarefas
UNION ALL SELECT 'clickup_tarefas', COUNT(*) FROM lakehouse_vertice.bronze.clickup_tarefas
UNION ALL SELECT 'msproject_tarefas', COUNT(*) FROM lakehouse_vertice.bronze.msproject_tarefas
UNION ALL SELECT 'colaboradores', COUNT(*) FROM lakehouse_vertice.bronze.colaboradores
UNION ALL SELECT 'apontamentos', COUNT(*) FROM lakehouse_vertice.bronze.apontamentos
UNION ALL SELECT 'custos', COUNT(*) FROM lakehouse_vertice.bronze.custos
UNION ALL SELECT 'entregas_fornecedor', COUNT(*) FROM lakehouse_vertice.bronze.entregas_fornecedor
ORDER BY linhas DESC;

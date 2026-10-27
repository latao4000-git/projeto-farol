-- Conferência da bronze: a primeira tarefa do job vertice_farol.
--
-- Antes de transformar qualquer coisa, conferimos se as 9 tabelas da bronze
-- (noite 1) chegaram inteiras. O número esperado de cada uma vem do gerador
-- de dados com seed 42. Se alguma tabela divergir, o job PARA aqui, e o
-- dashboard fica com o dado da semana passada em vez de meio dado.
--
-- Este arquivo roda como sql_task: cada comando termina em ponto e vírgula.


-- 1) A conferência: uma linha por tabela, com o esperado e o obtido.
WITH esperado AS (
  SELECT * FROM VALUES
    ('projetos',               60),
    ('status_semanal',       3911),
    ('excel_tarefas',        1663),
    ('clickup_tarefas',      2119),
    ('msproject_tarefas',    1260),
    ('colaboradores',         523),
    ('apontamentos',        30883),
    ('custos',              23640),
    ('entregas_fornecedor',   640)
  AS t(tabela, esperado)
),
obtido AS (
  SELECT 'projetos'            AS tabela, count(*) AS obtido FROM lakehouse_vertice.bronze.projetos
  UNION ALL SELECT 'status_semanal',      count(*) FROM lakehouse_vertice.bronze.status_semanal
  UNION ALL SELECT 'excel_tarefas',       count(*) FROM lakehouse_vertice.bronze.excel_tarefas
  UNION ALL SELECT 'clickup_tarefas',     count(*) FROM lakehouse_vertice.bronze.clickup_tarefas
  UNION ALL SELECT 'msproject_tarefas',   count(*) FROM lakehouse_vertice.bronze.msproject_tarefas
  UNION ALL SELECT 'colaboradores',       count(*) FROM lakehouse_vertice.bronze.colaboradores
  UNION ALL SELECT 'apontamentos',        count(*) FROM lakehouse_vertice.bronze.apontamentos
  UNION ALL SELECT 'custos',              count(*) FROM lakehouse_vertice.bronze.custos
  UNION ALL SELECT 'entregas_fornecedor', count(*) FROM lakehouse_vertice.bronze.entregas_fornecedor
)
SELECT
  e.tabela,
  e.esperado,
  o.obtido,
  CASE WHEN e.esperado = o.obtido THEN 'ok' ELSE 'DIVERGE' END AS situacao
FROM esperado e
JOIN obtido o USING (tabela)
ORDER BY e.tabela;


-- 2) O dente da conferência: se alguma tabela divergiu, raise_error() falha
--    a tarefa com uma mensagem que diz qual tabela e o que fazer.
WITH esperado AS (
  SELECT * FROM VALUES
    ('projetos',               60),
    ('status_semanal',       3911),
    ('excel_tarefas',        1663),
    ('clickup_tarefas',      2119),
    ('msproject_tarefas',    1260),
    ('colaboradores',         523),
    ('apontamentos',        30883),
    ('custos',              23640),
    ('entregas_fornecedor',   640)
  AS t(tabela, esperado)
),
obtido AS (
  SELECT 'projetos'            AS tabela, count(*) AS obtido FROM lakehouse_vertice.bronze.projetos
  UNION ALL SELECT 'status_semanal',      count(*) FROM lakehouse_vertice.bronze.status_semanal
  UNION ALL SELECT 'excel_tarefas',       count(*) FROM lakehouse_vertice.bronze.excel_tarefas
  UNION ALL SELECT 'clickup_tarefas',     count(*) FROM lakehouse_vertice.bronze.clickup_tarefas
  UNION ALL SELECT 'msproject_tarefas',   count(*) FROM lakehouse_vertice.bronze.msproject_tarefas
  UNION ALL SELECT 'colaboradores',       count(*) FROM lakehouse_vertice.bronze.colaboradores
  UNION ALL SELECT 'apontamentos',        count(*) FROM lakehouse_vertice.bronze.apontamentos
  UNION ALL SELECT 'custos',              count(*) FROM lakehouse_vertice.bronze.custos
  UNION ALL SELECT 'entregas_fornecedor', count(*) FROM lakehouse_vertice.bronze.entregas_fornecedor
),
divergencias AS (
  SELECT e.tabela || ' (esperado ' || e.esperado || ', obtido ' || o.obtido || ')' AS descricao
  FROM esperado e
  JOIN obtido o USING (tabela)
  WHERE e.esperado <> o.obtido
)
SELECT
  CASE
    WHEN count(*) > 0 THEN raise_error(
      'Bronze incompleta: ' || array_join(collect_list(descricao), ', ')
      || '. Rode de novo o 00-carregar-dados e o 01-ingestao-bronze da noite 1 e depois rode o job outra vez.'
    )
    ELSE 'bronze conferida: as 9 tabelas batem com o esperado'
  END AS resultado
FROM divergencias;

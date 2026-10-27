-- silver.projetos: o cadastro do PMO.
--
-- É mais que um cadastro: é o DE-PARA da integração. A coluna
-- codigo_ferramenta diz em qual planilha, lista do ClickUp ou arquivo do
-- MS Project mora cada projeto. A silver.tarefas usa esta tabela para
-- saber de quem é cada tarefa.
--
-- Sujeiras tratadas (seção 3 do CLAUDE.md):
--   #1 data_inicio em yyyy-MM-dd e dd/MM/yyyy (24 de 60)
--   #2 ferramenta escrita de 8 jeitos
--   #3 codigo_ferramenta vazio (2 projetos)

CREATE OR REFRESH MATERIALIZED VIEW projetos (
  -- o contrato: se amanhã alguém digitar "Planilha Google", o pipeline PARA
  CONSTRAINT data_inicio_valida EXPECT (data_inicio IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT ferramenta_conhecida EXPECT (ferramenta IN ('excel', 'clickup', 'msproject')) ON VIOLATION FAIL UPDATE
)
COMMENT 'Cadastro dos 60 projetos da Vértice (PMO): cliente, segmento, valores, datas, gerente e em qual ferramenta (excel, clickup ou msproject) o projeto é controlado. codigo_ferramenta é o de-para com as tarefas.'
AS
SELECT
  projeto_id,
  nome_projeto,
  cliente,
  segmento,
  tipo_projeto,

  -- 8 grafias viram 3 valores
  CASE
    WHEN lower(ferramenta) LIKE '%excel%' OR lower(ferramenta) LIKE '%planilha%' THEN 'excel'
    WHEN lower(ferramenta) LIKE '%click%'                                        THEN 'clickup'
    WHEN lower(ferramenta) LIKE '%project%'                                      THEN 'msproject'
  END                                                      AS ferramenta,
  ferramenta                                               AS ferramenta_como_veio,
  nullif(trim(codigo_ferramenta), '')                      AS codigo_ferramenta,

  CAST(valor_contrato  AS DECIMAL(18,2))                   AS valor_contrato,
  CAST(orcamento_custo AS DECIMAL(18,2))                   AS orcamento_custo,

  -- a data vem de dois jeitos: tenta um, depois o outro
  coalesce(
    try_to_date(data_inicio, 'yyyy-MM-dd'),
    try_to_date(data_inicio, 'dd/MM/yyyy')
  )                                                        AS data_inicio,
  to_date(data_fim_baseline, 'yyyy-MM-dd')                 AS data_fim_baseline,

  status,
  gerente_projeto
FROM lakehouse_vertice.bronze.projetos;

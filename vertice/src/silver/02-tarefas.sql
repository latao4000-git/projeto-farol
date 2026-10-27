-- silver.tarefas: AS TRÊS FERRAMENTAS VIRAM UMA.
--
-- A integração é um contrato de colunas: cada ferramenta vira uma visão
-- temporária com as MESMAS 13 colunas, e as três são empilhadas (UNION ALL).
-- Se amanhã aparecer uma quarta ferramenta, é só mais uma visão.
--
--   projeto_id, ferramenta, id_na_ferramenta, fase, tarefa, responsavel,
--   inicio_baseline, fim_baseline, inicio_real, fim_real,
--   pct_como_veio, horas, status_na_ferramenta
--
-- O de-para (qual arquivo ou lista é de qual projeto) vem da silver.projetos.
-- Excel e MS Project não têm status: ele é derivado do % (100 = concluida,
-- 0 = a_fazer, o resto = em_andamento), no mesmo vocabulário do ClickUp.


-- ---------------------------------------------------------------------------
-- 1) Excel: 20 planilhas. Tudo veio como texto.
--    Sujeiras #3, #4, #5, #6 e #7.
-- ---------------------------------------------------------------------------
CREATE TEMPORARY VIEW tarefas_excel AS
WITH limpo AS (
  SELECT
    e.*,
    -- #5: '45%' e '10,5%' já estão em %, '0.45' é fração e vira 45
    CASE
      WHEN e.pct_concluido LIKE '%\%%' THEN CAST(replace(replace(e.pct_concluido, '%', ''), ',', '.') AS DOUBLE)
      ELSE CAST(e.pct_concluido AS DOUBLE) * 100
    END AS pct
  FROM lakehouse_vertice.bronze.excel_tarefas e
  -- #6: a linha de TOTAL do fim da planilha somaria as horas em dobro
  WHERE e.tarefa <> 'TOTAL'
)
SELECT
  -- de-para pelo nome do arquivo. Se o código faltar (ou vier com outra
  -- grafia), o PRJ-xxx que está no próprio nome do arquivo resolve (#3).
  coalesce(p.projeto_id, pelo_nome.projeto_id)              AS projeto_id,
  'excel'                                                   AS ferramenta,
  CAST(l.id AS STRING)                                      AS id_na_ferramenta,
  l.fase,
  l.tarefa,
  l.responsavel,
  -- #4: com '/' é dd/MM/yyyy. Sem '/' é o número de série do Excel
  -- (dias desde 30/12/1899). O CAST duplo aceita '45661.0'.
  CASE WHEN l.inicio_previsto  LIKE '%/%' THEN to_date(l.inicio_previsto, 'dd/MM/yyyy')
       ELSE date_add(DATE'1899-12-30', CAST(CAST(l.inicio_previsto AS DOUBLE) AS INT)) END  AS inicio_baseline,
  CASE WHEN l.termino_previsto LIKE '%/%' THEN to_date(l.termino_previsto, 'dd/MM/yyyy')
       ELSE date_add(DATE'1899-12-30', CAST(CAST(l.termino_previsto AS DOUBLE) AS INT)) END AS fim_baseline,
  CASE WHEN l.inicio_real      LIKE '%/%' THEN to_date(l.inicio_real, 'dd/MM/yyyy')
       ELSE date_add(DATE'1899-12-30', CAST(CAST(l.inicio_real AS DOUBLE) AS INT)) END      AS inicio_real,
  CASE WHEN l.termino_real     LIKE '%/%' THEN to_date(l.termino_real, 'dd/MM/yyyy')
       ELSE date_add(DATE'1899-12-30', CAST(CAST(l.termino_real AS DOUBLE) AS INT)) END     AS fim_real,
  l.pct                                                     AS pct_como_veio,
  -- #7: '40h' vira 40
  CAST(replace(l.horas_previstas, 'h', '') AS DOUBLE)       AS horas,
  CASE WHEN l.pct >= 100 THEN 'concluida'
       WHEN l.pct = 0    THEN 'a_fazer'
       ELSE 'em_andamento' END                              AS status_na_ferramenta
FROM limpo l
LEFT JOIN projetos p
  ON p.ferramenta = 'excel' AND p.codigo_ferramenta = l.arquivo
LEFT JOIN projetos pelo_nome
  ON pelo_nome.projeto_id = regexp_extract(l.arquivo, '(PRJ-[0-9]{3})', 1);


-- ---------------------------------------------------------------------------
-- 2) ClickUp: 25 listas em JSON.
--    Sujeiras #3, #8 e #9.
-- ---------------------------------------------------------------------------
CREATE TEMPORARY VIEW tarefas_clickup AS
WITH campos AS (
  SELECT
    c.*,
    -- #8: o %, a fase e o baseline moram dentro da lista custom_fields
    filter(c.custom_fields, f -> f.name = 'Fase')[0].value            AS cf_fase,
    filter(c.custom_fields, f -> f.name = 'Progresso (%)')[0].value   AS cf_progresso,
    filter(c.custom_fields, f -> f.name = 'Início baseline')[0].value AS cf_inicio_baseline,
    filter(c.custom_fields, f -> f.name = 'Fim baseline')[0].value    AS cf_fim_baseline
  FROM lakehouse_vertice.bronze.clickup_tarefas c
)
SELECT
  -- de-para pelo id da lista. Se o código faltar, casa pelo nome da lista (#3).
  coalesce(p.projeto_id, pelo_nome.projeto_id)                          AS projeto_id,
  'clickup'                                                             AS ferramenta,
  c.id                                                                  AS id_na_ferramenta,
  c.cf_fase                                                             AS fase,
  c.name                                                                AS tarefa,
  c.assignees[0].username                                               AS responsavel,
  -- #8: datas em milissegundos desde 1970
  to_date(timestamp_millis(CAST(c.cf_inicio_baseline AS BIGINT)))       AS inicio_baseline,
  to_date(timestamp_millis(CAST(c.cf_fim_baseline AS BIGINT)))          AS fim_baseline,
  to_date(timestamp_millis(CAST(c.start_date AS BIGINT)))               AS inicio_real,
  to_date(timestamp_millis(CAST(c.date_done AS BIGINT)))                AS fim_real,
  CAST(c.cf_progresso AS DOUBLE)                                        AS pct_como_veio,
  -- time_estimate também vem em milissegundos
  c.time_estimate / 3600000                                             AS horas,
  -- #9: 12 jeitos de escrever o status viram 3
  CASE
    WHEN lower(trim(c.status.status)) IN ('done', 'closed', 'concluído', 'concluido')                THEN 'concluida'
    WHEN lower(trim(c.status.status)) IN ('to do', 'a fazer', 'backlog')                              THEN 'a_fazer'
    WHEN lower(trim(c.status.status)) IN ('in progress', 'em andamento', 'doing', 'review')           THEN 'em_andamento'
  END                                                                   AS status_na_ferramenta
FROM campos c
LEFT JOIN projetos p
  ON p.ferramenta = 'clickup' AND p.codigo_ferramenta = c.list_id
LEFT JOIN projetos pelo_nome
  ON pelo_nome.ferramenta = 'clickup' AND pelo_nome.nome_projeto = c.list_name;


-- ---------------------------------------------------------------------------
-- 3) MS Project: 15 cronogramas em XML.
--    Sujeiras #10, #11 e #12.
-- ---------------------------------------------------------------------------
CREATE TEMPORARY VIEW tarefas_msproject AS
WITH com_fase AS (
  -- #11: a fase não está na tarefa. Ela é a última tarefa-resumo de nível 1
  -- que apareceu antes, na ordem do arquivo. A janela fica num CTE porque o
  -- filtro Summary = 0 tem que vir DEPOIS (a fase é justamente um resumo).
  SELECT
    m.*,
    last_value(CASE WHEN m.OutlineLevel = 1 THEN m.Name END, true)
      OVER (PARTITION BY m.arquivo ORDER BY m.UID) AS fase
  FROM lakehouse_vertice.bronze.msproject_tarefas m
)
SELECT
  p.projeto_id,
  'msproject'                                                     AS ferramenta,
  CAST(m.UID AS STRING)                                           AS id_na_ferramenta,
  m.fase,
  m.Name                                                          AS tarefa,
  CAST(NULL AS STRING)                                            AS responsavel,
  to_date(m.Baseline.Start)                                       AS inicio_baseline,
  to_date(m.Baseline.Finish)                                      AS fim_baseline,
  to_date(m.ActualStart)                                          AS inicio_real,
  to_date(m.ActualFinish)                                         AS fim_real,
  CAST(m.PercentComplete AS DOUBLE)                               AS pct_como_veio,
  -- #12: 'PT40H0M0S' vira 40
  CAST(regexp_extract(m.Work, 'PT([0-9]+)H', 1) AS DOUBLE)        AS horas,
  CASE WHEN m.PercentComplete >= 100 THEN 'concluida'
       WHEN m.PercentComplete = 0    THEN 'a_fazer'
       ELSE 'em_andamento' END                                    AS status_na_ferramenta
FROM com_fase m
LEFT JOIN projetos p
  ON p.ferramenta = 'msproject' AND p.codigo_ferramenta = m.arquivo
-- #10: as tarefas-resumo somam as horas de baixo. Ficam só as de verdade.
WHERE m.Summary = 0;


-- ---------------------------------------------------------------------------
-- 4) A tabela: as três empilhadas, com o contrato de qualidade.
-- ---------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW tarefas (
  -- nenhuma tarefa pode ficar órfã: se o de-para falhar, o pipeline para
  CONSTRAINT achou_o_projeto      EXPECT (projeto_id IS NOT NULL)                   ON VIOLATION FAIL UPDATE,
  CONSTRAINT pct_entre_0_e_100    EXPECT (pct_concluido BETWEEN 0 AND 100)          ON VIOLATION FAIL UPDATE,
  CONSTRAINT horas_positivas      EXPECT (horas > 0)                                ON VIOLATION FAIL UPDATE,
  CONSTRAINT status_conhecido     EXPECT (status_na_ferramenta IS NOT NULL)         ON VIOLATION FAIL UPDATE
)
COMMENT 'Todas as tarefas dos 60 projetos num modelo só: 20 planilhas Excel, 25 listas do ClickUp e 15 cronogramas do MS Project. Uma linha por tarefa, com baseline, realizado, % concluído (0 a 100) e horas previstas. ferramenta diz de onde veio.'
AS
WITH empilhado AS (
  SELECT * FROM tarefas_excel
  UNION ALL
  SELECT * FROM tarefas_clickup
  UNION ALL
  SELECT * FROM tarefas_msproject
)
SELECT
  projeto_id || '-' || ferramenta || '-' || id_na_ferramenta AS tarefa_id,
  projeto_id,
  ferramenta,
  id_na_ferramenta,
  fase,
  tarefa,
  responsavel,
  inicio_baseline,
  fim_baseline,
  inicio_real,
  fim_real,
  pct_como_veio,
  -- #5: 11 tarefas do Excel vieram acima de 100%. Corta em 100 e sinaliza.
  least(pct_como_veio, 100)                                  AS pct_concluido,
  pct_como_veio > 100                                        AS pct_veio_acima_de_100,
  horas,
  status_na_ferramenta
FROM empilhado;

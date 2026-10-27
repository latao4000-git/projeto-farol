-- silver.colaboradores e silver.apontamentos.
--
-- Quem trabalha na Vértice e quantas horas cada pessoa apontou em cada
-- projeto, semana a semana (a base da pergunta 3: gente parada x gente
-- faltando).


-- ---------------------------------------------------------------------------
-- colaboradores. Sujeira #16.
-- ---------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW colaboradores
COMMENT 'As 520 pessoas da Vértice: papel, senioridade, custo por hora, admissão e desligamento. Uma linha por colaborador_id (os 3 cadastros duplicados foram resolvidos).'
AS
WITH ordenado AS (
  SELECT
    *,
    -- #16: COL0102, COL0257 e COL0433 aparecem duas vezes, uma delas em
    -- CAIXA ALTA. Fica o cadastro com o papel em minúsculas.
    row_number() OVER (
      PARTITION BY colaborador_id
      ORDER BY CASE WHEN papel = lower(papel) THEN 0 ELSE 1 END
    ) AS ordem
  FROM lakehouse_vertice.bronze.colaboradores
)
SELECT
  colaborador_id,
  nome,
  papel,
  senioridade,
  CAST(custo_hora AS DECIMAL(10,2))                AS custo_hora,
  to_date(data_admissao, 'yyyy-MM-dd')             AS data_admissao,
  to_date(data_desligamento, 'yyyy-MM-dd')         AS data_desligamento
FROM ordenado
WHERE ordem = 1;


-- ---------------------------------------------------------------------------
-- apontamentos (o timesheet semanal)
-- ---------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW apontamentos
COMMENT 'Timesheet semanal: horas disponíveis e horas apontadas por pessoa e projeto. semana é a sexta-feira (semana_inicio + 4), a mesma data do status semanal.'
AS
SELECT
  colaborador_id,
  projeto_id,
  to_date(semana_inicio, 'yyyy-MM-dd')             AS semana_inicio,
  -- a sexta da semana, para casar com o status semanal e com os custos
  date_add(to_date(semana_inicio, 'yyyy-MM-dd'), 4) AS semana,
  CAST(horas_disponiveis AS DOUBLE)                AS horas_disponiveis,
  CAST(horas_apontadas   AS DOUBLE)                AS horas_apontadas
FROM lakehouse_vertice.bronze.apontamentos;

-- gold.fato_projeto_semana: a evolução de cada projeto, sexta a sexta.
--
-- Responde "está piorando?". Uma linha por projeto e semana, da semana do
-- início até hoje (16/10/2026).
--
-- De onde vem o histórico? Excel, ClickUp e Project só guardam o % de HOJE.
-- O único lugar com o % de cada semana é o status semanal que o gerente
-- publica toda sexta. Por isso aqui o EV vem do status, e na fotografia de
-- hoje (gold.projeto_situacao_atual) ele vem das tarefas.
--
-- PV, EV e AC são ACUMULADOS: o EV da semana 40 é tudo que ficou pronto até
-- a semana 40. Nunca some EV de semanas diferentes do mesmo projeto.

CREATE OR REFRESH MATERIALIZED VIEW lakehouse_vertice.gold.fato_projeto_semana (
  CONSTRAINT pv_nao_negativo          EXPECT (pv >= 0)          ON VIOLATION FAIL UPDATE,
  CONSTRAINT ev_ate_o_orcamento       EXPECT (ev <= orcamento)  ON VIOLATION FAIL UPDATE
)
COMMENT 'Evolução semanal de cada projeto (uma linha por projeto e sexta-feira, do início até 16/10/2026): PV, EV e AC acumulados em reais, SPI, CPI, EAC, o farol publicado pelo gerente e as horas disponíveis, apontadas e ociosas do timesheet na semana. O EV vem do % do status semanal.'
AS
WITH
-- 1) as sextas-feiras de cada projeto, do início até hoje
semanas AS (
  SELECT
    p.projeto_id,
    p.orcamento_custo AS orcamento,
    explode(sequence(
      date_add(date_trunc('WEEK', p.data_inicio), 4),
      DATE'2026-10-16',
      INTERVAL 1 WEEK
    )) AS semana
  FROM projetos p
),

-- 2) PV: quanto do trabalho já DEVERIA estar pronto em cada sexta, pelo
--    baseline de cada tarefa (fração do prazo decorrida, entre 0 e 1)
pv_semana AS (
  SELECT
    s.projeto_id,
    s.semana,
    sum(t.horas * greatest(0, least(1,
      datediff(s.semana, t.inicio_baseline) / datediff(t.fim_baseline, t.inicio_baseline)
    )))           AS horas_planejadas,
    sum(t.horas)  AS horas_totais
  FROM semanas s
  JOIN tarefas t ON t.projeto_id = s.projeto_id
  GROUP BY s.projeto_id, s.semana
),

-- 3) EV: o % do status daquela sexta. Projeto concluído para de publicar,
--    então o último % (e o último farol) vale para as semanas seguintes.
--    A janela fica neste CTE, e a conta vem no próximo.
status_preenchido AS (
  SELECT
    s.projeto_id,
    s.semana,
    last_value(st.pct_concluido, true) OVER (PARTITION BY s.projeto_id ORDER BY s.semana) AS pct_concluido,
    last_value(st.farol, true)         OVER (PARTITION BY s.projeto_id ORDER BY s.semana) AS farol_do_gerente
  FROM semanas s
  LEFT JOIN status_semanal st
    ON st.projeto_id = s.projeto_id AND st.data_status = s.semana
),

-- 4) AC: o custo real lançado em cada semana, depois acumulado
custo_semana AS (
  SELECT projeto_id, semana, sum(valor) AS custo
  FROM custos
  GROUP BY projeto_id, semana
),
ac_semana AS (
  SELECT
    s.projeto_id,
    s.semana,
    sum(coalesce(c.custo, 0)) OVER (PARTITION BY s.projeto_id ORDER BY s.semana) AS ac
  FROM semanas s
  LEFT JOIN custo_semana c
    ON c.projeto_id = s.projeto_id AND c.semana = s.semana
),

-- 5) as horas do timesheet na semana
horas_semana AS (
  SELECT
    projeto_id,
    semana,
    sum(horas_disponiveis)                   AS horas_disponiveis,
    sum(horas_apontadas)                     AS horas_apontadas,
    round(sum(horas_disponiveis - horas_apontadas), 2) AS horas_ociosas
  FROM apontamentos
  GROUP BY projeto_id, semana
),

-- 6) os valores em reais
valores AS (
  SELECT
    s.projeto_id,
    s.semana,
    s.orcamento,
    s.orcamento * pv.horas_planejadas / pv.horas_totais        AS pv,
    s.orcamento * coalesce(st.pct_concluido, 0) / 100          AS ev,
    ac.ac,
    st.farol_do_gerente,
    h.horas_disponiveis,
    h.horas_apontadas,
    h.horas_ociosas
  FROM semanas s
  JOIN pv_semana pv          ON pv.projeto_id = s.projeto_id AND pv.semana = s.semana
  JOIN status_preenchido st  ON st.projeto_id = s.projeto_id AND st.semana = s.semana
  JOIN ac_semana ac          ON ac.projeto_id = s.projeto_id AND ac.semana = s.semana
  LEFT JOIN horas_semana h   ON h.projeto_id  = s.projeto_id AND h.semana  = s.semana
),

-- 7) os índices
indices AS (
  SELECT
    *,
    round(try_divide(ev, pv), 4) AS spi,
    round(try_divide(ev, ac), 4) AS cpi
  FROM valores
)
SELECT
  projeto_id,
  semana,
  orcamento,
  round(pv, 2)                         AS pv,
  round(ev, 2)                         AS ev,
  round(ac, 2)                         AS ac,
  spi,
  cpi,
  round(try_divide(orcamento, cpi), 2) AS eac,
  farol_do_gerente,
  horas_disponiveis,
  horas_apontadas,
  horas_ociosas
FROM indices;

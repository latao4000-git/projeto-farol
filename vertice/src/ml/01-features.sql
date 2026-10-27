-- Noite 3 · Prompt 1 · As features: o que descreve um projeto que VAI estourar
--
-- Uma linha por projeto e semana (sexta-feira). Cada coluna olha só para trás:
-- tudo que está aqui era conhecido NAQUELA sexta. É isso que deixa usar a mesma
-- tabela para treinar (semanas antigas, com rótulo) e para pontuar (a semana de
-- hoje, 2026-10-16, sem rótulo).
--
-- Os dois alvos (o futuro, que NUNCA entra como feature; por isso começam com alvo_/estoura):
--   alvo_pior_indice_30d  o menor entre SPI e CPI nas 4 semanas seguintes. É o que o modelo prevê:
--                         "daqui a 30 dias, o pior índice deste projeto vai estar em quanto?"
--   estoura_30d           1 se esse pior índice fica abaixo de 0,9; 0 senão. É a pergunta 4 do dono:
--                         "a regra de corte ainda não vê nada, mas vai ver em até 30 dias?"
--   Os dois ficam NULL quando ainda não há 4 semanas de futuro observado (é o caso de hoje).
--
--   elegivel = 1   projeto em andamento, com 12+ semanas de vida, ainda não terminado e com SPI e CPI >= 0,9:
--                  é sobre esses que a pergunta faz sentido (quem já está abaixo de 0,9, a regra já vê)
--
-- O texto do status semanal entra pela causa que a noite 2 extraiu (gold.status_estruturado).
-- Ela existe em TODAS as semanas (IA nos últimos 90 dias, palavra-chave no histórico), então
-- a feature significa a mesma coisa no treino e no score.

-- As features moram no schema ml, o laboratório do cientista: são passo intermediário,
-- não resposta para a diretoria. Na gold fica só o resultado (gold.score_estouro_30d).
CREATE SCHEMA IF NOT EXISTS lakehouse_vertice.ml
  COMMENT 'Laboratório de ML: features, métricas e o modelo registrado. Noite 3.';

CREATE OR REPLACE TABLE lakehouse_vertice.ml.features_projeto_semana
COMMENT 'Noite 3: features por projeto e semana (só olham para trás) + rótulo estoura_30d (SPI ou CPI cruza 0,9 em até 4 semanas). Hoje = 2026-10-16.'
AS
WITH base AS (
  SELECT f.projeto_id, f.semana, f.orcamento, f.pv, f.ev, f.ac, f.spi, f.cpi,
         f.horas_disponiveis, f.horas_ociosas, f.farol_do_gerente,
         d.data_inicio, d.duracao_baseline_dias, d.segmento,
         -- o que o projeto fez nas últimas 4 semanas: a "velocidade" atual, não a média da vida toda
         f.ev - lag(f.ev, 4) OVER w AS ev_4s,
         f.ac - lag(f.ac, 4) OVER w AS ac_4s,
         f.pv - lag(f.pv, 4) OVER w AS pv_4s,
         f.spi - lag(f.spi, 4) OVER w AS d_spi_4s,
         f.cpi - lag(f.cpi, 4) OVER w AS d_cpi_4s,
         f.cpi - lag(f.cpi, 8) OVER w AS d_cpi_8s,
         f.spi - lag(f.spi, 8) OVER w AS d_spi_8s,
         CASE WHEN f.cpi < lag(f.cpi) OVER w THEN 1 ELSE 0 END AS cpi_caiu,
         SUM(f.horas_ociosas)     OVER (PARTITION BY f.projeto_id ORDER BY f.semana ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS ociosas_4s,
         SUM(f.horas_disponiveis) OVER (PARTITION BY f.projeto_id ORDER BY f.semana ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS disponiveis_4s,
         -- o futuro, SÓ para o rótulo: nunca entra como feature
         MIN(least(f.spi, f.cpi)) OVER (PARTITION BY f.projeto_id ORDER BY f.semana ROWS BETWEEN 1 FOLLOWING AND 4 FOLLOWING) AS _pior_indice_futuro,
         COUNT(*)                 OVER (PARTITION BY f.projeto_id ORDER BY f.semana ROWS BETWEEN 1 FOLLOWING AND 4 FOLLOWING) AS _semanas_futuro
  FROM lakehouse_vertice.gold.fato_projeto_semana f
  JOIN lakehouse_vertice.gold.projeto_situacao_atual d USING (projeto_id)
  WINDOW w AS (PARTITION BY f.projeto_id ORDER BY f.semana)
),
sequencia AS (   -- quantas das últimas 4 semanas o CPI caiu
  SELECT *, SUM(cpi_caiu) OVER (PARTITION BY projeto_id ORDER BY semana ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS semanas_cpi_caindo
  FROM base
),
custo_categoria AS (   -- de onde vem o custo das últimas 4 semanas
  SELECT b.projeto_id, b.semana,
         try_divide(SUM(CASE WHEN c.categoria = 'consultoria' THEN c.valor END), SUM(c.valor)) AS pct_consultoria_4s,
         try_divide(SUM(CASE WHEN c.categoria = 'cloud' THEN c.valor END), SUM(c.valor))       AS pct_cloud_4s
  FROM base b
  JOIN lakehouse_vertice.silver.custos c
    ON c.projeto_id = b.projeto_id AND c.semana > date_sub(b.semana, 28) AND c.semana <= b.semana
  GROUP BY b.projeto_id, b.semana
),
status_4s AS (   -- o que o gerente escreveu no status das últimas 4 semanas (lido pela IA na noite 2)
  SELECT b.projeto_id, b.semana,
         COUNT_IF(s.causa_bloqueio = 'change_freeze')          AS status_freeze_4s,
         COUNT_IF(s.causa_bloqueio = 'falta_sre')              AS status_falta_sre_4s,
         COUNT_IF(s.causa_bloqueio = 'dependencia_fornecedor') AS status_fornecedor_4s,
         COUNT_IF(s.causa_bloqueio = 'rotatividade')           AS status_rotatividade_4s,
         COUNT_IF(s.causa_bloqueio = 'mudanca_escopo')         AS status_escopo_4s,
         COUNT_IF(s.causa_bloqueio = 'bug_retrabalho')         AS status_retrabalho_4s,
         COUNT_IF(s.causa_bloqueio NOT IN ('sem_bloqueio', 'nao_reportado')) AS status_com_bloqueio_4s
  FROM base b
  JOIN lakehouse_vertice.gold.status_estruturado s
    ON s.projeto_id = b.projeto_id AND s.data_status > date_sub(b.semana, 28) AND s.data_status <= b.semana
  GROUP BY b.projeto_id, b.semana
),
squad AS (   -- quem passou pelo projeto: quem apontou hora nele (o timesheet diz onde a pessoa está)
  SELECT DISTINCT projeto_id, colaborador_id FROM lakehouse_vertice.silver.apontamentos
),
saidas_12s AS (   -- gente que saiu da empresa estando no projeto, nas últimas 12 semanas
  SELECT b.projeto_id, b.semana, COUNT(*) AS saidas_12s
  FROM base b
  JOIN squad q ON q.projeto_id = b.projeto_id
  JOIN lakehouse_vertice.silver.colaboradores c USING (colaborador_id)
  WHERE c.data_desligamento > date_sub(b.semana, 84) AND c.data_desligamento <= b.semana
  GROUP BY b.projeto_id, b.semana
)
SELECT s.projeto_id,
       s.semana,
       s.segmento,
       -- onde o projeto está hoje
       s.spi,
       s.cpi,
       least(s.spi, s.cpi)                                                 AS indice_min,
       least(s.spi, s.cpi) - least(s.spi - s.d_spi_4s, s.cpi - s.d_cpi_4s) AS d_indice_min_4s,
       CAST(s.ev / s.orcamento AS DOUBLE)                                  AS pct_fisico,
       datediff(s.semana, s.data_inicio) / s.duracao_baseline_dias          AS pct_prazo,
       -- para onde ele está indo
       s.d_spi_4s,
       s.d_cpi_4s,
       s.d_spi_8s,
       s.d_cpi_8s,
       s.semanas_cpi_caindo,
       CAST(try_divide(s.ev_4s, s.ac_4s) AS DOUBLE)                        AS cpi_ultimas_4s,
       CAST(try_divide(s.ev_4s, s.pv_4s) AS DOUBLE)                        AS spi_ultimas_4s,
       -- gente e custo
       try_divide(s.ociosas_4s, s.disponiveis_4s)                          AS ociosidade_4s,
       cc.pct_consultoria_4s,
       cc.pct_cloud_4s,
       coalesce(sa.saidas_12s, 0)                                          AS saidas_12s,
       -- o texto do status semanal, já classificado
       coalesce(st.status_freeze_4s, 0)       AS status_freeze_4s,
       coalesce(st.status_falta_sre_4s, 0)    AS status_falta_sre_4s,
       coalesce(st.status_fornecedor_4s, 0)   AS status_fornecedor_4s,
       coalesce(st.status_rotatividade_4s, 0) AS status_rotatividade_4s,
       coalesce(st.status_escopo_4s, 0)       AS status_escopo_4s,
       coalesce(st.status_retrabalho_4s, 0)   AS status_retrabalho_4s,
       coalesce(st.status_com_bloqueio_4s, 0) AS status_com_bloqueio_4s,
       s.farol_do_gerente,
       -- quem pode ser pontuado, e o rótulo
       CASE WHEN s.spi >= 0.9 AND s.cpi >= 0.9 AND datediff(s.semana, s.data_inicio) >= 84
             AND s.ev < s.orcamento * 0.98
             AND (p.status = 'em_andamento' OR s.semana < DATE'2026-10-16') THEN 1 ELSE 0 END AS elegivel,
       CASE WHEN s._semanas_futuro = 4 THEN s._pior_indice_futuro END                  AS alvo_pior_indice_30d,
       CASE WHEN s._semanas_futuro = 4 THEN CAST(s._pior_indice_futuro < 0.9 AS INT) END AS estoura_30d
FROM sequencia s
JOIN lakehouse_vertice.silver.projetos p USING (projeto_id)
LEFT JOIN custo_categoria cc USING (projeto_id, semana)
LEFT JOIN status_4s st USING (projeto_id, semana)
LEFT JOIN saidas_12s sa USING (projeto_id, semana);

-- conferência rápida: a taxa base e o tamanho da tabela
SELECT COUNT(*)                                           AS linhas,
       COUNT_IF(elegivel = 1 AND estoura_30d IS NOT NULL) AS linhas_de_treino,
       ROUND(AVG(CASE WHEN elegivel = 1 THEN estoura_30d END), 4) AS taxa_base,
       COUNT_IF(semana = DATE'2026-10-16')                AS linhas_de_hoje
FROM lakehouse_vertice.ml.features_projeto_semana;

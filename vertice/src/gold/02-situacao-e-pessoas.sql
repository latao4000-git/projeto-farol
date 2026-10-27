-- gold.projeto_situacao_atual e gold.utilizacao_pessoa_semana.
--
-- A fotografia de hoje (16/10/2026) de cada projeto, que responde as
-- perguntas 1 e 2 do dono, e o uso de cada pessoa por semana, que responde
-- a pergunta 3. Os KPIs de hoje vêm das TAREFAS das três ferramentas.


-- ---------------------------------------------------------------------------
-- projeto_situacao_atual: "quais projetos estão atrasados?" e
-- "quanto esse atraso vai me custar?"
-- ---------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW lakehouse_vertice.gold.projeto_situacao_atual
COMMENT 'Fotografia de hoje (16/10/2026) dos 60 projetos: o cadastro (cliente, segmento, tipo, ferramenta, gerente, contrato, orçamento, prazo) e os KPIs calculados sobre as tarefas das ferramentas: PV, EV, AC, SPI, CPI, EAC, estouro previsto, margem projetada, atraso e término projetados. situacao: crítico (SPI ou CPI < 0,8), atenção (< 0,9), ok ou concluído. melancia: farol do gerente verde com SPI < 0,9.'
AS
WITH
-- 1) horas planejadas e agregadas de hoje, somando as tarefas
horas AS (
  SELECT
    projeto_id,
    sum(horas)                           AS horas_totais,
    sum(horas * pct_concluido / 100)     AS horas_agregadas,
    sum(horas * greatest(0, least(1,
      datediff(DATE'2026-10-16', inicio_baseline) / datediff(fim_baseline, inicio_baseline)
    )))                                  AS horas_planejadas
  FROM tarefas
  GROUP BY projeto_id
),

-- 2) o custo real até hoje
custo AS (
  SELECT projeto_id, sum(valor) AS ac
  FROM custos
  WHERE data <= DATE'2026-10-16'
  GROUP BY projeto_id
),

-- 3) o farol publicado hoje (um por projeto em andamento)
farol_hoje AS (
  SELECT projeto_id, farol
  FROM status_semanal
  WHERE data_status = DATE'2026-10-16'
),

-- 4) PV, EV e AC em reais
valores AS (
  SELECT
    p.*,
    datediff(p.data_fim_baseline, p.data_inicio)                 AS duracao_baseline_dias,
    p.orcamento_custo * h.horas_planejadas / h.horas_totais      AS pv,
    p.orcamento_custo * h.horas_agregadas  / h.horas_totais      AS ev,
    coalesce(c.ac, 0)                                            AS ac,
    f.farol                                                      AS farol_do_gerente
  FROM projetos p
  LEFT JOIN horas h      ON h.projeto_id = p.projeto_id
  LEFT JOIN custo c      ON c.projeto_id = p.projeto_id
  LEFT JOIN farol_hoje f ON f.projeto_id = p.projeto_id
),

-- 5) os índices. As contas usam o valor BRUTO; o arredondamento é só na saída.
--    (EAC sobre o CPI já arredondado em 4 casas desviava o estouro em R$ 127.)
indices AS (
  SELECT
    *,
    try_divide(ev, pv) AS spi_bruto,
    try_divide(ev, ac) AS cpi_bruto
  FROM valores
),

-- 6) o que os índices projetam para o fim do projeto
projecao AS (
  SELECT
    *,
    round(spi_bruto, 4)                                                AS spi,
    round(cpi_bruto, 4)                                                AS cpi,
    try_divide(orcamento_custo, cpi_bruto)                             AS eac,
    try_divide(duracao_baseline_dias, spi_bruto) - duracao_baseline_dias AS atraso_dias
  FROM indices
)
SELECT
  projeto_id || ' · ' || nome_projeto                       AS projeto,
  projeto_id,
  nome_projeto,
  cliente,
  segmento,
  tipo_projeto,
  ferramenta,
  gerente_projeto,
  valor_contrato,
  orcamento_custo                                           AS orcamento,
  data_inicio,
  data_fim_baseline,
  duracao_baseline_dias,
  status,
  round(pv, 2)                                              AS pv,
  round(ev, 2)                                              AS ev,
  round(ac, 2)                                              AS ac,
  spi,
  cpi,
  round(eac, 2)                                             AS eac,
  round(greatest(eac - orcamento_custo, 0), 2)              AS estouro_previsto,
  round(try_divide(valor_contrato - eac, valor_contrato), 4) AS margem_projetada,
  round(atraso_dias, 0)                                     AS atraso_projetado_dias,
  date_add(data_inicio, CAST(round(try_divide(duracao_baseline_dias, spi_bruto)) AS INT)) AS termino_projetado,
  -- regra de corte da Vértice
  CASE
    WHEN status <> 'em_andamento'  THEN 'concluído'
    WHEN spi_bruto < 0.8 OR cpi_bruto < 0.8 THEN 'crítico'
    WHEN spi_bruto < 0.9 OR cpi_bruto < 0.9 THEN 'atenção'
    ELSE 'ok'
  END                                                       AS situacao,
  farol_do_gerente,
  -- regra do manual da Vértice: o farol que o número daria
  CASE
    WHEN spi_bruto >= 0.95 THEN 'verde'
    WHEN spi_bruto >= 0.90 THEN 'amarelo'
    ELSE 'vermelho'
  END                                                       AS farol_calculado,
  -- melancia: verde por fora, vermelho por dentro
  coalesce(status = 'em_andamento' AND farol_do_gerente = 'verde' AND spi_bruto < 0.9, false) AS melancia
FROM projecao;


-- ---------------------------------------------------------------------------
-- utilizacao_pessoa_semana: "tenho gente parada enquanto outro projeto pede
-- gente?"
-- ---------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW lakehouse_vertice.gold.utilizacao_pessoa_semana
COMMENT 'Uso de cada pessoa por projeto e semana (sexta-feira): nome, papel, senioridade, horas disponíveis, apontadas e ociosas, utilização (apontadas ÷ disponíveis), custo das horas paradas (horas ociosas × custo por hora) e o SPI do projeto naquela semana.'
AS
SELECT
  a.colaborador_id,
  c.nome,
  c.papel,
  c.senioridade,
  a.projeto_id,
  a.semana,
  a.horas_disponiveis,
  a.horas_apontadas,
  round(a.horas_disponiveis - a.horas_apontadas, 2)               AS horas_ociosas,
  round(try_divide(a.horas_apontadas, a.horas_disponiveis), 4)    AS utilizacao,
  round((a.horas_disponiveis - a.horas_apontadas) * c.custo_hora, 2) AS custo_ocioso,
  f.spi                                                           AS spi_do_projeto
FROM apontamentos a
JOIN colaboradores c
  ON c.colaborador_id = a.colaborador_id
LEFT JOIN lakehouse_vertice.gold.fato_projeto_semana f
  ON f.projeto_id = a.projeto_id AND f.semana = a.semana;

-- Noite 1 · Verificação
-- Confere se o seu ambiente chegou nos mesmos números da aula.
-- Cada linha mostra o esperado, o obtido e se bateu. Se algo der "CONFIRA",
-- o problema está na carga ou na query, não no dado: a seed é fixa (42).
--
-- Precisa do rascunho do exemplo 05 (bronze.rascunho_tarefas): rode o exemplo 05 antes.
--
-- Rode com:
--   python3 scripts/run_sql.py setup/99-verificacao.sql --profile SEU-PERFIL

WITH contagens AS (
    SELECT 'linhas em projetos'            AS item, 60    AS esperado, (SELECT COUNT(*) FROM lakehouse_vertice.bronze.projetos)             AS obtido UNION ALL
    SELECT 'linhas em status_semanal',              3911,  (SELECT COUNT(*) FROM lakehouse_vertice.bronze.status_semanal)       UNION ALL
    SELECT 'linhas em excel_tarefas (com TOTAL)',   1663,  (SELECT COUNT(*) FROM lakehouse_vertice.bronze.excel_tarefas)        UNION ALL
    SELECT 'linhas em clickup_tarefas',             2119,  (SELECT COUNT(*) FROM lakehouse_vertice.bronze.clickup_tarefas)      UNION ALL
    SELECT 'linhas em msproject_tarefas',           1260,  (SELECT COUNT(*) FROM lakehouse_vertice.bronze.msproject_tarefas)    UNION ALL
    SELECT 'linhas em colaboradores',               523,   (SELECT COUNT(*) FROM lakehouse_vertice.bronze.colaboradores)        UNION ALL
    SELECT 'linhas em apontamentos',                30883, (SELECT COUNT(*) FROM lakehouse_vertice.bronze.apontamentos)         UNION ALL
    SELECT 'linhas em custos',                      23640, (SELECT COUNT(*) FROM lakehouse_vertice.bronze.custos)               UNION ALL
    SELECT 'linhas em entregas_fornecedor',         640,   (SELECT COUNT(*) FROM lakehouse_vertice.bronze.entregas_fornecedor)  UNION ALL
    SELECT 'custos com vírgula decimal',            671,   (SELECT COUNT(*) FROM lakehouse_vertice.bronze.custos WHERE valor LIKE '%,%') UNION ALL
    SELECT 'carteira (R$ mi, arredondado)',         305,   (SELECT CAST(ROUND(SUM(CAST(valor_contrato AS DECIMAL(18,2))) / 1e6) AS INT) FROM lakehouse_vertice.bronze.projetos) UNION ALL
    SELECT 'custo real total (R$ mi)',              193,   (SELECT CAST(ROUND(SUM(CAST(replace(valor, ',', '.') AS DECIMAL(18,2))) / 1e6) AS INT) FROM lakehouse_vertice.bronze.custos) UNION ALL
    SELECT 'projetos no rascunho (3 ferramentas)',  60,    (SELECT COUNT(DISTINCT projeto_id) FROM lakehouse_vertice.bronze.rascunho_tarefas)
),
kpi AS (
    SELECT r.projeto_id,
           CAST(p.orcamento_custo AS DOUBLE) * SUM(r.horas * r.pct_concluido / 100) / SUM(r.horas) AS ev,
           SUM(r.horas * r.pct_concluido / 100) / SUM(r.horas * GREATEST(0, LEAST(1,
               datediff(DATE'2026-10-16', r.inicio_baseline) / datediff(r.fim_baseline, r.inicio_baseline)))) AS spi
    FROM lakehouse_vertice.bronze.rascunho_tarefas r
    JOIN lakehouse_vertice.bronze.projetos p USING (projeto_id)
    WHERE p.status = 'em_andamento'
    GROUP BY r.projeto_id, p.orcamento_custo
),
ac AS (
    SELECT projeto_id, SUM(CAST(replace(valor, ',', '.') AS DOUBLE)) AS ac
    FROM lakehouse_vertice.bronze.custos GROUP BY projeto_id
),
k AS (SELECT kpi.projeto_id, spi, ev / ac.ac AS cpi FROM kpi JOIN ac USING (projeto_id)),
resumo AS (
    SELECT 'projetos em andamento' AS item, 41 AS esperado, COUNT(*) AS obtido FROM k UNION ALL
    SELECT 'projetos críticos (SPI ou CPI < 0,8)', 7, COUNT(*) FILTER (WHERE LEAST(spi, cpi) < 0.8) FROM k UNION ALL
    SELECT 'projetos em atenção (< 0,9, sem crítico)', 10,
           COUNT(*) FILTER (WHERE LEAST(spi, cpi) >= 0.8 AND LEAST(spi, cpi) < 0.9) FROM k UNION ALL
    SELECT 'SPI do PRJ-011 × 100', 77, CAST(ROUND(MAX(spi) FILTER (WHERE projeto_id = 'PRJ-011') * 100) AS INT) FROM k UNION ALL
    SELECT 'farol verde com SPI < 0,9 (melancia)', 4,
           (SELECT COUNT(*) FROM k JOIN lakehouse_vertice.bronze.status_semanal s USING (projeto_id)
            WHERE s.data_status = '2026-10-16' AND lower(s.farol) = 'verde' AND k.spi < 0.9)
)
SELECT item, esperado, obtido, CASE WHEN esperado = obtido THEN 'ok' ELSE 'CONFIRA' END AS status
FROM (SELECT * FROM contagens UNION ALL SELECT * FROM resumo);

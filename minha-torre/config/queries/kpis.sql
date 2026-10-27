-- Os números do topo da Torre (fotografia de 16/10/2026).
-- "Alto risco em 30 dias" (score da noite 3) NÃO entra aqui: a tabela pode não existir,
-- e query com tabela inexistente quebra o typegen e o build. A tela conta pela rota /api/score-estouro.
WITH multa AS (   -- multa contratual das entregas atrasadas na vigência atual (gold.contratos, noite 4)
  SELECT e.projeto_id,
         SUM(e.valor * least(CASE WHEN e.data_entrega IS NOT NULL THEN e.dias_de_atraso_na_entrega
                                  ELSE datediff(DATE'2026-10-16', e.data_prometida) END * c.multa_atraso_pct_dia,
                             c.teto_multa_pct) / 100) AS multa_a_cobrar
  FROM lakehouse_vertice.silver.entregas_fornecedor e
  JOIN lakehouse_vertice.gold.contratos c ON lower(c.fornecedor) = lower(e.fornecedor)
  WHERE c.multa_atraso_pct_dia IS NOT NULL
    AND ((e.data_entrega IS NOT NULL AND e.dias_de_atraso_na_entrega > 0) OR e.em_atraso)
    AND e.data_prometida > add_months(c.data_fim_vigencia, -12)
  GROUP BY e.projeto_id
)
SELECT COUNT(*)                                                    AS projetos_em_andamento,
       COUNT_IF(situacao IN ('crítico', 'atenção'))                AS projetos_em_risco,
       COUNT_IF(situacao = 'crítico')                              AS projetos_criticos,
       COUNT_IF(melancia)                                          AS projetos_melancia,
       SUM(estouro_previsto)                                       AS estouro_previsto,
       SUM(valor_contrato)                                         AS carteira,
       (SELECT SUM(multa_a_cobrar) FROM multa)                     AS multa_a_cobrar
FROM lakehouse_vertice.gold.projeto_situacao_atual
WHERE status = 'em_andamento'

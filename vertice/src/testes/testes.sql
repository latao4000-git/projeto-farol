-- Testes de qualidade: a tarefa testes_de_qualidade do job vertice_farol.
--
-- Cada teste é um SELECT que devolve 'ok' ou chama raise_error(), e a tarefa
-- (e o job) quebra. Melhor o dashboard ficar com o dado da semana passada
-- do que com o dado errado de hoje.
--
-- Roda como sql_task: o arquivo é cortado em cada ponto e vírgula, então
-- nenhuma mensagem pode ter ponto e vírgula dentro.


-- 1) os 60 projetos têm cronograma na silver.tarefas
SELECT CASE
  WHEN (SELECT count(DISTINCT projeto_id) FROM lakehouse_vertice.silver.tarefas) <> 60
  THEN raise_error('Teste 1 falhou: nem todo projeto tem tarefas na silver.tarefas. Confira o de-para em silver.projetos.')
  ELSE 'teste 1 ok: os 60 projetos têm cronograma'
END AS teste_01;


-- 2) cada projeto veio de UMA ferramenta, a do cadastro do PMO
SELECT CASE
  WHEN (
    SELECT count(*)
    FROM (
      SELECT t.projeto_id
      FROM lakehouse_vertice.silver.tarefas t
      JOIN lakehouse_vertice.silver.projetos p USING (projeto_id)
      GROUP BY t.projeto_id
      HAVING count(DISTINCT t.ferramenta) > 1 OR max(t.ferramenta) <> max(p.ferramenta)
    )
  ) > 0
  THEN raise_error('Teste 2 falhou: há projeto com tarefas de mais de uma ferramenta, ou de uma ferramenta diferente do cadastro.')
  ELSE 'teste 2 ok: cada projeto veio da ferramenta do cadastro'
END AS teste_02;


-- 3) as horas do Excel na silver = a soma das linhas de TOTAL das planilhas
SELECT CASE
  WHEN abs(
    (SELECT sum(horas) FROM lakehouse_vertice.silver.tarefas WHERE ferramenta = 'excel')
    - (SELECT sum(CAST(replace(horas_previstas, 'h', '') AS DOUBLE))
       FROM lakehouse_vertice.bronze.excel_tarefas WHERE tarefa = 'TOTAL')
  ) > 0.01
  THEN raise_error('Teste 3 falhou: as horas do Excel na silver não batem com as linhas de TOTAL das planilhas.')
  ELSE 'teste 3 ok: horas do Excel = linhas de TOTAL'
END AS teste_03;


-- 4) uma linha por pessoa na silver
SELECT CASE
  WHEN (SELECT count(*) - count(DISTINCT colaborador_id) FROM lakehouse_vertice.silver.colaboradores) <> 0
  THEN raise_error('Teste 4 falhou: há colaborador_id repetido em silver.colaboradores.')
  ELSE 'teste 4 ok: uma linha por pessoa'
END AS teste_04;


-- 5) a CodeForge virou um fornecedor só
SELECT CASE
  WHEN (
    SELECT count(DISTINCT fornecedor)
    FROM lakehouse_vertice.silver.entregas_fornecedor
    WHERE replace(lower(fornecedor), ' ', '') LIKE '%codeforge%'
  ) <> 1
  THEN raise_error('Teste 5 falhou: a CodeForge aparece com mais de um nome em silver.entregas_fornecedor.')
  ELSE 'teste 5 ok: a CodeForge é um fornecedor só'
END AS teste_05;


-- 6) a limpeza não mudou o custo total (bronze com replace = silver)
SELECT CASE
  WHEN (SELECT sum(CAST(replace(valor, ',', '.') AS DECIMAL(18,2))) FROM lakehouse_vertice.bronze.custos)
    <> (SELECT sum(valor) FROM lakehouse_vertice.silver.custos)
  THEN raise_error('Teste 6 falhou: o custo total da silver é diferente do da bronze. A limpeza perdeu ou criou dinheiro.')
  ELSE 'teste 6 ok: o custo total não mudou'
END AS teste_06;


-- 7) os 60 projetos têm fotografia de hoje
SELECT CASE
  WHEN (SELECT count(*) FROM lakehouse_vertice.gold.projeto_situacao_atual) <> 60
    OR (SELECT count(DISTINCT projeto_id) FROM lakehouse_vertice.gold.projeto_situacao_atual) <> 60
  THEN raise_error('Teste 7 falhou: gold.projeto_situacao_atual não tem exatamente uma linha para cada um dos 60 projetos.')
  ELSE 'teste 7 ok: 60 projetos na fotografia de hoje'
END AS teste_07;


-- 8) todo projeto em andamento tem SPI e CPI
SELECT CASE
  WHEN (
    SELECT count(*) FROM lakehouse_vertice.gold.projeto_situacao_atual
    WHERE status = 'em_andamento' AND (spi IS NULL OR cpi IS NULL)
  ) > 0
  THEN raise_error('Teste 8 falhou: há projeto em andamento sem SPI ou sem CPI.')
  ELSE 'teste 8 ok: todo projeto em andamento tem SPI e CPI'
END AS teste_08;


-- 9) o EV de hoje do status semanal bate com o das ferramentas (diferença < 1%)
SELECT CASE
  WHEN abs(
    (SELECT sum(ev) FROM lakehouse_vertice.gold.fato_projeto_semana WHERE semana = DATE'2026-10-16')
    / (SELECT sum(ev) FROM lakehouse_vertice.gold.projeto_situacao_atual)
    - 1
  ) >= 0.01
  THEN raise_error('Teste 9 falhou: o EV de hoje pelo status semanal difere mais de 1% do EV pelas tarefas das ferramentas.')
  ELSE 'teste 9 ok: EV do status = EV das ferramentas'
END AS teste_09;


-- 10) AC de hoje no fato = soma dos lançamentos até hoje, projeto a projeto
SELECT CASE
  WHEN (
    SELECT count(*)
    FROM lakehouse_vertice.gold.fato_projeto_semana f
    JOIN (
      SELECT projeto_id, sum(valor) AS ac
      FROM lakehouse_vertice.silver.custos
      WHERE data <= DATE'2026-10-16'
      GROUP BY projeto_id
    ) c USING (projeto_id)
    WHERE f.semana = DATE'2026-10-16' AND abs(f.ac - c.ac) > 0.01
  ) > 0
  THEN raise_error('Teste 10 falhou: o AC de hoje no fato não bate com a soma dos lançamentos de custo até hoje.')
  ELSE 'teste 10 ok: AC do fato = custos lançados'
END AS teste_10;

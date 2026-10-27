-- Gente parada nas últimas 12 semanas (até 16/10/2026): utilização abaixo de 20%.
-- horas_paradas_semana e custo_ocioso_semana são MÉDIAS por semana: é o que deixa
-- de ser desperdiçado em cada semana em que a pessoa trabalha num projeto que precisa dela.
-- O nome do projeto vem da gold e o custo/hora do cadastro (silver.colaboradores).
SELECT u.colaborador_id, u.nome, u.papel, u.senioridade,
       u.projeto_id AS projeto_origem, p.projeto AS projeto_origem_nome,
       ROUND(SUM(u.horas_apontadas) / SUM(u.horas_disponiveis), 3)        AS utilizacao_media,
       ROUND(SUM(u.horas_ociosas) / COUNT(DISTINCT u.semana), 1)          AS horas_paradas_semana,
       ROUND(SUM(u.custo_ocioso) / COUNT(DISTINCT u.semana), 2)           AS custo_ocioso_semana,
       MAX(c.custo_hora)                                                  AS custo_hora
FROM lakehouse_vertice.gold.utilizacao_pessoa_semana u
JOIN lakehouse_vertice.silver.colaboradores c USING (colaborador_id)
LEFT JOIN lakehouse_vertice.gold.projeto_situacao_atual p USING (projeto_id)
WHERE u.semana > DATE'2026-07-24'
GROUP BY u.colaborador_id, u.nome, u.papel, u.senioridade, u.projeto_id, p.projeto
HAVING SUM(u.horas_apontadas) / SUM(u.horas_disponiveis) < 0.2
ORDER BY utilizacao_media

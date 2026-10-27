-- gold.status_estruturado: o texto livre do status semanal vira coluna.
--
-- Toda sexta o gerente escreve o bloqueio do projeto em texto livre. Aqui
-- esse texto vira causa (lista fechada, dá para agrupar), bloqueio, quem
-- destrava e dias de impacto (número, dá para somar).
--
-- IA custa, e custa por linha (~5 s por status). Então cada status vai para
-- a ferramenta certa:
--   regra         semana sem bloqueio e status vazio: padrão fixo, custo zero
--   ia            texto com bloqueio dos últimos 90 dias (~160 status)
--   palavra_chave histórico antigo com bloqueio, onde a resposta não muda decisão
--
-- Incremental: a tabela ACUMULA e o MERGE só recebe os status que ainda não
-- estão nela. Na semana que vem, só os status da semana que vem passam pela IA.
--
-- Roda como sql_task: nenhum ponto e vírgula dentro das strings.


-- a) a tabela. NÃO é CREATE OR REPLACE: a IA não pode ser refeita a cada execução.
CREATE TABLE IF NOT EXISTS lakehouse_vertice.gold.status_estruturado (
  projeto_id       STRING    COMMENT 'Projeto (PRJ-xxx) que publicou o status',
  data_status      DATE      COMMENT 'Sexta-feira do status semanal',
  farol            STRING    COMMENT 'Farol publicado pelo gerente: verde, amarelo ou vermelho',
  causa_bloqueio   STRING    COMMENT 'Causa do bloqueio: change_freeze, falta_sre, dependencia_fornecedor, rotatividade, mudanca_escopo, bug_retrabalho, aprovacao_cliente, sem_bloqueio, nao_reportado (status vazio) ou outro',
  bloqueio         STRING    COMMENT 'O bloqueio descrito em poucas palavras (só nos status classificados pela IA)',
  quem_destrava    STRING    COMMENT 'Quem pode destravar o bloqueio (só nos status classificados pela IA)',
  dias_impacto     DOUBLE    COMMENT 'Dias de impacto no cronograma declarados no texto (1 semana = 7)',
  metodo           STRING    COMMENT 'Como o status foi classificado: regra, ia ou palavra_chave',
  texto_status     STRING    COMMENT 'O texto livre original do status semanal',
  _classificado_em TIMESTAMP COMMENT 'Quando esta linha foi classificada'
)
COMMENT 'Status semanal estruturado: para cada status de cada projeto, a causa do bloqueio, o bloqueio, quem destrava e os dias de impacto, tirados do texto livre por regra, IA (ai_classify e ai_extract nos últimos 90 dias) ou palavra-chave. Responde por que cada projeto atrasou.';


-- b) o MERGE incremental
MERGE INTO lakehouse_vertice.gold.status_estruturado AS destino
USING (
  WITH
  -- só o que ainda não foi classificado
  novos AS (
    SELECT s.projeto_id, s.data_status, s.farol, s.texto_status, s.status_vazio
    FROM lakehouse_vertice.silver.status_semanal s
    LEFT ANTI JOIN lakehouse_vertice.gold.status_estruturado e
      ON e.projeto_id = s.projeto_id AND e.data_status = s.data_status
  ),

  -- escolhe o método de cada status
  com_metodo AS (
    SELECT
      *,
      CASE
        WHEN status_vazio
          OR lower(texto_status) RLIKE 'bloqueios: nenhum|sem bloqueios|nada relevante' THEN 'regra'
        WHEN data_status >= DATE'2026-07-18'                                           THEN 'ia'
        ELSE 'palavra_chave'
      END AS metodo,
      -- só o trecho do bloqueio vai para a IA (o resto do texto fala das entregas)
      coalesce(nullif(regexp_extract(texto_status, 'Bloqueios: (.*)', 1), ''), texto_status) AS trecho_bloqueio,
      -- dias de impacto pelo padrão do texto (usado fora da IA)
      CASE
        WHEN lower(texto_status) LIKE '%impacto estimado: 1 semana%' THEN 7
        ELSE CAST(nullif(regexp_extract(lower(texto_status), 'impacto estimado de ([0-9]+) dias', 1), '') AS DOUBLE)
      END AS dias_pelo_texto
    FROM novos
  ),

  -- 1) regra: custo zero
  pela_regra AS (
    SELECT
      projeto_id, data_status, farol,
      CASE WHEN status_vazio THEN 'nao_reportado' ELSE 'sem_bloqueio' END AS causa_bloqueio,
      CAST(NULL AS STRING) AS bloqueio,
      CAST(NULL AS STRING) AS quem_destrava,
      dias_pelo_texto      AS dias_impacto,
      metodo, texto_status
    FROM com_metodo
    WHERE metodo = 'regra'
  ),

  -- 2) IA: as duas funções, na versão 2.0 (resultado VARIANT, lido em :response)
  pela_ia_bruto AS (
    SELECT
      *,
      ai_classify(
        trecho_bloqueio,
        '["change_freeze","falta_sre","dependencia_fornecedor","rotatividade","mudanca_escopo","bug_retrabalho","aprovacao_cliente","sem_bloqueio"]',
        map('version', '2.0')
      ) AS classificacao,
      -- schema tipado: dias_impacto já sai como número
      ai_extract(
        trecho_bloqueio,
        '{"bloqueio":{"type":"string"},"quem_destrava":{"type":"string"},"dias_impacto":{"type":"number","description":"dias de impacto no cronograma, 1 semana = 7"}}',
        map('version', '2.0')
      ) AS extracao
    FROM com_metodo
    WHERE metodo = 'ia'
  ),
  pela_ia AS (
    SELECT
      projeto_id, data_status, farol,
      classificacao:response[0]::STRING        AS causa_bloqueio,
      extracao:response:bloqueio::STRING       AS bloqueio,
      extracao:response:quem_destrava::STRING  AS quem_destrava,
      extracao:response:dias_impacto::DOUBLE   AS dias_impacto,
      metodo, texto_status
    FROM pela_ia_bruto
  ),

  -- 3) palavra-chave: o histórico antigo
  pela_palavra_chave AS (
    SELECT
      projeto_id, data_status, farol,
      CASE
        WHEN lower(trecho_bloqueio) RLIKE 'freeze|congelamento|janela de deploy'               THEN 'change_freeze'
        WHEN lower(trecho_bloqueio) RLIKE 'sre|infraestrutura|ambiente de homologação'         THEN 'falta_sre'
        WHEN lower(trecho_bloqueio) RLIKE 'forge|consultoria|fornecedor'                       THEN 'dependencia_fornecedor'
        WHEN lower(trecho_bloqueio) RLIKE 'saída de|rotatividade|onboarding'                   THEN 'rotatividade'
        WHEN lower(trecho_bloqueio) RLIKE 'escopo|change request|regra de negócio'             THEN 'mudanca_escopo'
        WHEN lower(trecho_bloqueio) RLIKE 'bugs|regressão|refazendo'                           THEN 'bug_retrabalho'
        WHEN lower(trecho_bloqueio) RLIKE 'aprovação do cliente|homologação do cliente'        THEN 'aprovacao_cliente'
        ELSE 'outro'
      END                  AS causa_bloqueio,
      CAST(NULL AS STRING) AS bloqueio,
      CAST(NULL AS STRING) AS quem_destrava,
      dias_pelo_texto      AS dias_impacto,
      metodo, texto_status
    FROM com_metodo
    WHERE metodo = 'palavra_chave'
  )

  SELECT * FROM pela_regra
  UNION ALL SELECT * FROM pela_ia
  UNION ALL SELECT * FROM pela_palavra_chave
) AS origem
ON destino.projeto_id = origem.projeto_id AND destino.data_status = origem.data_status
WHEN NOT MATCHED THEN INSERT (
  projeto_id, data_status, farol, causa_bloqueio, bloqueio, quem_destrava,
  dias_impacto, metodo, texto_status, _classificado_em
) VALUES (
  origem.projeto_id, origem.data_status, origem.farol, origem.causa_bloqueio, origem.bloqueio,
  origem.quem_destrava, origem.dias_impacto, origem.metodo, origem.texto_status, current_timestamp()
);


-- c) leitura: quantos status por método e causa
SELECT metodo, causa_bloqueio, count(*) AS status
FROM lakehouse_vertice.gold.status_estruturado
GROUP BY metodo, causa_bloqueio
ORDER BY metodo, status DESC;

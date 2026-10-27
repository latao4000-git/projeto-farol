-- Noite 4 · O agente que lê contrato
--
-- "Quais projetos estão atrasados?" a gold já responde. A pergunta seguinte do
-- dono é sempre outra: "E O QUE O CONTRATO DIZ?" Dá para cobrar multa da
-- consultoria que atrasou? Qual contrato renova sozinho se ninguém avisar?
--
-- A resposta está em 8 contratos em PDF no volume. Tudo em SQL, em 3 passos:
--   1. ai_parse_document   PDF → elementos (título de seção e texto), UMA vez     → silver.documentos_elementos
--   2. agrupar             cláusula por cláusula (o Genie cita a fonte)          → silver.contratos_clausulas
--   3. ai_extract          texto → colunas TIPADAS (número, data, booleano)      → gold.contratos
--
-- Na gold fica UMA tabela: um contrato por linha, com o que dá para somar e filtrar.
-- A multa da CodeForge e os avisos prévios vencendo são perguntas sobre ela (veja o fim).
--
-- A lição do passo 3: ai_extract SEM schema devolve texto ("0,5%", "sim"); COM schema
-- tipado devolve 0.5 e true — dado que dá para somar, comparar e filtrar.
--
-- Hoje do dataset: 16/10/2026. Custo medido no Free Edition: ~1 min para os 8 PDFs.

-- 1. PDF → elementos --------------------------------------------------------------
--    ai_parse_document é a chamada cara: roda uma vez e o resultado vira tabela.
CREATE OR REPLACE TABLE lakehouse_vertice.silver.documentos_elementos
COMMENT 'Elementos dos contratos em PDF extraídos com ai_parse_document: documento, ordem, tipo (title, section_header, text) e conteúdo.'
AS
WITH arquivos AS (
  SELECT path, content
  FROM read_files('/Volumes/lakehouse_vertice/bronze/raw/documentos/contratos/', format => 'binaryFile')
),
parseado AS (
  SELECT path,
         try_cast(ai_parse_document(content, map('version', '2.0')):document:elements AS ARRAY<VARIANT>) AS elementos
  FROM arquivos
)
SELECT regexp_extract(path, '([^/]+)\\.pdf$', 1)                AS documento,
       pos                                                      AS ordem,
       e:type::STRING                                           AS tipo,
       regexp_replace(trim(e:content::STRING), '\\s+', ' ')     AS conteudo,
       path                                                     AS arquivo
FROM parseado
LATERAL VIEW posexplode(elementos) AS pos, e;

-- 2. Uma linha por cláusula --------------------------------------------------------
--     Cada texto pertence ao último título de seção ("CLÁUSULA 6 - MULTA POR ATRASO") que veio antes dele.
CREATE OR REPLACE TABLE lakehouse_vertice.silver.contratos_clausulas
COMMENT 'Cláusulas dos contratos de fornecedor e SaaS da Vértice (uma linha por cláusula): fornecedor, número, título e texto. Use para citar o que o contrato diz sobre multa, SLA, renovação, aviso prévio, reajuste e rescisão.'
AS
WITH marcado AS (
  SELECT *,
         last_value(CASE WHEN tipo = 'section_header' THEN conteudo END, true)
           OVER (PARTITION BY documento ORDER BY ordem) AS secao
  FROM lakehouse_vertice.silver.documentos_elementos
),
fornecedor AS (
  SELECT documento, trim(regexp_extract(conteudo, 'CONTRATADA: (.+)$', 1)) AS fornecedor
  FROM lakehouse_vertice.silver.documentos_elementos
  WHERE conteudo LIKE 'CONTRATANTE:%'
)
SELECT f.fornecedor,
       CAST(regexp_extract(m.secao, 'CLÁUSULA ([0-9]+)', 1) AS INT)   AS clausula_numero,
       trim(regexp_extract(m.secao, 'CLÁUSULA [0-9]+ - (.+)$', 1))     AS titulo,
       concat_ws(' ', collect_list(m.conteudo))                         AS texto,
       m.documento
FROM marcado m
JOIN fornecedor f USING (documento)
WHERE m.tipo = 'text' AND m.secao LIKE 'CLÁUSULA%'
GROUP BY f.fornecedor, m.secao, m.documento;

-- 3a. A lição: ai_extract SEM schema devolve TEXTO ------------------------------------
--     (só leitura) Repare: '0,5%' e 'sim' são strings. Não dá para somar nem comparar.
SELECT f.fornecedor,
       ai_extract(t.texto, '["multa_atraso", "renovacao_automatica", "aviso_previo"]', map('version', '2.0')):response AS sem_schema
FROM (SELECT documento, concat_ws(' ', collect_list(conteudo)) AS texto
      FROM lakehouse_vertice.silver.documentos_elementos GROUP BY documento) t
JOIN (SELECT DISTINCT documento, fornecedor FROM lakehouse_vertice.silver.contratos_clausulas) f USING (documento)
LIMIT 3;

-- 3b. COM schema tipado: o contrato vira coluna ---------------------------------------
CREATE OR REPLACE TABLE lakehouse_vertice.gold.contratos
COMMENT 'Contratos de fornecedor e SaaS da Vértice (um por linha), extraídos por IA (ai_extract com JSON schema tipado): objeto, valor anual, fim da vigência, renovação automática, aviso prévio em dias, multa por atraso (% ao dia), teto da multa (%), SLA, índice de reajuste e o texto de todas as cláusulas. multa_atraso_pct_dia nulo = contrato sem multa por atraso. Data limite do aviso = data_fim_vigencia - aviso_previo_dias.'
AS
WITH texto AS (
  SELECT c.documento, c.fornecedor,
         concat_ws(' ', collect_list(concat('CLÁUSULA ', c.clausula_numero, ' - ', c.titulo, ': ', c.texto))) AS texto
  FROM lakehouse_vertice.silver.contratos_clausulas c
  GROUP BY c.documento, c.fornecedor
),
extraido AS (
  SELECT documento, fornecedor, texto,
         ai_extract(texto,
           '{"objeto":                {"type": "string",  "description": "o que o fornecedor presta, em poucas palavras, em português"},
             "valor_anual":           {"type": "number",  "description": "valor anual estimado do contrato, em reais (R$ 14.800.000,00 = 14800000)"},
             "data_fim_vigencia":     {"type": "string",  "description": "último dia da vigência, no formato AAAA-MM-DD"},
             "renovacao_automatica":  {"type": "boolean", "description": "true se o contrato renova sozinho sem manifestação das partes"},
             "aviso_previo_dias":     {"type": "integer", "description": "dias de antecedência do fim da vigência para avisar que NÃO vai renovar (ou para formalizar a renovação, se não for automática)"},
             "multa_atraso_pct_dia":  {"type": "number",  "description": "multa por atraso em % do valor da entrega por dia (0,5% = 0.5). Nulo se não há multa por atraso"},
             "teto_multa_pct":        {"type": "number",  "description": "limite máximo da multa em % do valor da entrega. Nulo se não há multa"},
             "sla":                   {"type": "string",  "description": "o nível de serviço que o fornecedor se obriga a cumprir, copiado do contrato, em português"},
             "reajuste":              {"type": "string",  "description": "índice de reajuste anual, ex.: IPCA"}}',
           map('version', '2.0')) AS j
  FROM texto
)
SELECT fornecedor,
       j:response:objeto::STRING                        AS objeto,
       CAST(j:response:valor_anual::DOUBLE AS DECIMAL(18,2)) AS valor_anual,
       try_to_date(j:response:data_fim_vigencia::STRING) AS data_fim_vigencia,
       j:response:renovacao_automatica::BOOLEAN         AS renovacao_automatica,
       j:response:aviso_previo_dias::INT                AS aviso_previo_dias,
       j:response:multa_atraso_pct_dia::DOUBLE          AS multa_atraso_pct_dia,
       j:response:teto_multa_pct::DOUBLE                AS teto_multa_pct,
       j:response:sla::STRING                           AS sla,
       j:response:reajuste::STRING                      AS reajuste,
       texto                                            AS clausulas,
       documento,
       current_timestamp()                              AS _extraido_em
FROM extraido;

-- 4. As duas perguntas do dono, direto na gold.contratos (só leitura) --------------
--    São as mesmas que o Genie "Farol · Diretoria + Contratos" responde.

-- 4a. Quanto dá para cobrar da consultoria que atrasou?
--     Multa = valor da entrega × % ao dia × dias de atraso, limitada ao teto do contrato.
--     Entregue com atraso: conta os dias até a entrega. Ainda em aberto: conta até hoje.
--     Só entra o que foi prometido nos 12 meses do contrato vigente (dá para descontar da fatura).
WITH atrasos AS (
  SELECT e.fornecedor, e.valor, e.data_prometida,
         CASE WHEN e.data_entrega IS NOT NULL THEN e.dias_de_atraso_na_entrega
              ELSE datediff(DATE'2026-10-16', e.data_prometida) END AS dias_de_atraso
  FROM lakehouse_vertice.silver.entregas_fornecedor e
  WHERE (e.data_entrega IS NOT NULL AND e.dias_de_atraso_na_entrega > 0) OR e.em_atraso
)
SELECT a.fornecedor,
       COUNT(*)                                                                                  AS entregas_atrasadas,
       ROUND(SUM(a.valor * least(a.dias_de_atraso * c.multa_atraso_pct_dia, c.teto_multa_pct) / 100), 2) AS multa_cobravel
FROM atrasos a
JOIN lakehouse_vertice.gold.contratos c ON lower(c.fornecedor) = lower(a.fornecedor)
WHERE c.multa_atraso_pct_dia IS NOT NULL
  AND a.data_prometida > add_months(c.data_fim_vigencia, -12)
GROUP BY a.fornecedor;

-- 4b. Qual contrato vence o aviso prévio (e renova sozinho) se ninguém fizer nada?
SELECT fornecedor, objeto, valor_anual, renovacao_automatica,
       date_sub(data_fim_vigencia, aviso_previo_dias)                             AS data_limite_aviso,
       datediff(date_sub(data_fim_vigencia, aviso_previo_dias), DATE'2026-10-16') AS dias_ate_limite
FROM lakehouse_vertice.gold.contratos
ORDER BY dias_ate_limite;

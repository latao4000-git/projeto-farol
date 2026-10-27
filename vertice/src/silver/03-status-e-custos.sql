-- silver.status_semanal e silver.custos.
--
-- O status de toda sexta (o histórico do avanço) e os lançamentos de custo
-- real (a base do CPI).


-- ---------------------------------------------------------------------------
-- status_semanal. Sujeiras #17 e #18.
-- ---------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW status_semanal (
  CONSTRAINT farol_conhecido EXPECT (farol IN ('verde', 'amarelo', 'vermelho')) ON VIOLATION FAIL UPDATE
)
COMMENT 'Status semanal que cada gerente preenche toda sexta: % concluído, farol (verde, amarelo ou vermelho) e o texto livre com os bloqueios. status_vazio marca o texto que não diz nada (vazio, N/A, ver ata da reunião).'
AS
SELECT
  projeto_id,
  to_date(data_status, 'yyyy-MM-dd')                      AS data_status,
  gerente,
  -- #17: 'Verde', 'VERDE' e 'verde' são o mesmo farol
  lower(trim(farol))                                      AS farol,
  CAST(pct_concluido AS INT)                              AS pct_concluido,
  texto_status,
  -- #18: o status vazio NÃO é descartado. A semana existiu, o gerente só
  -- não escreveu nada. A flag deixa a IA (prompt 4) pular esses textos.
  coalesce(trim(texto_status), '') IN ('', 'N/A', 'ver ata da reunião') AS status_vazio
FROM lakehouse_vertice.bronze.status_semanal;


-- ---------------------------------------------------------------------------
-- custos. Sujeiras #13 e #14.
-- ---------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW custos
COMMENT 'Lançamentos de custo real por projeto (pessoal, consultoria, cloud, licenças, despesas), em reais. Estornos ficam como valor negativo (estorno = true): o custo é líquido. semana é a sexta-feira da semana do lançamento.'
AS
SELECT
  lancamento_id,
  projeto_id,
  to_date(data, 'yyyy-MM-dd')                             AS data,
  -- a sexta da semana: date_trunc('WEEK') volta para a segunda, + 4 dias
  date_add(date_trunc('WEEK', to_date(data, 'yyyy-MM-dd')), 4) AS semana,
  categoria,
  descricao,
  -- #13: 671 valores com vírgula decimal. O replace vem ANTES do CAST.
  -- try_cast "funcionaria" e jogaria R$ 5,4 mi fora em silêncio.
  CAST(replace(valor, ',', '.') AS DECIMAL(18,2))         AS valor,
  -- #14: o estorno FICA (o custo é líquido), só é sinalizado
  CAST(replace(valor, ',', '.') AS DECIMAL(18,2)) < 0     AS estorno,
  -- rastro da correção #13: quantos valores chegaram com vírgula
  valor LIKE '%,%'                                        AS valor_veio_com_virgula,
  centro_custo
FROM lakehouse_vertice.bronze.custos;

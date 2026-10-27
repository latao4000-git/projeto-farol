-- silver.entregas_fornecedor: o que as consultorias prometeram x entregaram.
--
-- Sujeira #15: a mesma consultoria vem escrita de 4 jeitos
-- ('CodeForge Consultoria Ltda', 'Codeforge Consultoria',
--  'CODEFORGE CONSULTORIA LTDA', 'Code Forge Consultoria').
-- data_entrega vazia NÃO é sujeira: é entrega ainda em aberto.

CREATE OR REFRESH MATERIALIZED VIEW entregas_fornecedor
COMMENT 'Entregas das consultorias contratadas: item, valor, data do pedido, data prometida e data de entrega. Prazos em dias, atraso na entrega e as flags em_aberto (ainda não entregue) e em_atraso (em aberto com a data prometida antes de 16/10/2026). Fornecedor sem tabela gold: leia daqui.'
AS
WITH datas AS (
  SELECT
    *,
    to_date(data_pedido,    'yyyy-MM-dd') AS dt_pedido,
    to_date(data_prometida, 'yyyy-MM-dd') AS dt_prometida,
    to_date(data_entrega,   'yyyy-MM-dd') AS dt_entrega
  FROM lakehouse_vertice.bronze.entregas_fornecedor
)
SELECT
  entrega_id,
  projeto_id,
  -- sem espaço e em minúsculas, as 4 grafias viram 'codeforge...'
  CASE
    WHEN replace(lower(fornecedor), ' ', '') LIKE '%codeforge%' THEN 'CodeForge Consultoria Ltda'
    ELSE fornecedor
  END                                                     AS fornecedor,
  fornecedor                                              AS fornecedor_como_veio,
  item,
  CAST(valor AS DECIMAL(18,2))                            AS valor,
  dt_pedido                                               AS data_pedido,
  dt_prometida                                            AS data_prometida,
  dt_entrega                                              AS data_entrega,
  CAST(prazo_contratado_dias AS INT)                      AS prazo_contratado_dias,
  status,
  datediff(dt_prometida, dt_pedido)                       AS prazo_prometido_dias,
  datediff(dt_entrega,   dt_pedido)                       AS prazo_real_dias,
  -- só existe para o que já foi entregue (negativo = entregou antes)
  datediff(dt_entrega,   dt_prometida)                    AS dias_de_atraso_na_entrega,
  dt_entrega IS NULL                                      AS em_aberto,
  -- o "hoje" do dataset é 16/10/2026: nunca current_date()
  dt_entrega IS NULL AND dt_prometida < DATE'2026-10-16'  AS em_atraso
FROM datas;

-- Prompt 5 · Métricas governadas
--
-- Os KPIs da carteira definidos UMA vez só, numa metric view do Unity Catalog.
-- O dashboard e o Genie leem daqui: se a fórmula do SPI mudar, muda num lugar.
--
-- Fonte: a fotografia de hoje (gold.projeto_situacao_atual), só os projetos
-- em andamento. Os índices são sempre razão de somas (SUM(ev) / SUM(pv)),
-- nunca média dos índices: assim o projeto grande pesa mais que o pequeno.
--
-- ARMADILHA: a sql_task do job corta o arquivo em todo ponto e vírgula,
-- inclusive dentro do YAML. Por isso o YAML abaixo não tem nenhum.
-- E a indentação precisa chegar intacta: rode pelo job (sql_task) ou pela
-- API de statements, nunca pelo `aitools tools query`.

CREATE OR REPLACE VIEW lakehouse_vertice.gold.mv_projetos
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
comment: "KPIs governados da carteira da Vértice (projetos em andamento, fotografia de 16/10/2026). Use para totais de hoje. Para ranking de projetos use gold.projeto_situacao_atual."
source: lakehouse_vertice.gold.projeto_situacao_atual
filter: status = 'em_andamento'

dimensions:
  - name: projeto_id
    expr: projeto_id
    comment: "Código do projeto, por exemplo PRJ-011"
    synonyms: ["código do projeto", "id do projeto"]
  - name: projeto
    expr: projeto
    comment: "Código e nome do projeto juntos, para exibir"
    synonyms: ["nome do projeto"]
  - name: cliente
    expr: cliente
    synonyms: ["empresa cliente", "conta"]
  - name: segmento
    expr: segmento
    comment: "Segmento do cliente: varejo, financeiro, saude, logistica ou industria"
    synonyms: ["setor", "vertical", "mercado"]
  - name: ferramenta
    expr: ferramenta
    comment: "Onde o gerente controla o projeto: excel, clickup ou msproject"
    synonyms: ["sistema de origem", "ferramenta de gestão"]
  - name: situacao
    expr: situacao
    comment: "Regra de corte pelo pior índice: crítico se SPI ou CPI abaixo de 0,8, atenção abaixo de 0,9, senão ok"
    synonyms: ["status do projeto", "risco", "classificação"]
  - name: farol_do_gerente
    expr: farol_do_gerente
    comment: "Farol que o gerente declarou no último status semanal (verde, amarelo, vermelho)"
    synonyms: ["farol declarado", "farol do status"]
  - name: farol_calculado
    expr: farol_calculado
    comment: "Farol pelo número, regra do manual da Vértice: verde com SPI a partir de 0,95, amarelo a partir de 0,90, vermelho abaixo"
    synonyms: ["farol real", "farol pelo SPI"]
  - name: gerente_projeto
    expr: gerente_projeto
    synonyms: ["gerente", "gestor do projeto", "GP"]

measures:
  - name: projetos
    expr: COUNT(1)
    comment: "Quantidade de projetos em andamento"
    synonyms: ["quantidade de projetos", "número de projetos"]
  - name: carteira
    expr: SUM(valor_contrato)
    comment: "Soma do valor de contrato, em reais"
    synonyms: ["valor da carteira", "valor contratado", "receita contratada"]
  - name: spi
    expr: SUM(ev) / SUM(pv)
    comment: "Índice de prazo (EV dividido por PV). Abaixo de 1 é atraso"
    synonyms: ["índice de prazo", "schedule performance index"]
  - name: cpi
    expr: SUM(ev) / SUM(ac)
    comment: "Índice de custo (EV dividido por AC). Abaixo de 1 é estouro de custo"
    synonyms: ["índice de custo", "cost performance index"]
  - name: eac
    expr: SUM(eac)
    comment: "Estimativa no término: orçamento dividido pelo CPI, somado na carteira"
    synonyms: ["custo projetado", "estimate at completion"]
  - name: estouro_previsto
    expr: SUM(estouro_previsto)
    comment: "Quanto o EAC passa do orçamento, só nos projetos em que passa, em reais"
    synonyms: ["custo do atraso", "estouro de orçamento", "quanto vai custar"]
  - name: margem_projetada
    expr: (SUM(valor_contrato) - SUM(eac)) / SUM(valor_contrato)
    comment: "Margem no término: contrato menos EAC, dividido pelo contrato (0,20 = 20%)"
    synonyms: ["margem", "margem prevista"]
  - name: atraso_projetado_medio_dias
    expr: AVG(atraso_projetado_dias)
    comment: "Média de dias de atraso no término (duração baseline dividida pelo SPI, menos a duração baseline)"
    synonyms: ["atraso médio", "dias de atraso"]
  - name: projetos_em_risco
    expr: COUNT(1) FILTER (WHERE situacao IN ('crítico', 'atenção'))
    comment: "Projetos críticos mais os em atenção"
    synonyms: ["projetos atrasados", "projetos em atenção ou críticos"]
  - name: projetos_criticos
    expr: COUNT(1) FILTER (WHERE situacao = 'crítico')
    comment: "Projetos com SPI ou CPI abaixo de 0,8"
    synonyms: ["críticos", "projetos no vermelho"]
  - name: projetos_melancia
    expr: COUNT(1) FILTER (WHERE melancia)
    comment: "Verde por fora, vermelho por dentro: farol do gerente verde e SPI abaixo de 0,9"
    synonyms: ["melancias", "farol verde falso"]
$$

"""Gera o dashboard "Projeto Farol · Portfólio" (AI/BI) como código.

    python scripts/gerar_dashboard.py                      # escreve resources/dashboard-portfolio.lvdash.json
    python scripts/gerar_dashboard.py --testar --profile imersao-out26 [--warehouse ID]
                                                           # roda cada query no warehouse e mostra as linhas

Três páginas, uma para cada pergunta do dono que o dashboard responde:
  Portfólio     quais projetos atrasam e quanto isso custa (perguntas 1 e 2)
  Pessoas       tenho gente parada enquanto outro projeto pede gente? (pergunta 3)
  Fornecedores  quem atrasa as entregas (metade da pergunta 4)

Regras do formato (skill databricks-aibi-dashboards):
  - nas queries, as tabelas da gold vão com o nome PURO (catálogo e schema
    entram no deploy, pelo dataset_catalog/dataset_schema do bundle). A silver
    vai com o nome completo, porque o schema padrão do dashboard é a gold.
  - o "hoje" é DATE'2026-10-16', nunca current_date().

Cores (skill dataviz, validadas com validate_palette.js nos dois temas):
  - situação: crítico #FF5F46, atenção #F6C344, ok #22C2F4. Cor de status é
    reservada e nunca vai sozinha: a situação aparece escrita na legenda,
    no tooltip e na tabela.
  - séries e categorias: a paleta CATEGORICA abaixo, sempre na mesma ordem.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "resources" / "dashboard-portfolio.lvdash.json"

HOJE = "DATE'2026-10-16'"
CORTE = 0.9  # SPI ou CPI abaixo disso = atenção

COR_SITUACAO = {"crítico": "#FF5F46", "atenção": "#F6C344", "ok": "#22C2F4"}
# Azul da Jornada um passo mais claro (#0059DB some no fundo escuro: 2,8:1)
# e os tons médios da paleta de referência da dataviz. Passa nas 6 checagens
# no claro (#FFFFFF) e no escuro (#1C1C24). Não mude a ordem: ela é o que
# separa as cores para quem tem daltonismo.
CATEGORICA = ["#2F72E6", "#D95926", "#199E70", "#7B6BE0", "#D55181", "#C98500"]

TABELAS_GOLD = ["mv_projetos", "projeto_situacao_atual", "fato_projeto_semana",
                "utilizacao_pessoa_semana", "status_estruturado"]


# --------------------------------------------------------------------------
# Datasets: o SQL de cada um. Um dataset alimenta vários widgets sempre que
# dá: clicar num gráfico filtra os outros widgets do mesmo dataset.
# --------------------------------------------------------------------------
DATASETS = {
    # Os KPIs saem da metric view: a fórmula mora num lugar só.
    "ds_kpis": ("KPIs da carteira (mv_projetos)", """
SELECT MEASURE(carteira)          AS carteira,
       MEASURE(estouro_previsto)  AS estouro_previsto,
       MEASURE(spi)               AS spi,
       MEASURE(cpi)               AS cpi,
       MEASURE(projetos)          AS projetos,
       MEASURE(projetos_em_risco) AS projetos_em_risco,
       MEASURE(projetos_criticos) AS projetos_criticos,
       MEASURE(projetos_melancia) AS projetos_melancia
FROM mv_projetos
"""),
    # A fotografia de hoje, um projeto por linha: barra, dispersão e tabela.
    "ds_projetos": ("Projetos em andamento", """
SELECT projeto_id,
       projeto,
       cliente,
       segmento,
       situacao,
       farol_do_gerente,
       farol_calculado,
       CASE WHEN melancia THEN 'sim' ELSE '' END AS melancia,
       spi,
       cpi,
       valor_contrato,
       CAST(ROUND(estouro_previsto) AS BIGINT)     AS estouro_previsto,
       CAST(ROUND(atraso_projetado_dias) AS INT)   AS atraso_projetado_dias,
       margem_projetada
FROM projeto_situacao_atual
WHERE status = 'em_andamento'
ORDER BY CASE situacao WHEN 'crítico' THEN 1 WHEN 'atenção' THEN 2 ELSE 3 END, spi
"""),
    # SPI e CPI da carteira semana a semana. PV, EV e AC são acumulados no
    # fato: soma-se os projetos de cada semana, nunca as semanas entre si.
    # As primeiras semanas (dez/2024) têm de 1 a 9 projetos e SPI zerado:
    # ruído que achataria o gráfico. O HAVING começa a série com a carteira
    # formada (10+ projetos), e o try_divide evita a divisão por zero (o Spark
    # calcula o SELECT antes de aplicar o HAVING).
    "ds_semanal": ("SPI e CPI semanais da carteira", """
SELECT semana,
       try_divide(SUM(ev), SUM(pv))                    AS spi,
       CAST(try_divide(SUM(ev), SUM(ac)) AS DOUBLE)    AS cpi
FROM fato_projeto_semana
GROUP BY semana
HAVING COUNT(*) >= 10 AND SUM(pv) > 0 AND SUM(ac) > 0
ORDER BY semana
"""),
    # 12 semanas = as sextas depois de 24/07/2026, até hoje.
    "ds_pessoas_paradas": ("Top 15 pessoas por custo da hora parada (12 semanas)", f"""
SELECT colaborador_id,
       concat(nome, ' · ', papel)                      AS pessoa,
       papel,
       SUM(custo_ocioso)                               AS custo_ocioso,
       SUM(horas_ociosas)                              AS horas_ociosas,
       SUM(horas_apontadas) / SUM(horas_disponiveis)   AS utilizacao
FROM utilizacao_pessoa_semana
WHERE semana > date_sub({HOJE}, 84)
GROUP BY colaborador_id, nome, papel
ORDER BY custo_ocioso DESC
LIMIT 15
"""),
    "ds_utilizacao": ("Utilização por pessoa e projeto (12 semanas)", f"""
SELECT colaborador_id,
       nome,
       papel,
       senioridade,
       projeto_id,
       CAST(ROUND(SUM(horas_disponiveis)) AS INT)      AS horas_disponiveis,
       CAST(ROUND(SUM(horas_apontadas)) AS INT)        AS horas_apontadas,
       SUM(horas_apontadas) / SUM(horas_disponiveis)   AS utilizacao,
       CAST(ROUND(SUM(custo_ocioso)) AS BIGINT)        AS custo_ocioso,
       MAX(spi_do_projeto)                             AS spi_do_projeto
FROM utilizacao_pessoa_semana
WHERE semana > date_sub({HOJE}, 84)
GROUP BY colaborador_id, nome, papel, senioridade, projeto_id
ORDER BY utilizacao, custo_ocioso DESC
"""),
    # Só status COM bloqueio dos últimos 90 dias, nos 15 projetos que mais
    # travaram (49 projetos num gráfico de barras não se leem).
    "ds_bloqueios": ("Causas de bloqueio por projeto (90 dias)", f"""
WITH bloqueios AS (
  SELECT projeto_id, causa_bloqueio
  FROM status_estruturado
  WHERE data_status > date_sub({HOJE}, 90)
    AND causa_bloqueio NOT IN ('sem_bloqueio', 'nao_reportado')
),
mais_travados AS (
  SELECT projeto_id
  FROM bloqueios
  GROUP BY projeto_id
  ORDER BY COUNT(*) DESC, projeto_id
  LIMIT 15
)
SELECT b.projeto_id,
       CASE b.causa_bloqueio
         WHEN 'mudanca_escopo'         THEN 'Mudança de escopo'
         WHEN 'bug_retrabalho'         THEN 'Bug e retrabalho'
         WHEN 'aprovacao_cliente'      THEN 'Aprovação do cliente'
         WHEN 'dependencia_fornecedor' THEN 'Fornecedor'
         WHEN 'falta_sre'              THEN 'Falta de SRE'
         WHEN 'rotatividade'           THEN 'Rotatividade'
         ELSE b.causa_bloqueio
       END AS causa,
       COUNT(*) AS status_com_bloqueio
FROM bloqueios b
JOIN mais_travados USING (projeto_id)
GROUP BY ALL
"""),
    # Prazo real ÷ prometido é a média por entrega (a mesma conta da verificação).
    "ds_fornecedores": ("Fornecedores", """
SELECT fornecedor,
       COUNT(DISTINCT fornecedor_como_veio)                AS grafias_no_cadastro,
       COUNT(*)                                            AS entregas,
       AVG(prazo_real_dias / prazo_prometido_dias)         AS prazo_real_sobre_prometido,
       AVG(CASE WHEN data_entrega <= data_prometida THEN 1.0 ELSE 0.0 END)
         FILTER (WHERE data_entrega IS NOT NULL)           AS pct_no_prazo,
       COUNT_IF(em_atraso)                                 AS em_atraso_hoje,
       CAST(ROUND(SUM(valor)) AS BIGINT)                   AS valor_contratado
FROM lakehouse_vertice.silver.entregas_fornecedor
GROUP BY fornecedor
ORDER BY prazo_real_sobre_prometido DESC
"""),
    "ds_entregas_atrasadas": ("Entregas em atraso hoje", f"""
SELECT entrega_id,
       projeto_id,
       fornecedor,
       fornecedor_como_veio,
       item,
       CAST(ROUND(valor) AS BIGINT) AS valor,
       data_pedido,
       data_prometida,
       datediff({HOJE}, data_prometida) AS dias_em_atraso
FROM lakehouse_vertice.silver.entregas_fornecedor
WHERE em_atraso
ORDER BY dias_em_atraso DESC
"""),
}


# --------------------------------------------------------------------------
# Peças dos widgets
# --------------------------------------------------------------------------
REAIS = {"type": "number-currency", "currencyCode": "BRL", "abbreviation": "compact",
         "decimalPlaces": {"type": "max", "places": 2}}
# Nas tabelas só o number-percent foi respeitado (medido em 21/10/2026): horas e
# reais saem arredondados do próprio SQL, e o "(R$)" vai no título da coluna.
REAIS_INTEIRO = {"type": "number-currency", "currencyCode": "BRL",
                 "decimalPlaces": {"type": "max", "places": 0}}
INDICE = {"type": "number-plain", "decimalPlaces": {"type": "max", "places": 2}}
PCT = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 1}}
INTEIRO = {"type": "number-plain", "decimalPlaces": {"type": "max", "places": 0}}


def campo(nome, expressao=None):
    return {"name": nome, "expression": expressao or f"`{nome}`"}


def consulta(dataset, campos, agregado=False, filtros=None):
    q = {"datasetName": dataset, "fields": campos, "disaggregated": not agregado}
    if filtros:
        q["filters"] = [{"expression": f} for f in filtros]
    return [{"name": "main_query", "query": q}]


def quadro(titulo, descricao=None):
    f = {"title": titulo, "showTitle": True}
    if descricao:
        f.update(description=descricao, showDescription=True)
    return f


def posicao(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def texto(nome, linhas, x, y, w, h):
    return {"widget": {"name": nome, "multilineTextboxSpec": {"lines": linhas}},
            "position": posicao(x, y, w, h)}


def kpi(nome, titulo, coluna, formato, x, y, w, descricao=None):
    valor = {"fieldName": coluna, "displayName": titulo}
    if formato:
        valor["format"] = formato
    return {"widget": {
        "name": nome,
        "queries": consulta("ds_kpis", [campo(coluna)]),
        "spec": {"version": 2, "widgetType": "counter",
                 "encodings": {"value": valor},
                 "frame": quadro(titulo, descricao)}},
        "position": posicao(x, y, w, 3)}


def cor_por_situacao():
    return {"fieldName": "situacao", "displayName": "Situação",
            "scale": {"type": "categorical",
                      "sort": {"by": "custom-order", "orderedValues": list(COR_SITUACAO)},
                      "mappings": [{"value": v, "color": c} for v, c in COR_SITUACAO.items()]}}


def linha_de_corte(eixo, valor=CORTE, rotulo="corte: atenção (0,9)"):
    tipo = "horizontal-line" if eixo == "y" else "vertical-line"
    return {"type": tipo, "encodings": {
        eixo: {"dataValue": str(valor), "dataType": "DOUBLE"},
        "label": {"value": rotulo},
        "color": {"value": "#8A8F98"}}}


def coluna(nome, titulo, formato=None, regras=None):
    c = {"fieldName": nome, "displayName": titulo}
    if formato:
        c["format"] = formato
    if regras:
        c["style"] = {"type": "basic", "rules": regras}
    return c


def regra(operador, valor, cor):
    return {"condition": {"operand": {"type": "data-value", "value": str(valor)},
                          "operator": operador},
            "backgroundColor": cor}


# Índice abaixo de 0,8 pinta de crítico, abaixo de 0,9 de atenção (a 1ª regra que casa vale).
REGRAS_INDICE = [regra("<", 0.8, COR_SITUACAO["crítico"]), regra("<", CORTE, COR_SITUACAO["atenção"])]


# --------------------------------------------------------------------------
# Página 1 · Portfólio
# --------------------------------------------------------------------------
def pagina_portfolio():
    w = [
        texto("titulo_portfolio", [
            "# Projeto Farol · Portfólio\n", "\n",
            "Fotografia de **16/10/2026** dos projetos em andamento. Regra de corte: SPI ou CPI "
            "abaixo de **0,9 = atenção**, abaixo de **0,8 = crítico**. Os KPIs vêm da metric view "
            "`gold.mv_projetos`."], 0, 0, 12, 2),
        # Linha 1: dinheiro e índices. Linha 2: contagens.
        kpi("kpi_carteira", "Carteira em andamento", "carteira", REAIS, 0, 2, 3,
            "Soma dos contratos"),
        kpi("kpi_estouro", "Estouro previsto", "estouro_previsto", REAIS, 3, 2, 3,
            "EAC acima do orçamento"),
        kpi("kpi_spi", "SPI da carteira", "spi", INDICE, 6, 2, 3,
            "Prazo: abaixo de 1 é atraso"),
        kpi("kpi_cpi", "CPI da carteira", "cpi", INDICE, 9, 2, 3,
            "Custo: abaixo de 1 é estouro"),
        kpi("kpi_risco", "Projetos em risco", "projetos_em_risco", None, 0, 5, 4,
            "Críticos + em atenção"),
        kpi("kpi_criticos", "Críticos", "projetos_criticos", None, 4, 5, 4,
            "SPI ou CPI abaixo de 0,8"),
        kpi("kpi_melancias", "Melancias", "projetos_melancia", None, 8, 5, 4,
            "Farol do gerente verde, SPI abaixo de 0,9"),

        # Barra horizontal: quem mais vai estourar. Só quem estoura (> 0).
        {"widget": {
            "name": "barra_estouro",
            "queries": consulta("ds_projetos", [
                campo("projeto_id"), campo("situacao"),
                campo("sum(estouro_previsto)", "SUM(`estouro_previsto`)")],
                agregado=True, filtros=["`estouro_previsto` > 0"]),
            "spec": {"version": 3, "widgetType": "bar",
                     "encodings": {
                         "x": {"fieldName": "sum(estouro_previsto)", "displayName": "Estouro previsto",
                               "scale": {"type": "quantitative"}, "format": REAIS},
                         "y": {"fieldName": "projeto_id", "displayName": "Projeto",
                               "scale": {"type": "categorical", "sort": {"by": "x-reversed"}}},
                         "color": cor_por_situacao()},
                     "frame": quadro("Estouro previsto por projeto",
                                     "Só os projetos cujo EAC passa do orçamento")}},
            "position": posicao(0, 8, 6, 9)},

        # Dispersão SPI × CPI com as linhas de corte: o quadrante de baixo à
        # esquerda é atraso E estouro.
        {"widget": {
            "name": "dispersao_spi_cpi",
            "queries": consulta("ds_projetos", [
                campo("spi"), campo("cpi"), campo("situacao"), campo("projeto"),
                campo("estouro_previsto")]),
            "spec": {"version": 3, "widgetType": "scatter",
                     "encodings": {
                         "x": {"fieldName": "spi", "displayName": "SPI (prazo)",
                               "scale": {"type": "quantitative"}, "format": INDICE},
                         "y": {"fieldName": "cpi", "displayName": "CPI (custo)",
                               "scale": {"type": "quantitative"}, "format": INDICE},
                         "color": cor_por_situacao(),
                         "extra": [{"fieldName": "projeto", "displayName": "Projeto"},
                                   {"fieldName": "estouro_previsto", "displayName": "Estouro previsto",
                                    "format": REAIS}]},
                     "annotations": [linha_de_corte("x"), linha_de_corte("y")],
                     "frame": quadro("SPI × CPI por projeto",
                                     "Abaixo e à esquerda das linhas: atrasado e estourando")}},
            "position": posicao(6, 8, 6, 9)},

        # A tendência da carteira: dois índices na MESMA escala, um eixo só.
        {"widget": {
            "name": "linha_spi_cpi_semanal",
            "queries": consulta("ds_semanal", [campo("semana"), campo("spi"), campo("cpi")]),
            "spec": {"version": 3, "widgetType": "line",
                     "encodings": {
                         "x": {"fieldName": "semana", "displayName": "Semana",
                               "scale": {"type": "temporal"}},
                         "y": {"scale": {"type": "quantitative"}, "format": INDICE,
                               "fields": [{"fieldName": "spi", "displayName": "SPI"},
                                          {"fieldName": "cpi", "displayName": "CPI"}]}},
                     "annotations": [linha_de_corte("y")],
                     "frame": quadro("SPI e CPI da carteira, semana a semana",
                                     "Σ EV ÷ Σ PV e Σ EV ÷ Σ AC dos projetos ativos em cada sexta")}},
            "position": posicao(0, 17, 12, 6)},

        # O detalhe: o farol do gerente ao lado do farol pelo número.
        {"widget": {
            "name": "tabela_projetos",
            "queries": consulta("ds_projetos", [campo(c) for c in (
                "projeto", "cliente", "segmento", "situacao", "farol_do_gerente",
                "farol_calculado", "melancia", "spi", "cpi", "estouro_previsto",
                "atraso_projetado_dias")]),
            "spec": {"version": 2, "widgetType": "table",
                     "encodings": {"columns": [
                         coluna("projeto", "Projeto"),
                         coluna("cliente", "Cliente"),
                         coluna("segmento", "Segmento"),
                         coluna("situacao", "Situação"),
                         coluna("farol_do_gerente", "Farol do gerente"),
                         coluna("farol_calculado", "Farol pelo número"),
                         coluna("melancia", "Melancia?"),
                         coluna("spi", "SPI", INDICE, REGRAS_INDICE),
                         coluna("cpi", "CPI", INDICE, REGRAS_INDICE),
                         coluna("estouro_previsto", "Estouro previsto (R$)", REAIS_INTEIRO),
                         coluna("atraso_projetado_dias", "Atraso projetado (dias)", INTEIRO)]},
                     "frame": quadro("Projetos em andamento",
                                     "Críticos primeiro. Melancia = o gerente diz verde, o número diz atraso")}},
            "position": posicao(0, 23, 12, 10)},
    ]
    return {"name": "portfolio", "displayName": "Portfólio", "pageType": "PAGE_TYPE_CANVAS",
            "layoutVersion": "GRID_V1", "layout": w}


# --------------------------------------------------------------------------
# Página 2 · Pessoas
# --------------------------------------------------------------------------
def pagina_pessoas():
    causas = ["Mudança de escopo", "Bug e retrabalho", "Aprovação do cliente",
              "Fornecedor", "Falta de SRE", "Rotatividade"]
    w = [
        texto("titulo_pessoas", [
            "# Pessoas\n", "\n",
            "Tenho gente parada enquanto outro projeto pede gente? Horas paradas das "
            "**últimas 12 semanas** (timesheet) ao lado do que os gerentes dizem que trava "
            "o projeto (status semanal dos **últimos 90 dias**, classificado pela IA)."], 0, 0, 12, 2),

        {"widget": {
            "name": "barra_pessoas_paradas",
            "queries": consulta("ds_pessoas_paradas", [
                campo("pessoa"), campo("custo_ocioso"), campo("utilizacao"), campo("horas_ociosas")]),
            "spec": {"version": 3, "widgetType": "bar",
                     "encodings": {
                         "x": {"fieldName": "custo_ocioso", "displayName": "Custo da hora parada",
                               "scale": {"type": "quantitative"}, "format": REAIS},
                         "y": {"fieldName": "pessoa", "displayName": "Pessoa",
                               "scale": {"type": "categorical", "sort": {"by": "x-reversed"}}},
                         "extra": [{"fieldName": "utilizacao", "displayName": "Utilização", "format": PCT},
                                   {"fieldName": "horas_ociosas", "displayName": "Horas paradas",
                                    "format": INTEIRO}]},
                     "frame": quadro("Top 15 pessoas por custo da hora parada",
                                     "Horas disponíveis sem apontamento × custo/hora, 12 semanas")}},
            "position": posicao(0, 2, 6, 9)},

        {"widget": {
            "name": "barra_causas_bloqueio",
            "queries": consulta("ds_bloqueios", [
                campo("projeto_id"), campo("causa"),
                campo("sum(status_com_bloqueio)", "SUM(`status_com_bloqueio`)")], agregado=True),
            "spec": {"version": 3, "widgetType": "bar",
                     "encodings": {
                         "x": {"fieldName": "sum(status_com_bloqueio)", "displayName": "Status com bloqueio",
                               "scale": {"type": "quantitative"}},
                         "y": {"fieldName": "projeto_id", "displayName": "Projeto",
                               "scale": {"type": "categorical", "sort": {"by": "x-reversed"}}},
                         # Cor segue a causa, nunca a posição: a ordem é fixa.
                         "color": {"fieldName": "causa", "displayName": "Causa",
                                   "scale": {"type": "categorical",
                                             "sort": {"by": "custom-order", "orderedValues": causas},
                                             "mappings": [{"value": v, "color": c}
                                                          for v, c in zip(causas, CATEGORICA)]}}},
                     "frame": quadro("Causas de bloqueio por projeto",
                                     "Os 15 projetos com mais status bloqueados, últimos 90 dias")}},
            "position": posicao(6, 2, 6, 9)},

        {"widget": {
            "name": "tabela_utilizacao",
            "queries": consulta("ds_utilizacao", [campo(c) for c in (
                "colaborador_id", "nome", "papel", "senioridade", "projeto_id", "horas_disponiveis",
                "horas_apontadas", "utilizacao", "custo_ocioso", "spi_do_projeto")]),
            "spec": {"version": 2, "widgetType": "table",
                     "encodings": {"columns": [
                         coluna("colaborador_id", "Matrícula"),
                         coluna("nome", "Nome"),
                         coluna("papel", "Papel"),
                         coluna("senioridade", "Senioridade"),
                         coluna("projeto_id", "Projeto"),
                         coluna("horas_disponiveis", "Horas disponíveis", INTEIRO),
                         coluna("horas_apontadas", "Horas apontadas", INTEIRO),
                         coluna("utilizacao", "Utilização", PCT,
                                [regra("<", 0.2, COR_SITUACAO["crítico"])]),
                         coluna("custo_ocioso", "Custo da hora parada (R$)", REAIS_INTEIRO),
                         coluna("spi_do_projeto", "SPI do projeto", INDICE, REGRAS_INDICE)]},
                     "frame": quadro("Utilização por pessoa e projeto (12 semanas)",
                                     "Menos usados primeiro. Abaixo de 20% = gente parada")}},
            "position": posicao(0, 11, 12, 10)},
    ]
    return {"name": "pessoas", "displayName": "Pessoas", "pageType": "PAGE_TYPE_CANVAS",
            "layoutVersion": "GRID_V1", "layout": w}


# --------------------------------------------------------------------------
# Página 3 · Fornecedores
# --------------------------------------------------------------------------
def pagina_fornecedores():
    w = [
        texto("titulo_fornecedores", [
            "# Fornecedores\n", "\n",
            "Quem atrasa as entregas das consultorias. Prazo real ÷ prometido acima de 1 = "
            "entrega mais devagar do que prometeu. Uma consultoria aparece com várias grafias "
            "no cadastro: a silver já juntou."], 0, 0, 12, 2),

        {"widget": {
            "name": "tabela_fornecedores",
            "queries": consulta("ds_fornecedores", [campo(c) for c in (
                "fornecedor", "grafias_no_cadastro", "entregas", "prazo_real_sobre_prometido",
                "pct_no_prazo", "em_atraso_hoje", "valor_contratado")]),
            "spec": {"version": 2, "widgetType": "table",
                     "encodings": {"columns": [
                         coluna("fornecedor", "Fornecedor"),
                         coluna("grafias_no_cadastro", "Grafias no cadastro", INTEIRO),
                         coluna("entregas", "Entregas", INTEIRO),
                         coluna("prazo_real_sobre_prometido", "Prazo real ÷ prometido", INDICE,
                                [regra(">", 1.2, COR_SITUACAO["crítico"]),
                                 regra(">", 1.0, COR_SITUACAO["atenção"])]),
                         coluna("pct_no_prazo", "% no prazo", PCT),
                         coluna("em_atraso_hoje", "Em atraso hoje", INTEIRO,
                                [regra(">", 0, COR_SITUACAO["crítico"])]),
                         coluna("valor_contratado", "Valor das entregas (R$)", REAIS_INTEIRO)]},
                     "frame": quadro("Desempenho por fornecedor",
                                     "Fonte: silver.entregas_fornecedor")}},
            "position": posicao(0, 2, 12, 6)},

        {"widget": {
            "name": "tabela_entregas_atrasadas",
            "queries": consulta("ds_entregas_atrasadas", [campo(c) for c in (
                "entrega_id", "projeto_id", "fornecedor", "fornecedor_como_veio", "item",
                "valor", "data_pedido", "data_prometida", "dias_em_atraso")]),
            "spec": {"version": 2, "widgetType": "table",
                     "encodings": {"columns": [
                         coluna("entrega_id", "Entrega"),
                         coluna("projeto_id", "Projeto"),
                         coluna("fornecedor", "Fornecedor"),
                         coluna("fornecedor_como_veio", "Como veio no cadastro"),
                         coluna("item", "Item"),
                         coluna("valor", "Valor (R$)", REAIS_INTEIRO),
                         coluna("data_pedido", "Pedido em"),
                         coluna("data_prometida", "Prometida para"),
                         coluna("dias_em_atraso", "Dias em atraso", INTEIRO)]},
                     "frame": quadro("Entregas em atraso hoje",
                                     "Prometidas antes de 16/10/2026 e ainda não entregues")}},
            "position": posicao(0, 8, 12, 6)},
    ]
    return {"name": "fornecedores", "displayName": "Fornecedores", "pageType": "PAGE_TYPE_CANVAS",
            "layoutVersion": "GRID_V1", "layout": w}


def dashboard():
    return {
        "datasets": [{"name": nome, "displayName": titulo,
                      "queryLines": [l + "\n" for l in sql.strip().splitlines()]}
                     for nome, (titulo, sql) in DATASETS.items()],
        "pages": [pagina_portfolio(), pagina_pessoas(), pagina_fornecedores()],
        "uiSettings": {"theme": {
            # Cores da Jornada: azul #0059DB no claro, ciano #22C2F4 no escuro, fundo #14141A.
            "canvasBackgroundColor": {"light": "#F5F6F8", "dark": "#14141A"},
            "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#1C1C24"},
            "widgetBorderColor": {"light": "#FFFFFF", "dark": "#1C1C24"},
            "fontColor": {"light": "#14141A", "dark": "#F0F1F5"},
            "selectionColor": {"light": "#0059DB", "dark": "#22C2F4"},
            "visualizationColors": CATEGORICA,
            "widgetHeaderAlignment": "LEFT",
            "widgetCornerRadius": 8}},
    }


# --------------------------------------------------------------------------
# --testar: roda cada query no warehouse (com o catálogo na frente das
# tabelas da gold, porque fora do dashboard ninguém preenche o schema)
# --------------------------------------------------------------------------
def com_catalogo(sql):
    padrao = r"(?<![.\w])(" + "|".join(TABELAS_GOLD) + r")\b"
    return re.sub(padrao, r"lakehouse_vertice.gold.\1", sql)


def testar(profile, warehouse):
    falhas = 0
    for nome, (titulo, sql) in DATASETS.items():
        corpo = json.dumps({"warehouse_id": warehouse, "statement": com_catalogo(sql),
                            "wait_timeout": "50s", "format": "JSON_ARRAY"})
        saida = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements",
                                "--json", corpo, "--profile", profile],
                               capture_output=True, text=True, encoding="utf-8")
        try:
            r = json.loads(saida.stdout)
        except json.JSONDecodeError:
            r = {"status": {"state": "ERRO", "error": {"message": saida.stderr.strip()}}}
        estado = r.get("status", {}).get("state")
        if estado == "SUCCEEDED":
            linhas = r.get("manifest", {}).get("total_row_count", 0)
            print(f"  ok     {nome:24} {linhas:>5} linhas   {titulo}")
            if linhas == 0:
                falhas += 1
        else:
            falhas += 1
            msg = r.get("status", {}).get("error", {}).get("message", "")
            print(f"  FALHOU {nome:24} {estado}: {msg[:300]}")
    return falhas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--testar", action="store_true", help="roda cada query e mostra as linhas")
    ap.add_argument("--profile", default="imersao-out26")
    ap.add_argument("--warehouse", default="7b2456d0fa260c04")
    args = ap.parse_args()

    if args.testar:
        print(f"Testando {len(DATASETS)} queries no warehouse {args.warehouse}:")
        return 1 if testar(args.profile, args.warehouse) else 0

    SAIDA.write_text(json.dumps(dashboard(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok: {SAIDA.relative_to(RAIZ)} ({len(DATASETS)} datasets, 3 páginas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

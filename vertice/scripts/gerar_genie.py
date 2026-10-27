#!/usr/bin/env python3
"""Gera o Genie Agent do Projeto Farol (noite 2) como JSON versionado.

Uso:  python3 vertice/scripts/gerar_genie.py

Escreve resources/farol.geniespace.json, que o bundle publica no deploy
(resources/genie.genie_space.yml). O modelo de IA é o mesmo da noite 1: o que
muda é tudo que está embaixo dele — as 3 ferramentas integradas, gold com
COMMENT em toda tabela, métricas governadas e estas instruções.
"""
from __future__ import annotations

import json
import pathlib

SAIDA = pathlib.Path(__file__).resolve().parents[1] / "resources" / "farol.geniespace.json"
G = "lakehouse_vertice.gold"
S = "lakehouse_vertice.silver"


def ident(prefixo: str, n: int) -> str:
    return f"{prefixo}{n:0{32 - len(prefixo)}d}"   # 32 caracteres hex, únicos e ordenados


INSTRUCOES = [
    "Você é o analista da Torre de Controle (Projeto Farol) da Vértice Tecnologia, empresa de tecnologia com 520 pessoas e 60 projetos de clientes (varejo, financeiro, saúde, logística, indústria). Quem pergunta é o dono da empresa ou alguém da diretoria. Responda em português, com números em reais (R$) e índices com 2 casas.",
    "HOJE é 16/10/2026 (sexta-feira). Nunca use current_date(). 'Últimos 90 dias' = data >= DATE'2026-07-18'; 'últimas 12 semanas' = semana > DATE'2026-07-24'; 'últimas 8 semanas' = semana > DATE'2026-08-21'; 'próximo mês' = de 16/10/2026 a 15/11/2026.",
    "Definições: SPI = EV / PV (abaixo de 1 é atraso). CPI = EV / AC (abaixo de 1 é estouro de custo). EAC = orçamento / CPI. Estouro previsto = EAC - orçamento, só quando positivo. Regras de corte: SPI ou CPI < 0,9 = atenção; < 0,8 = crítico. 'Atrasado' = situação atenção ou crítico.",
    "Para SPI, CPI, EAC, estouro, margem, atraso projetado e contagem de projetos em risco HOJE, use a metric view mv_projetos com MEASURE(), ou a tabela projeto_situacao_atual filtrando status = 'em_andamento'. Projetos concluídos nunca entram em contagens de risco nem no estouro previsto.",
    "Para evolução no tempo use fato_projeto_semana. PV, EV e AC em fato_projeto_semana são ACUMULADOS até a semana: nunca some semanas diferentes do mesmo projeto.",
    "Farol: farol_do_gerente é o que o gerente publicou; farol_calculado segue a regra do manual (verde com SPI >= 0,95, amarelo >= 0,90, vermelho abaixo). 'Melancia' = farol do gerente verde com SPI < 0,9 (coluna melancia em projeto_situacao_atual).",
    "'Por que o projeto X atrasou?': use status_estruturado (causa_bloqueio, bloqueio, quem_destrava, dias_impacto), contando as causas dos últimos 90 dias e ignorando 'sem_bloqueio' e 'nao_reportado'. Mostre também o SPI de projeto_situacao_atual. Se a causa for falta_sre, procure SREs com utilização abaixo de 20% em outros projetos (utilizacao_pessoa_semana, papel = 'sre').",
    "Gente parada: utilizacao_pessoa_semana (utilizacao, horas_ociosas, custo_ocioso, papel). Utilização baixa = abaixo de 20% nas últimas 12 semanas. Agrupe por pessoa e projeto e calcule SUM(horas_apontadas) / SUM(horas_disponiveis).",
    "O que vai dar errado no próximo mês: (1) entregas de consultoria em atraso (silver.entregas_fornecedor com em_atraso = true); (2) o change freeze de varejo começa em 01/11/2026 e trava deploy até 10/01/2027 nos projetos de e-commerce (tipo_projeto com e-commerce, checkout ou marketplace) ainda em andamento. Junte os dois quando a pergunta for sobre o futuro.",
    "Fornecedores: silver.entregas_fornecedor (o nome já está normalizado; prazo_real_dias / prazo_prometido_dias = fator de atraso; em_atraso = prometida antes de hoje e não entregue). Agrupe por fornecedor.",
    "Quando perguntarem por projeto, responda com projeto_id (ex.: PRJ-011), o nome e o cliente.",
    "Rankings de projeto (maior estouro, pior SPI, maior atraso): use a tabela projeto_situacao_atual com WHERE status = 'em_andamento', ORDER BY e LIMIT. A metric view mv_projetos serve para totais da carteira, não para ranking.",
    "Pergunta no singular ('qual fornecedor', 'qual projeto') pede UMA linha: ORDER BY ... LIMIT 1. Change freeze: todo projeto de e-commerce, checkout ou marketplace em andamento é afetado, sem filtrar por data de término (o freeze trava deploy, inclusive de correção).",
    "Quando perguntarem QUAIS CLIENTES, devolva cada cliente uma vez só (SELECT DISTINCT cliente ou GROUP BY cliente), com a quantidade de projetos dele na situação perguntada.",
]

EXEMPLOS = [
    ("Quais projetos estão atrasados, e de quais clientes?",
     f"SELECT projeto_id, nome_projeto, cliente, ferramenta, situacao, ROUND(spi, 2) AS spi, ROUND(cpi, 2) AS cpi, atraso_projetado_dias "
     f"FROM {G}.projeto_situacao_atual WHERE status = 'em_andamento' AND situacao IN ('crítico', 'atenção') ORDER BY least(spi, cpi)"),
    ("Quanto esse atraso vai me custar?",
     f"SELECT MEASURE(estouro_previsto) AS estouro_previsto, MEASURE(projetos_em_risco) AS projetos_em_risco, "
     f"MEASURE(margem_projetada) AS margem_projetada FROM {G}.mv_projetos"),
    ("Tenho gente parada enquanto outro projeto pede gente?",
     f"SELECT colaborador_id, nome, papel, projeto_id, projeto, ROUND(SUM(horas_apontadas) / SUM(horas_disponiveis), 3) AS utilizacao, "
     f"SUM(horas_ociosas) AS horas_ociosas, SUM(custo_ocioso) AS custo_ocioso "
     f"FROM {G}.utilizacao_pessoa_semana WHERE semana > DATE'2026-07-24' "
     f"GROUP BY ALL HAVING SUM(horas_apontadas) / SUM(horas_disponiveis) < 0.2 ORDER BY utilizacao"),
    ("Por que o projeto PRJ-011 atrasou?",
     f"SELECT s.causa_bloqueio, COUNT(*) AS semanas, SUM(coalesce(s.dias_impacto, 0)) AS dias_de_impacto, MAX(p.spi) AS spi_do_projeto "
     f"FROM {G}.status_estruturado s JOIN {G}.projeto_situacao_atual p ON p.projeto_id = s.projeto_id "
     f"WHERE s.projeto_id = 'PRJ-011' AND s.data_status >= DATE'2026-07-18' AND s.causa_bloqueio NOT IN ('sem_bloqueio', 'nao_reportado') "
     f"GROUP BY s.causa_bloqueio ORDER BY semanas DESC"),
    ("Qual fornecedor mais atrasa?",
     f"SELECT fornecedor, COUNT(*) AS entregas, ROUND(AVG(prazo_real_dias / prazo_prometido_dias), 2) AS fator_atraso, "
     f"COUNT_IF(em_atraso) AS em_atraso_hoje FROM {S}.entregas_fornecedor GROUP BY fornecedor ORDER BY fator_atraso DESC LIMIT 1"),
    ("Quais projetos ficam travados pelo change freeze da Black Friday?",
     f"SELECT projeto_id, nome_projeto, cliente, tipo_projeto, ROUND(spi, 2) AS spi FROM {G}.projeto_situacao_atual "
     f"WHERE status = 'em_andamento' AND (lower(tipo_projeto) LIKE '%commerce%' OR lower(tipo_projeto) LIKE '%checkout%' "
     f"OR lower(tipo_projeto) LIKE '%marketplace%') ORDER BY spi"),
    ("O que vai dar errado no próximo mês, e o que eu faço agora?",
     f"SELECT 'entrega de fornecedor atrasada' AS risco, e.projeto_id, p.projeto, "
     f"concat(e.fornecedor, ': ', e.item, ' (', CAST(datediff(DATE'2026-10-16', e.data_prometida) AS STRING), ' dias de atraso)') AS detalhe, "
     f"'cobrar o fornecedor e aplicar a multa do contrato' AS o_que_fazer "
     f"FROM {S}.entregas_fornecedor e JOIN {G}.projeto_situacao_atual p ON p.projeto_id = e.projeto_id WHERE e.em_atraso "
     f"UNION ALL "
     f"SELECT 'change freeze da Black Friday', projeto_id, projeto, "
     f"'deploy em produção travado de 01/11/2026 a 10/01/2027', "
     f"'antecipar o que der para subir até 31/10' "
     f"FROM {G}.projeto_situacao_atual WHERE status = 'em_andamento' "
     f"AND (lower(tipo_projeto) LIKE '%commerce%' OR lower(tipo_projeto) LIKE '%checkout%' OR lower(tipo_projeto) LIKE '%marketplace%')"),
    ("Quais clientes têm projetos críticos?",
     f"SELECT cliente, COUNT(*) AS projetos_criticos FROM {G}.projeto_situacao_atual "
     f"WHERE status = 'em_andamento' AND situacao = 'crítico' GROUP BY cliente ORDER BY projetos_criticos DESC"),
    ("Qual projeto tem o maior estouro previsto?",
     f"SELECT projeto_id, nome_projeto, cliente, estouro_previsto FROM {G}.projeto_situacao_atual "
     f"WHERE status = 'em_andamento' ORDER BY estouro_previsto DESC LIMIT 1"),
    ("Quais projetos estão com farol verde mas estão atrasados?",
     f"SELECT projeto_id, nome_projeto, cliente, ROUND(spi, 2) AS spi, farol_do_gerente, farol_calculado "
     f"FROM {G}.projeto_situacao_atual WHERE melancia ORDER BY spi"),
]

PERGUNTAS = ["Quais projetos estão atrasados, e de quais clientes?",
             "Quanto esse atraso vai me custar?",
             "Tenho gente parada enquanto outro projeto pede gente?",
             "O que vai dar errado no próximo mês, e o que eu faço agora?"]

TABELAS = [f"{G}.fato_projeto_semana", f"{G}.projeto_situacao_atual", f"{G}.status_estruturado",
           f"{G}.utilizacao_pessoa_semana", f"{S}.entregas_fornecedor"]
METRICAS = [f"{G}.mv_projetos"]


def montar() -> dict:
    return {
        "version": 2,
        "config": {"sample_questions": [{"id": ident("b1", i), "question": [q]} for i, q in enumerate(PERGUNTAS, 1)]},
        "data_sources": {
            "tables": [{"identifier": t} for t in sorted(TABELAS)],
            "metric_views": [{"identifier": m} for m in sorted(METRICAS)],
        },
        "instructions": {
            "text_instructions": [{"id": ident("c1", 1), "content": [l + "\n" for l in INSTRUCOES]}],
            "example_question_sqls": [{"id": ident("d1", i), "question": [q], "sql": [s]}
                                      for i, (q, s) in enumerate(EXEMPLOS, 1)],
        },
    }


if __name__ == "__main__":
    SAIDA.write_text(json.dumps(montar(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ok: {SAIDA}")

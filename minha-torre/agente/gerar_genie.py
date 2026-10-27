#!/usr/bin/env python3
"""Gera o Genie Agent da noite 4, "Farol · Diretoria + Contratos", como JSON.

Uso:
    python3 minha-torre/agente/gerar_genie.py --profile SEU-PERFIL
    python3 scripts/genie.py publicar minha-torre/agente/diretoria-contratos-genie.json \
        --titulo "Farol · Diretoria + Contratos" --profile SEU-PERFIL

É o Genie da noite 2 com uma camada a mais: os CONTRATOS de fornecedor. O dono
não pergunta só "quem está atrasado?": pergunta "e o que o contrato diz? dá para
cobrar multa?". O agente cruza o status (a causa), a gold (o tamanho do problema),
o modelo da noite 3 (o que vem aí) e a cláusula (o direito).

A tabela do modelo da noite 3 (gold.score_estouro_30d) entra se existir:
o Genie recusa publicar com tabela inexistente.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

AQUI = pathlib.Path(__file__).resolve().parent
# Não use a extensão .geniespace.json aqui: o import do código do app recusa
# ("Requested node type [UNKNOWN] is not supported") e o app não sobe.
SAIDA = AQUI / "diretoria-contratos-genie.json"
G = "lakehouse_vertice.gold"
S = "lakehouse_vertice.silver"


def ident(prefixo: str, n: int) -> str:
    return f"{prefixo}{n:0{32 - len(prefixo)}d}"


def existe(tabela: str, profile: str | None) -> bool:
    if not profile:
        return False
    r = subprocess.run(["databricks", "tables", "exists", tabela, "--profile", profile, "-o", "json"],
                       capture_output=True, text=True)
    return r.returncode == 0 and '"table_exists": true' in r.stdout.replace("\n", " ").replace("  ", " ")


TABELAS = [f"{G}.contratos", f"{G}.projeto_situacao_atual", f"{G}.status_estruturado",
           f"{G}.utilizacao_pessoa_semana", f"{S}.entregas_fornecedor"]
METRICAS = [f"{G}.mv_projetos"]

MULTA_SQL = (
    f"WITH atrasos AS (SELECT e.fornecedor, e.valor, e.data_prometida, "
    f"CASE WHEN e.data_entrega IS NOT NULL THEN e.dias_de_atraso_na_entrega "
    f"ELSE datediff(DATE'2026-10-16', e.data_prometida) END AS dias_de_atraso "
    f"FROM {S}.entregas_fornecedor e "
    f"WHERE (e.data_entrega IS NOT NULL AND e.dias_de_atraso_na_entrega > 0) OR e.em_atraso) "
    f"SELECT a.fornecedor, COUNT(*) AS entregas_atrasadas, "
    f"ROUND(SUM(a.valor * least(a.dias_de_atraso * c.multa_atraso_pct_dia, c.teto_multa_pct) / 100), 2) AS multa_cobravel "
    f"FROM atrasos a JOIN {G}.contratos c ON lower(c.fornecedor) = lower(a.fornecedor) "
    f"WHERE c.multa_atraso_pct_dia IS NOT NULL AND a.data_prometida > add_months(c.data_fim_vigencia, -12) "
)

INSTRUCOES = [
    "Você é o assessor do DONO da Vértice Tecnologia (empresa de tecnologia, 520 pessoas, 60 projetos de clientes). "
    "Nos contratos de fornecedor e SaaS, a VÉRTICE É A CONTRATANTE e o fornecedor é a CONTRATADA: multa por atraso é "
    "dinheiro que a Vértice pode COBRAR (descontar da fatura do fornecedor). Responda em português, curto, com números em "
    "reais (R$) e índices com 2 casas. Termine com uma recomendação de uma linha quando a pergunta pedir decisão.",
    "HOJE é 16/10/2026. Nunca use current_date(). 'Últimos 90 dias' = data >= DATE'2026-07-18'; "
    "'últimas 12 semanas' = semana > DATE'2026-07-24'; 'próximos 60 dias' = até 15/12/2026.",
    "KPIs: SPI = EV/PV (< 1 é atraso), CPI = EV/AC (< 1 é estouro). Atenção: SPI ou CPI < 0,9; crítico: < 0,8. "
    "Fotografia de hoje: projeto_situacao_atual com status = 'em_andamento' (ou mv_projetos com MEASURE()). "
    "'Em risco' = atenção + crítico somados (hoje são 17), a menos que peçam a quebra por situação.",
    "Causa do atraso: status_estruturado (causa_bloqueio, bloqueio, quem_destrava, dias_impacto) nos últimos 90 dias, "
    "ignorando 'sem_bloqueio' e 'nao_reportado'. Gente parada: utilizacao_pessoa_semana nas últimas 12 semanas, "
    "SUM(horas_apontadas) / SUM(horas_disponiveis) < 0,2.",
    "CONTRATOS: são 8 contratos de fornecedor e SaaS (CodeForge, Pixel Design Studio, QualiTest Brasil, SecureOps Segurança, "
    "DataPrime Analytics, NuvemSul Cloud, Observa360, CodeVault), um por linha em contratos, com os campos extraídos por IA "
    "(valor_anual, data_fim_vigencia, renovacao_automatica, aviso_previo_dias, multa_atraso_pct_dia, teto_multa_pct, sla, reajuste) "
    "e o texto das cláusulas em clausulas. Quando disser o que o contrato diz, cite o número da cláusula e um trecho curto. "
    "Para um contrato específico, filtre por fornecedor com LIKE (ex.: fornecedor LIKE '%NuvemSul%').",
    "MULTA de fornecedor = valor da entrega × multa_atraso_pct_dia × dias de atraso, limitada a teto_multa_pct, em % (divida por 100). "
    "Dias de atraso: até a entrega se entregue (dias_de_atraso_na_entrega), até hoje se em aberto. Só conta o que foi prometido "
    "na vigência atual: data_prometida > add_months(data_fim_vigencia, -12). Junte entregas_fornecedor com contratos por "
    "lower(fornecedor). Use a SQL de exemplo da multa.",
    "AVISO PRÉVIO: data limite = date_sub(data_fim_vigencia, aviso_previo_dias). Já passou = data limite antes de 16/10/2026; "
    "vence em breve = até 60 dias. Se renovacao_automatica, o contrato renova sozinho se ninguém avisar; se não, o serviço para "
    "se ninguém formalizar a renovação.",
    "Quando citar um projeto, use projeto_id e nome (ex.: PRJ-011 · Checkout e meios de pagamento - Supermercados Bom Preço).",
]

EXEMPLOS = [
    ("Quanto a Vértice pode cobrar de multa da CodeForge?",
     MULTA_SQL + "AND a.fornecedor LIKE '%CodeForge%' GROUP BY a.fornecedor"),
    ("Quais contratos precisam de decisão por causa do aviso prévio?",
     f"SELECT fornecedor, valor_anual, data_fim_vigencia, aviso_previo_dias, renovacao_automatica, "
     f"date_sub(data_fim_vigencia, aviso_previo_dias) AS data_limite_aviso, "
     f"datediff(date_sub(data_fim_vigencia, aviso_previo_dias), DATE'2026-10-16') AS dias_ate_limite "
     f"FROM {G}.contratos WHERE datediff(date_sub(data_fim_vigencia, aviso_previo_dias), DATE'2026-10-16') <= 60 "
     f"ORDER BY dias_ate_limite"),
    ("Qual a multa por atraso e o teto no contrato da CodeForge?",
     f"SELECT fornecedor, multa_atraso_pct_dia, teto_multa_pct, clausulas FROM {G}.contratos WHERE fornecedor LIKE '%CodeForge%'"),
    ("Por que o PRJ-011 atrasou?",
     f"SELECT causa_bloqueio, COUNT(*) AS semanas, SUM(coalesce(dias_impacto, 0)) AS dias_de_impacto "
     f"FROM {G}.status_estruturado WHERE projeto_id = 'PRJ-011' AND data_status >= DATE'2026-07-18' "
     f"AND causa_bloqueio NOT IN ('sem_bloqueio', 'nao_reportado') GROUP BY causa_bloqueio ORDER BY semanas DESC"),
    ("Tenho SRE parado que poderia ir para o PRJ-011?",
     f"SELECT colaborador_id, nome, papel, projeto_id, projeto, ROUND(SUM(horas_apontadas) / SUM(horas_disponiveis), 3) AS utilizacao, "
     f"SUM(horas_ociosas) AS horas_ociosas, SUM(custo_ocioso) AS custo_ocioso "
     f"FROM {G}.utilizacao_pessoa_semana WHERE papel = 'sre' AND semana > DATE'2026-07-24' "
     f"GROUP BY ALL HAVING SUM(horas_apontadas) / SUM(horas_disponiveis) < 0.2 ORDER BY utilizacao"),
]

PERGUNTAS = [
    "Quanto a Vértice pode cobrar de multa da CodeForge?",
    "Quais contratos precisam de decisão por causa do aviso prévio?",
    "Por que o PRJ-011 atrasou?",
    "Tenho SRE parado que poderia ir para o PRJ-011?",
]


def montar(profile: str | None) -> dict:
    tabelas = list(TABELAS)
    instr = list(INSTRUCOES)
    if existe(f"{G}.score_estouro_30d", profile):
        tabelas.append(f"{G}.score_estouro_30d")
        instr.append("O que vai dar errado no próximo mês: score_estouro_30d (prob_estouro_30d de 0 a 1, ranking, faixa_risco, "
                     "principais_fatores), o modelo treinado na noite 3. Use a data_referencia mais recente e ordene por ranking.")
    return {
        "version": 2,
        "config": {"sample_questions": [{"id": ident("e1", i), "question": [q]} for i, q in enumerate(PERGUNTAS, 1)]},
        "data_sources": {
            "tables": [{"identifier": t} for t in sorted(tabelas)],
            "metric_views": [{"identifier": m} for m in sorted(METRICAS)],
        },
        "instructions": {
            "text_instructions": [{"id": ident("e2", 1), "content": [l + "\n" for l in instr]}],
            "example_question_sqls": [{"id": ident("e3", i), "question": [q], "sql": [s]}
                                      for i, (q, s) in enumerate(EXEMPLOS, 1)],
        },
    }


def main() -> None:
    profile = sys.argv[sys.argv.index("--profile") + 1] if "--profile" in sys.argv else None
    espaco = montar(profile)
    SAIDA.write_text(json.dumps(espaco, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(espaco["data_sources"]["tables"])
    print(f"ok: {SAIDA.name} · {n} tabelas · score da noite 3: {'sim' if n > len(TABELAS) else 'ainda não'}")


if __name__ == "__main__":
    main()

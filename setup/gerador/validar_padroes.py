#!/usr/bin/env python3
"""Confere se o dataset gerado conta a história que a aula precisa.

Uso:  python3 setup/gerador/validar_padroes.py --dados ./dados

É o gabarito da centralização: lê as três ferramentas (Excel, ClickUp e
MS Project) só com a biblioteca padrão, junta tudo pelo cadastro do PMO,
recalcula os KPIs e checa os 5 padrões embutidos. Sai com código 1 se algum
padrão sumir: rode depois de qualquer mudança no gerador.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from xlsx_simples import data_de_serial, ler_xlsx  # noqa: E402

HOJE = dt.date(2026, 10, 16)
CPI_CAINDO = ["PRJ-002", "PRJ-005", "PRJ-009", "PRJ-014", "PRJ-018", "PRJ-021", "PRJ-027", "PRJ-033"]
ECOMMERCE_FREEZE = ["PRJ-003", "PRJ-011", "PRJ-024"]
SQUAD_ROTATIVIDADE = ["PRJ-016", "PRJ-030"]
CORTE_ATENCAO, CORTE_CRITICO = 0.9, 0.8


def ler(base: pathlib.Path, nome: str) -> list[dict]:
    with (base / nome).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def data(txt) -> dt.date | None:
    if txt is None or txt == "":
        return None
    if isinstance(txt, float):
        return data_de_serial(txt)
    txt = txt.strip()
    return dt.datetime.strptime(txt, "%d/%m/%Y").date() if "/" in txt else dt.date.fromisoformat(txt[:10])


def num(txt) -> float:
    return float(str(txt).replace(",", ".").replace("%", "").replace("h", "").strip())


def de_ms(txt) -> dt.date | None:
    return dt.datetime.fromtimestamp(int(txt) / 1000, dt.timezone.utc).date() if txt else None


def horas_iso(txt: str) -> float:
    m = re.match(r"PT(\d+)H(\d+)M", txt)
    return int(m.group(1)) + int(m.group(2)) / 60


# ------------------------------------------------------------------ centralização

def tarefas_excel(caminho):
    linhas = ler_xlsx(caminho)
    cab = linhas[0]
    out = []
    for lin in linhas[1:]:
        r = dict(zip(cab, lin + [None] * (len(cab) - len(lin))))
        if r["Tarefa"] == "TOTAL":                   # linha de total no fim da planilha
            continue
        pct = r["% Concluído"]
        pct = num(pct) if isinstance(pct, str) else pct * 100
        out.append(dict(ini_b=data(r["Início previsto"]), fim_b=data(r["Término previsto"]),
                        pct=min(pct, 100.0), horas=num(r["Horas previstas"])))
    return out


def tarefas_clickup(caminho):
    doc = json.loads(caminho.read_text(encoding="utf-8"))
    out = []
    for t in doc["tasks"]:
        cf = {c["name"]: c["value"] for c in t["custom_fields"]}
        out.append(dict(ini_b=de_ms(cf["Início baseline"]), fim_b=de_ms(cf["Fim baseline"]),
                        pct=min(num(cf["Progresso (%)"]), 100.0), horas=t["time_estimate"] / 3_600_000))
    return doc["list"], out


def tarefas_msproject(caminho):
    ns = {"p": "http://schemas.microsoft.com/project"}
    raiz = ET.parse(caminho).getroot()
    out = []
    for t in raiz.iter("{http://schemas.microsoft.com/project}Task"):
        if t.findtext("p:Summary", namespaces=ns) == "1":          # tarefa-resumo: somaria duas vezes
            continue
        b = t.find("p:Baseline", ns)
        out.append(dict(ini_b=data(b.findtext("p:Start", namespaces=ns)), fim_b=data(b.findtext("p:Finish", namespaces=ns)),
                        pct=float(t.findtext("p:PercentComplete", namespaces=ns)),
                        horas=horas_iso(t.findtext("p:Work", namespaces=ns))))
    return out


def centralizar(base, proj):
    """projeto_id -> lista de tarefas canônicas (baseline, % concluído, horas)."""
    por_codigo = {p["codigo_ferramenta"]: pid for pid, p in proj.items() if p["codigo_ferramenta"]}
    por_nome = {p["nome_projeto"]: pid for pid, p in proj.items()}
    tarefas = {}
    for f in sorted((base / "excel").glob("*.xlsx")):
        pid = por_codigo.get(f.name)
        if pid is None:                               # código vazio no PMO: o nome do arquivo traz o PRJ
            pid = re.search(r"PRJ-\d{3}", f.name).group(0)
        tarefas[pid] = tarefas_excel(f)
    for f in sorted((base / "clickup").glob("*.json")):
        lista, ts = tarefas_clickup(f)
        pid = por_codigo.get(lista["id"]) or por_nome[lista["name"]]   # código vazio: casa pelo nome da lista
        tarefas[pid] = ts
    for f in sorted((base / "msproject").glob("*.xml")):
        tarefas[por_codigo.get(f.name) or f.name[:7]] = tarefas_msproject(f)
    return tarefas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", default="./dados")
    base = pathlib.Path(ap.parse_args().dados)
    ok = True

    def checar(cond: bool, msg: str) -> None:
        nonlocal ok
        ok &= cond
        print(f"  [{'ok' if cond else 'FALHOU'}] {msg}")

    proj = {p["projeto_id"]: p for p in ler(base, "pmo/projetos.csv")}
    tarefas = centralizar(base, proj)
    checar(len(tarefas) == len(proj) == 60, f"60 projetos e {len(tarefas)} cronogramas encontrados nas 3 ferramentas")
    custos = collections.defaultdict(list)
    for c in ler(base, "financeiro/custos.csv"):
        custos[c["projeto_id"]].append((data(c["data"]), num(c["valor"])))

    def kpis(pid, d=HOJE):
        ts = tarefas[pid]
        tot = sum(t["horas"] for t in ts)
        ev_h = sum(t["horas"] * t["pct"] / 100 for t in ts)
        pv_h = sum(t["horas"] * min(1.0, max(0.0, (d - t["ini_b"]).days / max(1, (t["fim_b"] - t["ini_b"]).days)))
                   for t in ts)
        orc = float(proj[pid]["orcamento_custo"])
        ev = orc * ev_h / tot
        ac = sum(v for dd, v in custos[pid] if dd <= d)
        return dict(spi=ev_h / pv_h if pv_h else 0, cpi=ev / ac if ac else 0, ev=ev, ac=ac, orc=orc,
                    pct=ev_h / tot * 100)

    # ---- KPIs de hoje -------------------------------------------------------------
    print(f"\nSPI e CPI em {HOJE.isoformat()} dos projetos em andamento (ordenado pelo pior índice)")
    andamento = [pid for pid, p in proj.items() if p["status"] == "em_andamento"]
    linhas = []
    for pid in andamento:
        k = kpis(pid)
        eac = k["orc"] / k["cpi"] if k["cpi"] else 0
        linhas.append((pid, proj[pid]["ferramenta"], k["spi"], k["cpi"], min(k["spi"], k["cpi"]), max(0.0, eac - k["orc"])))
    marcas = {**{p: "CPI caindo" for p in CPI_CAINDO}, **{p: "freeze" for p in ECOMMERCE_FREEZE},
              **{p: "rotatividade" for p in SQUAD_ROTATIVIDADE}, "PRJ-011": "freeze + sem SRE", "PRJ-007": "SREs ociosos"}
    for pid, ferr, spi, cpi, pior, est in sorted(linhas, key=lambda x: x[4]):
        print(f"  {pid} {ferr:<11} SPI {spi:5.2f}  CPI {cpi:5.2f}  estouro R$ {est / 1e6:5.2f} mi  {marcas.get(pid, '')}")
    criticos = [x for x in linhas if x[4] < CORTE_CRITICO]
    atencao = [x for x in linhas if CORTE_CRITICO <= x[4] < CORTE_ATENCAO]
    carteira = sum(float(p["valor_contrato"]) for p in proj.values())
    carteira_and = sum(float(proj[pid]["valor_contrato"]) for pid in andamento)
    print(f"\n  {len(andamento)} em andamento · {len(criticos)} críticos · {len(atencao)} em atenção · "
          f"estouro previsto R$ {sum(x[5] for x in linhas) / 1e6:.2f} mi")
    print(f"  carteira R$ {carteira / 1e6:.1f} mi (R$ {carteira_and / 1e6:.1f} mi em andamento)")
    checar(8 <= len(criticos) + len(atencao) <= 22, "entre 8 e 22 projetos em risco (atenção + crítico)")

    # ---- padrão 1 ----------------------------------------------------------------
    print("\nPadrão 1 · CPI caindo a partir do 6º mês (escopo cresce sem aditivo)")
    status = collections.defaultdict(list)
    for s in ler(base, "pmo/status_semanal.csv"):
        status[s["projeto_id"]].append(s)

    def cpi_status(pid, d):
        """CPI com o avanço reportado no status semanal (o histórico que existe)."""
        ult = [s for s in status[pid] if data(s["data_status"]) <= d]
        if not ult:
            return 0
        ev = int(ult[-1]["pct_concluido"]) / 100 * float(proj[pid]["orcamento_custo"])
        ac = sum(v for dd, v in custos[pid] if dd <= d)
        return ev / ac if ac else 0

    for pid in CPI_CAINDO:
        ini = data(proj[pid]["data_inicio"])
        serie = []
        for m in (3, 5, 8, 11, 14, 17):
            d = ini + dt.timedelta(days=int(m * 30.4))
            if d > HOJE:
                break
            serie.append((m, cpi_status(pid, d)))
        serie.append(("hoje", cpi_status(pid, HOJE)))
        print("    " + pid + "  " + "  ".join(f"m{m}:{c:.2f}" if m != "hoje" else f"hoje:{c:.2f}" for m, c in serie))
        m5 = dict(serie).get(5, 0)
        checar(m5 >= 0.93 and serie[-1][1] <= 0.90, f"{pid}: CPI ≥ 0,93 no mês 5 e ≤ 0,90 hoje")

    # ---- padrão 2 ----------------------------------------------------------------
    print("\nPadrão 2 · change freeze da Black Friday (01/11/2025 a 10/01/2026) nos projetos de e-commerce")
    for pid in ECOMMERCE_FREEZE:
        pct = {data(s["data_status"]): int(s["pct_concluido"]) for s in status[pid]}
        datas = sorted(pct)

        def ritmo(a, b):
            ds = [d for d in datas if a <= d <= b]
            return (pct[ds[-1]] - pct[ds[0]]) / max(1, len(ds) - 1) if len(ds) > 1 else 0

        antes = ritmo(dt.date(2025, 8, 22), dt.date(2025, 10, 31))
        durante = ritmo(dt.date(2025, 11, 7), dt.date(2026, 1, 9))
        checar(antes > 0 and durante < 0.45 * antes,
               f"{pid}: avanço semanal caiu de {antes:.2f} p.p. para {durante:.2f} p.p. no freeze")
    outros_ecom = [pid for pid, p in proj.items() if "commerce" in p["tipo_projeto"].lower() or "heckout" in p["tipo_projeto"]
                   or "arketplace" in p["tipo_projeto"]]
    checar(sorted(outros_ecom) == ECOMMERCE_FREEZE, f"só os 3 projetos de e-commerce: {outros_ecom}")

    # ---- padrão 3 ----------------------------------------------------------------
    print("\nPadrão 3 · prazo real ÷ prometido por fornecedor")
    entregas = ler(base, "compras/entregas_fornecedor.csv")
    razao = collections.defaultdict(list)
    grafias = set()
    for e in entregas:
        nome = e["fornecedor"]
        chave = "CodeForge (4 grafias)" if "forge" in nome.lower() else nome
        if "forge" in nome.lower():
            grafias.add(nome)
        if e["data_entrega"]:
            razao[chave].append((data(e["data_entrega"]) - data(e["data_pedido"])).days / int(e["prazo_contratado_dias"]))
    for f, rs in sorted(razao.items(), key=lambda x: -sum(x[1]) / len(x[1])):
        print(f"    {f:<28} {sum(rs) / len(rs):.2f}  ({len(rs)} entregas)")
    cf = razao["CodeForge (4 grafias)"]
    checar(1.33 <= sum(cf) / len(cf) <= 1.47, "CodeForge entrega com ~40% de atraso")
    checar(len(grafias) == 4, f"CodeForge escrita de {len(grafias)} jeitos")
    atrasadas = [e for e in entregas if not e["data_entrega"] and data(e["data_prometida"]) < HOJE]
    print(f"    entregas em atraso hoje: {len(atrasadas)} "
          f"({sum('forge' in e['fornecedor'].lower() for e in atrasadas)} da CodeForge)")

    # ---- padrão 4 ----------------------------------------------------------------
    print("\nPadrão 4 · SREs ociosos no PRJ-007 × falta de SRE no PRJ-011")
    apont = ler(base, "timesheet/apontamentos.csv")
    corte = HOJE - dt.timedelta(weeks=12)
    for cid in ("COL0017", "COL0018"):
        u = [float(a["horas_apontadas"]) / float(a["horas_disponiveis"]) for a in apont
             if a["colaborador_id"] == cid and a["projeto_id"] == "PRJ-007" and data(a["semana_inicio"]) >= corte]
        checar(bool(u) and max(u) < 0.12, f"{cid}: utilização máxima {max(u) if u else 0:.0%} no PRJ-007 nas últimas 12 semanas")
    col = {c["colaborador_id"]: c for c in ler(base, "rh/colaboradores.csv")}
    sre_011 = {a["colaborador_id"] for a in apont if a["projeto_id"] == "PRJ-011" and data(a["semana_inicio"]) >= corte
               and col[a["colaborador_id"]]["papel"].lower() == "sre"}
    checar(not sre_011, "nenhum SRE apontando horas no PRJ-011 nas últimas 12 semanas")
    falta = [s for s in status["PRJ-011"] if data(s["data_status"]) > corte
             and re.search(r"sre|infraestrutura", s["texto_status"].lower())]
    checar(len(falta) >= 7, f"status do PRJ-011 citando SRE/infraestrutura nas últimas 12 semanas: {len(falta)}")

    # ---- padrão 5 ----------------------------------------------------------------
    print("\nPadrão 5 · squads com rotatividade alta")
    # quem passou pelo squad = quem apontou hora no projeto (o timesheet substitui a planilha de alocação)
    for pid in SQUAD_ROTATIVIDADE + ["(outros)"]:
        if pid == "(outros)":
            ids = {a["colaborador_id"] for a in apont if a["projeto_id"] not in SQUAD_ROTATIVIDADE}
        else:
            ids = {a["colaborador_id"] for a in apont if a["projeto_id"] == pid}
        saidas = [c for c in ids if col[c]["data_desligamento"]
                  and data(col[c]["data_desligamento"]) >= HOJE - dt.timedelta(days=270)]
        taxa = len(saidas) / len(ids)
        print(f"    {pid:<9} {len(saidas):>3} saídas em 9 meses de {len(ids)} pessoas ({taxa:.0%})")
        if pid != "(outros)":
            checar(taxa >= 0.25, f"{pid}: rotatividade ≥ 25%")
    piores = sorted(linhas, key=lambda x: x[2])[:6]
    checar(all(p in [x[0] for x in piores] for p in SQUAD_ROTATIVIDADE),
           f"squads com rotatividade entre os 6 piores SPI: {[x[0] for x in piores]}")

    # ---- farol melancia --------------------------------------------------------------
    print("\nFarol do gerente × número (regra oficial do manual: verde só com SPI ≥ 0,95)")
    ult_farol = {}
    for pid, ss in status.items():
        ult_farol[pid] = ss[-1]["farol"].lower()
    melancia = [x[0] for x in linhas if x[2] < 0.9 and ult_farol.get(x[0]) == "verde"]
    print(f"    {len(melancia)} projetos com farol verde e SPI < 0,90: {', '.join(melancia)}")

    # ---- pergunta 2: horas ociosas -------------------------------------------------
    print("\nPergunta 3 · horas ociosas por projeto (últimas 8 semanas)")
    corte8 = HOJE - dt.timedelta(weeks=8)
    ocio = collections.Counter()
    for a in apont:
        if data(a["semana_inicio"]) >= corte8:
            ocio[a["projeto_id"]] += max(0.0, float(a["horas_disponiveis"]) - float(a["horas_apontadas"]))
    for pid, h in ocio.most_common(5):
        print(f"    {pid}  {h:,.0f} h ociosas".replace(",", "."))

    print("\nStatus semanal · palavras de bloqueio (amostra para o ai_classify)")
    cont = collections.Counter()
    for ss in status.values():
        for s in ss:
            t = s["texto_status"].lower()
            for chave in ("freeze", "congelamento", "sre", "consultoria", "forge", "saída", "rotatividade",
                          "escopo", "bugs", "aprovação", "nenhum", "sem bloqueios"):
                if chave in t:
                    cont[chave] += 1
    print("   ", dict(cont.most_common()))

    h = hashlib.sha256()
    for f in sorted(base.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(base).as_posix().encode())
            h.update(f.read_bytes())
    print(f"\nsha256 do dataset: {h.hexdigest()[:16]}")
    print("\nTODOS OS PADRÕES OK" if ok else "\nALGUM PADRÃO FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

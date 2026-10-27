#!/usr/bin/env python3
"""Genie pela linha de comando: criar/atualizar um espaço a partir de um JSON e fazer perguntas.

Uso:
  python3 scripts/genie.py publicar <arquivo.json> --titulo "..." --descricao "..." --profile P
  python3 scripts/genie.py perguntar "<título do espaço>" "pergunta 1" ["pergunta 2" ...] --profile P
  python3 scripts/genie.py benchmark "<título do espaço>" <arquivo-benchmark.json> --profile P

O JSON do espaço é o `serialized_space` (versão 2). Publicar de novo com o
mesmo título ATUALIZA o espaço, não cria outro.

O benchmark é uma lista [{"pergunta": "...", "sql_referencia": "..."}]: o
script roda a pergunta no Genie, roda o SQL de referência no warehouse e
compara os dois resultados: mesmas linhas, ignorando ordem, nome de coluna e
colunas extras que o Genie traga junto (valores com 2 casas decimais).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time


def api(metodo: str, caminho: str, profile: str, corpo: dict | None = None) -> dict:
    cmd = ["databricks", "api", metodo, caminho, "--profile", profile]
    if corpo is not None:
        cmd += ["--json", json.dumps(corpo)]
    for tentativa in range(4):          # rede e limite de taxa do Free Edition: tenta de novo
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout or "{}")
        erro = r.stderr.strip() or r.stdout.strip()
        if not any(x in erro for x in ("EOF", "429", "503", "502", "timeout", "RESOURCE_EXHAUSTED", "TEMPORARILY")):
            break
        time.sleep(5 * (tentativa + 1))
    raise RuntimeError(erro)


def warehouse(profile: str) -> str:
    return api("get", "/api/2.0/sql/warehouses", profile)["warehouses"][0]["id"]


def achar(titulo: str, profile: str) -> str | None:
    token = None
    while True:
        q = "/api/2.0/genie/spaces?page_size=100" + (f"&page_token={token}" if token else "")
        r = api("get", q, profile)
        for s in r.get("spaces", []):
            if s.get("title") == titulo:
                return s["space_id"]
        token = r.get("next_page_token")
        if not token:
            return None


def publicar(arquivo: str, titulo: str, descricao: str, profile: str) -> str:
    espaco = json.load(open(arquivo, encoding="utf-8"))
    corpo = {"title": titulo, "description": descricao, "warehouse_id": warehouse(profile),
             "serialized_space": json.dumps(espaco, ensure_ascii=False)}
    sid = achar(titulo, profile)
    if sid:
        api("patch", f"/api/2.0/genie/spaces/{sid}", profile, corpo)
        print(f"atualizado: {titulo} ({sid})")
    else:
        sid = api("post", "/api/2.0/genie/spaces", profile, corpo)["space_id"]
        print(f"criado: {titulo} ({sid})")
    return sid


def perguntar(sid: str, pergunta: str, profile: str) -> dict:
    """Devolve {texto, sql, colunas, linhas, status}."""
    r = api("post", f"/api/2.0/genie/spaces/{sid}/start-conversation", profile, {"content": pergunta})
    conv, msg = r["conversation_id"], r["message_id"]
    for _ in range(90):
        m = api("get", f"/api/2.0/genie/spaces/{sid}/conversations/{conv}/messages/{msg}", profile)
        if m.get("status") in ("COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"):
            break
        time.sleep(3)
    saida = {"status": m.get("status"), "texto": "", "sql": "", "colunas": [], "linhas": []}
    for a in m.get("attachments", []) or []:
        if a.get("text"):
            saida["texto"] += a["text"].get("content", "")
        if a.get("query"):
            saida["sql"] = a["query"].get("query", "")
            att = a.get("attachment_id")
            try:
                res = api("get", f"/api/2.0/genie/spaces/{sid}/conversations/{conv}/messages/{msg}"
                                 f"/attachments/{att}/query-result", profile)
                st = res.get("statement_response", {})
                saida["colunas"] = [c["name"] for c in st.get("manifest", {}).get("schema", {}).get("columns", [])]
                saida["linhas"] = st.get("result", {}).get("data_array") or []
            except RuntimeError as e:
                saida["texto"] += f" [sem resultado: {e}]"
    return saida


def rodar_sql(sql: str, profile: str) -> list[list]:
    r = api("post", "/api/2.0/sql/statements", profile,
            {"warehouse_id": warehouse(profile), "statement": sql, "wait_timeout": "50s"})
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(2)
        r = api("get", f"/api/2.0/sql/statements/{r['statement_id']}", profile)
    if r["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(r["status"].get("error", {}).get("message"))
    return r.get("result", {}).get("data_array") or []


def _valor(x):
    try:
        return f"{round(float(x), 2):g}"
    except (TypeError, ValueError):
        return (x or "").strip().lower()


def bate(genie: list[list], referencia: list[list]) -> bool:
    """O Genie acertou se devolveu as mesmas linhas da referência.

    Colunas extras na resposta do Genie são aceitas (ele costuma trazer o nome
    da obra junto do código): cada linha da referência precisa estar CONTIDA
    numa linha diferente do Genie, e o número de linhas tem que ser o mesmo.
    """
    if not genie or len(genie) != len(referencia):
        return False
    resto = [set(map(_valor, l)) for l in genie]
    for linha in referencia:
        alvo = set(map(_valor, linha))
        achou = next((i for i, g in enumerate(resto) if alvo <= g), None)
        if achou is None:
            return False
        resto.pop(achou)
    return True


def mostrar(p: str, r: dict) -> None:
    print(f"\n❓ {p}\n   status: {r['status']}")
    if r["texto"]:
        print(f"   resposta: {r['texto'][:500]}")
    if r["sql"]:
        print("   SQL: " + r["sql"].replace("\n", "\n        ")[:1500])
    for l in r["linhas"][:8]:
        print("   · " + " | ".join("" if x is None else str(x) for x in l))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["publicar", "perguntar", "benchmark"])
    ap.add_argument("alvo")
    ap.add_argument("resto", nargs="*")
    ap.add_argument("--titulo")
    ap.add_argument("--descricao", default="")
    ap.add_argument("--profile", required=True)
    a = ap.parse_args()

    if a.acao == "publicar":
        publicar(a.alvo, a.titulo, a.descricao, a.profile)
        return 0
    sid = achar(a.alvo, a.profile)
    if not sid:
        sys.exit(f"espaço não encontrado: {a.alvo}")
    if a.acao == "perguntar":
        for p in a.resto:
            mostrar(p, perguntar(sid, p, a.profile))
        return 0
    casos = json.load(open(a.resto[0], encoding="utf-8"))
    certos = 0
    for n, c in enumerate(casos, 1):
        try:
            r = perguntar(sid, c["pergunta"], a.profile)
        except RuntimeError as e:
            r = {"status": "ERRO", "texto": str(e), "sql": "", "colunas": [], "linhas": []}
        try:
            ok = bate(r["linhas"], rodar_sql(c["sql_referencia"], a.profile))
        except RuntimeError as e:
            ok = False
            r["texto"] += f" [referência falhou: {e}]"
        certos += ok
        print(f"[{'ok' if ok else 'ERRO'}] {n:02d}. {c['pergunta']}")
        if not ok:
            print("      SQL do Genie: " + (r["sql"] or r["texto"])[:400].replace("\n", " "))
    print(f"\n{certos}/{len(casos)} certas")
    return 0 if certos >= 0.8 * len(casos) else 1


if __name__ == "__main__":
    sys.exit(main())

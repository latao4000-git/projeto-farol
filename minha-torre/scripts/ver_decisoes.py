#!/usr/bin/env python3
"""Lê a tabela torre.decisoes direto no Lakebase (Postgres), sem psql.

Prova que o clique no app virou linha no banco, com usuário e horário.

Uso:
    uv run --no-project --with "psycopg[binary]" python minha-torre/scripts/ver_decisoes.py --profile SEU-PERFIL

A senha é um token OAuth de curta duração gerado pelo CLI
(`databricks postgres generate-database-credential`). Funciona para o dono
do projeto Lakebase; outro usuário precisa de GRANT no schema `torre`, que é
do service principal do app.
"""
import argparse
import json
import subprocess

import psycopg

ENDPOINT = "projects/minha-torre/branches/production/endpoints/primary"


def cli(*args: str, profile: str) -> dict:
    r = subprocess.run(["databricks", *args, "--profile", profile, "-o", "json"], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    a = ap.parse_args()
    host = cli("postgres", "get-endpoint", ENDPOINT, profile=a.profile)["status"]["hosts"]["host"]
    token = cli("postgres", "generate-database-credential", ENDPOINT, profile=a.profile)["token"]
    usuario = cli("current-user", "me", profile=a.profile)["userName"]
    with psycopg.connect(host=host, dbname="databricks_postgres", user=usuario, password=token, sslmode="require") as c:
        linhas = c.execute(
            "SELECT id, criado_em, usuario, recurso_id, projeto_origem, projeto_destino, decisao, economia_mes, dias_recuperados "
            "FROM torre.decisoes ORDER BY id DESC LIMIT 20").fetchall()
    print(f"torre.decisoes em {host}: {len(linhas)} linha(s)")
    for l in linhas:
        print("  " + " | ".join(str(x) for x in l))


if __name__ == "__main__":
    main()

# minha-torre · o app do Projeto Farol (noite 4)

Databricks App em [AppKit](https://developers.databricks.com/docs/appkit/v0/) (React + TypeScript) com quatro telas:
**Projetos em risco**, **Simulador**, **Decisões** e **Perguntar**. Visão geral do projeto no [README da raiz](../README.md).

| Peça | Onde |
|---|---|
| Leituras (SQL warehouse, gold) | [`config/queries/`](config/queries): `kpis.sql`, `projetos_risco.sql`, `pessoas_ociosas.sql` |
| Score da noite 3 (tabela opcional) | [`server/routes/score.ts`](server/routes/score.ts): responde `{disponivel:false}` se a tabela não existir |
| Escrita (Lakebase, `torre.decisoes`) | [`server/routes/decisoes.ts`](server/routes/decisoes.ts), validada com zod e testada em [`server/decisoes.test.ts`](server/decisoes.test.ts) |
| Telas | [`client/src/pages/`](client/src/pages) |
| Agente de contratos | [`agente/`](agente): `01-contratos.sql` (PDF → `gold.contratos`) e `gerar_genie.py` |
| Job dos contratos | [`resources/contratos.job.yml`](resources/contratos.job.yml) |

## Deploy

```bash
databricks bundle deploy --profile <perfil>     # cria o app, o service principal e o job farol_contratos
bash scripts/conceder-acesso.sh <perfil>        # GRANT USE CATALOG / USE SCHEMA / SELECT na gold e na silver
databricks apps deploy --profile <perfil>       # build e start
```

Na primeira visita, cada pessoa clica **Authorize** uma vez: o app pede para usar o Genie em nome dela.

## Desenvolvimento

```bash
npm install
set -a; . ./.env; set +a; npm run typegen -- --wait   # tipos das queries a partir do Unity Catalog
npm run dev
npm run typecheck && npm run lint && npm test
databricks apps validate --profile <perfil>
```

Para conferir a gravação direto no Postgres:

```bash
python scripts/ver_decisoes.py --profile <perfil>   # precisa de psycopg[binary]
```

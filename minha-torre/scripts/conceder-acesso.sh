#!/usr/bin/env bash
# O app é um USUÁRIO do Unity Catalog (um service principal) e nasce sem acesso
# a dado nenhum. `CAN_USE` no warehouse dá o computador, não o dado.
# Sem estes GRANTs o build falha no typegen (INSUFFICIENT_PERMISSIONS) e,
# depois, toda tela carrega vazia.
#
# O service principal muda a cada app criado: leia com `apps get`, nunca copie.
#
# Uso:  bash scripts/conceder-acesso.sh <perfil> [nome-do-app]
set -euo pipefail
PERFIL="${1:?informe o profile}"
APP="${2:-minha-torre}"
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
RUN_SQL="$RAIZ/scripts/run_sql.py"
PY="$(command -v python3 >/dev/null && python3 -c 'print(1)' >/dev/null 2>&1 && echo python3 || echo python)"
WAREHOUSE="$(grep -E '^DATABRICKS_WAREHOUSE_ID=' "$(dirname "$0")/../.env" | cut -d= -f2)"

SP=$(databricks apps get "$APP" --profile "$PERFIL" -o json \
     | "$PY" -c "import json,sys; print(json.load(sys.stdin)['service_principal_client_id'])")
echo "service principal do app $APP: $SP"

TMP=$(mktemp)
cat > "$TMP" <<SQL
GRANT USE CATALOG ON CATALOG lakehouse_vertice TO \`$SP\`;
GRANT USE SCHEMA, SELECT ON SCHEMA lakehouse_vertice.gold TO \`$SP\`;
GRANT USE SCHEMA, SELECT ON SCHEMA lakehouse_vertice.silver TO \`$SP\`
SQL
"$PY" "$RUN_SQL" "$TMP" --profile "$PERFIL" ${WAREHOUSE:+--warehouse "$WAREHOUSE"} --quiet
rm -f "$TMP"

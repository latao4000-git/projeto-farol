// Probabilidade de estouro em 30 dias (modelo da noite 3, gold.score_estouro_30d).
//
// Exceção consciente à regra "leitura é sempre config/queries/*.sql": a tabela
// é de OUTRA noite e pode ainda não existir. Uma query em config/queries com
// tabela inexistente quebra o typegen e, com ele, o build do app inteiro.
// Aqui a rota responde { disponivel: false } e a tela mostra "—".

import { getExecutionContext } from '@databricks/appkit';
import type { Application } from 'express';

interface AppKitComServer {
  server: { extend(fn: (app: Application) => void): void };
}

const SQL = `
  SELECT projeto_id, prob_estouro_30d, ranking, faixa_risco
  FROM lakehouse_vertice.gold.score_estouro_30d
  WHERE data_referencia = (SELECT MAX(data_referencia) FROM lakehouse_vertice.gold.score_estouro_30d)`;

export function registrarRotaScore(appkit: AppKitComServer) {
  appkit.server.extend((app) => {
    app.get('/api/score-estouro', async (_req, res) => {
      try {
        const contexto = getExecutionContext();
        const warehouseId = (await contexto.warehouseId) ?? process.env.DATABRICKS_WAREHOUSE_ID ?? '';
        const r = await contexto.client.statementExecution.executeStatement({
          warehouse_id: warehouseId, statement: SQL, wait_timeout: '30s',
        });
        if (r.status?.state !== 'SUCCEEDED') {
          res.json({ disponivel: false, motivo: r.status?.error?.message ?? r.status?.state, linhas: [] });
          return;
        }
        const colunas = (r.manifest?.schema?.columns ?? []).map((c) => c.name ?? '');
        const linhas = (r.result?.data_array ?? []).map((l) =>
          Object.fromEntries(colunas.map((c, i) => [c, l[i] ?? null])),
        );
        res.json({ disponivel: linhas.length > 0, linhas });
      } catch (err) {
        res.json({ disponivel: false, motivo: (err as Error).message, linhas: [] });
      }
    });
  });
}

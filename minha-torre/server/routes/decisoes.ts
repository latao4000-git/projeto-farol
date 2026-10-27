// Decisões do dono e da diretoria, gravadas no Lakebase (Postgres).
//
// Por que Postgres e não uma tabela Delta? Porque isto é uma TRANSAÇÃO: uma
// pessoa clica, uma linha nasce, e ela precisa aparecer na hora para todo
// mundo. Delta é ótima para analisar milhões de linhas; Postgres é feito
// para gravar uma linha por clique, com chave, horário e usuário.
//
// O app roda como service principal, mas a decisão é gravada com o e-mail de
// quem clicou (header x-forwarded-email, que o Databricks Apps injeta depois
// do login SSO). Sem isso, ninguém sabe quem aprovou.

import { z } from 'zod';
import type { Application, Request } from 'express';

interface AppKitComLakebase {
  lakebase: { query(texto: string, params?: unknown[]): Promise<{ rows: Record<string, unknown>[] }> };
  server: { extend(fn: (app: Application) => void): void };
}

// O service principal só enxerga o schema que ele mesmo cria (não o public).
const CRIAR = [
  `CREATE SCHEMA IF NOT EXISTS torre`,
  `CREATE TABLE IF NOT EXISTS torre.decisoes (
     id               SERIAL PRIMARY KEY,
     projeto_origem   TEXT NOT NULL,
     projeto_destino  TEXT NOT NULL,
     recurso_id       TEXT NOT NULL,
     tipo             TEXT NOT NULL CHECK (tipo IN ('pessoa')),
     decisao          TEXT NOT NULL CHECK (decisao IN ('aprovada', 'recusada')),
     justificativa    TEXT NOT NULL,
     horas_recuperadas_mes NUMERIC(12,1),
     economia_mes     NUMERIC(14,2),
     dias_recuperados NUMERIC(8,1),
     usuario          TEXT NOT NULL,
     criado_em        TIMESTAMPTZ NOT NULL DEFAULT NOW()
   )`,
];

export const DecisaoSchema = z.object({
  projeto_origem: z.string().regex(/^PRJ-\d{3}$/),
  projeto_destino: z.string().regex(/^PRJ-\d{3}$/),
  recurso_id: z.string().regex(/^COL\d{4}$/),
  tipo: z.enum(['pessoa']),
  decisao: z.enum(['aprovada', 'recusada']),
  justificativa: z.string().trim().min(10, 'Escreva uma justificativa de pelo menos 10 caracteres').max(1000),
  // o warehouse devolve número como string: coerce aceita os dois
  horas_recuperadas_mes: z.coerce.number().nonnegative().optional(),
  economia_mes: z.coerce.number().nonnegative().optional(),
  dias_recuperados: z.coerce.number().nonnegative().optional(),
});

const usuario = (req: Request) => req.header('x-forwarded-email') ?? req.header('x-forwarded-user') ?? 'local@desenvolvimento';

export async function registrarRotasDecisoes(appkit: AppKitComLakebase) {
  try {
    for (const sql of CRIAR) await appkit.lakebase.query(sql);
    console.log('[decisoes] torre.decisoes pronta');
  } catch (err) {
    console.warn('[decisoes] não consegui criar a tabela:', (err as Error).message);
  }

  appkit.server.extend((app) => {
    app.get('/api/quem-sou', (req, res) => {
      res.json({ usuario: usuario(req) });
    });

    app.get('/api/decisoes', async (_req, res) => {
      try {
        const { rows } = await appkit.lakebase.query(
          `SELECT id, projeto_origem, projeto_destino, recurso_id, tipo, decisao, justificativa,
                  horas_recuperadas_mes, economia_mes, dias_recuperados, usuario, criado_em
           FROM torre.decisoes ORDER BY criado_em DESC LIMIT 200`,
        );
        res.json(rows);
      } catch (err) {
        console.error('[decisoes] listar', err);
        res.status(500).json({ erro: 'Não consegui ler as decisões' });
      }
    });

    app.post('/api/decisoes', async (req, res) => {
      const p = DecisaoSchema.safeParse(req.body);
      if (!p.success) {
        res.status(400).json({ erro: p.error.issues[0]?.message ?? 'Decisão inválida' });
        return;
      }
      const d = p.data;
      if (d.projeto_origem === d.projeto_destino) {
        res.status(400).json({ erro: 'Origem e destino são o mesmo projeto' });
        return;
      }
      try {
        const { rows } = await appkit.lakebase.query(
          `INSERT INTO torre.decisoes
             (projeto_origem, projeto_destino, recurso_id, tipo, decisao, justificativa,
              horas_recuperadas_mes, economia_mes, dias_recuperados, usuario)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
           RETURNING id, criado_em, usuario`,
          [d.projeto_origem, d.projeto_destino, d.recurso_id, d.tipo, d.decisao, d.justificativa,
           d.horas_recuperadas_mes ?? null, d.economia_mes ?? null, d.dias_recuperados ?? null, usuario(req)],
        );
        res.status(201).json(rows[0]);
      } catch (err) {
        console.error('[decisoes] gravar', err);
        res.status(500).json({ erro: 'Não consegui gravar a decisão' });
      }
    });
  });
}

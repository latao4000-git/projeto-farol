import { describe, expect, test } from 'vitest';
import { DecisaoSchema } from './routes/decisoes';

// O endpoint que escreve é a porta mais sensível do app: só entra decisão válida.
const valida = {
  projeto_origem: 'PRJ-007', projeto_destino: 'PRJ-011', recurso_id: 'COL0017', tipo: 'pessoa',
  decisao: 'aprovada', justificativa: 'SRE sênior a 6% de uso no PRJ-007 (ainda no discovery); PRJ-011 sem SRE há 12 semanas.',
  horas_recuperadas_mes: '150.8', economia_mes: '30123.20', dias_recuperados: '19.0',
};

describe('DecisaoSchema', () => {
  test('aceita uma decisão válida e converte número que chega como string', () => {
    const p = DecisaoSchema.parse(valida);
    expect(p.economia_mes).toBeCloseTo(30123.2);
    expect(p.dias_recuperados).toBeCloseTo(19);
  });
  test('recusa justificativa curta', () => {
    expect(DecisaoSchema.safeParse({ ...valida, justificativa: 'ok' }).success).toBe(false);
  });
  test('recusa código de projeto fora do padrão PRJ-000', () => {
    expect(DecisaoSchema.safeParse({ ...valida, projeto_destino: "PRJ-011'; DROP TABLE x" }).success).toBe(false);
  });
  test('recusa colaborador fora do padrão COL0000', () => {
    expect(DecisaoSchema.safeParse({ ...valida, recurso_id: 'EQ0017' }).success).toBe(false);
  });
  test('recusa decisão fora de aprovada/recusada', () => {
    expect(DecisaoSchema.safeParse({ ...valida, decisao: 'talvez' }).success).toBe(false);
  });
});

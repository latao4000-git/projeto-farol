import { describe, expect, test } from 'vitest';
import { indice, milhoes, num, pct } from '../client/src/lib/dados';

// O warehouse devolve todo número como string: sem num(), "6465127.22" + 1 concatena.
describe('num e formatos', () => {
  test('converte string do warehouse em número', () => {
    expect(num('6465127.22')).toBe(6465127.22);
    expect(num(null)).toBe(0);
    expect(num('abc')).toBe(0);
  });

  test('formata em pt-BR', () => {
    expect(milhoes('6465127.22')).toBe('R$ 6,5 mi');
    expect(indice('0.8123')).toBe('0,81');
    expect(pct('0.06')).toBe('6%');
  });
});

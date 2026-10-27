import {
  useAnalyticsQuery, Button, Card, CardContent, CardHeader, CardTitle, Input, Label, Skeleton,
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@databricks/appkit-ui/react';
import { useState } from 'react';
import { z } from 'zod';
import { CAUSAS, CAUSA_DO_PAPEL, num, pct, reais } from '../../lib/dados';

const RespostaSchema = z.object({ id: z.coerce.number().optional(), usuario: z.string().optional(), erro: z.string().optional() });

// Premissa do simulador: o efeito vale para o PRÓXIMO MÊS (4 semanas).
const SEMANAS = 4;
// Premissa de mobilização: uma semana de onboarding no projeto novo (40 h que ainda não produzem).
const HORAS_ONBOARDING = 40;

export function SimuladorPage() {
  const pessoas = useAnalyticsQuery('pessoas_ociosas', {});
  const projetos = useAnalyticsQuery('projetos_risco', {});
  const [pessoaId, setPessoaId] = useState<string>('');
  const [destinoId, setDestinoId] = useState<string>('');
  const [horasOnboarding, setHorasOnboarding] = useState<string>(String(HORAS_ONBOARDING));
  const [justificativa, setJustificativa] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState<{ ok: boolean; texto: string } | null>(null);

  const pessoa = pessoas.data?.find((r) => r.colaborador_id === pessoaId);
  const campoCausa = pessoa ? CAUSA_DO_PAPEL[pessoa.papel] : undefined;
  // Destino = projeto em risco, diferente da origem; com causa compatível com o papel primeiro.
  const destinos = (projetos.data ?? [])
    .filter((o) => o.situacao !== 'ok' && o.projeto_id !== pessoa?.projeto_origem)
    .sort((a, b) => (campoCausa ? num(b[campoCausa]) - num(a[campoCausa]) : 0));
  const destino = projetos.data?.find((o) => o.projeto_id === destinoId);

  // As contas, à vista de quem decide:
  const horasMes = pessoa ? num(pessoa.horas_paradas_semana) * SEMANAS : 0;
  const ociosidadeMes = pessoa ? num(pessoa.custo_ocioso_semana) * SEMANAS : 0;
  const diasCausa = destino && campoCausa ? num(destino[campoCausa]) : 0;
  const diasRecuperados = (diasCausa / 90) * 30;            // impacto dos últimos 90 dias, trazido para 1 mês
  const custoMobilizacao = pessoa ? num(horasOnboarding) * num(pessoa.custo_hora) : 0;
  const saldo = ociosidadeMes - custoMobilizacao;

  async function decidir(decisao: 'aprovada' | 'recusada') {
    if (!pessoa || !destino) return;
    setEnviando(true);
    setResultado(null);
    try {
      const r = await fetch('/api/decisoes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          projeto_origem: pessoa.projeto_origem, projeto_destino: destino.projeto_id,
          recurso_id: pessoa.colaborador_id, tipo: 'pessoa', decisao, justificativa,
          horas_recuperadas_mes: horasMes.toFixed(1), economia_mes: ociosidadeMes.toFixed(2),
          dias_recuperados: diasRecuperados.toFixed(1),
        }),
      });
      const corpo = RespostaSchema.parse(await r.json());
      if (!r.ok) throw new Error(corpo.erro ?? r.statusText);
      setResultado({ ok: true, texto: `Decisão nº ${corpo.id} ${decisao} e registrada por ${corpo.usuario}.` });
      setJustificativa('');
    } catch (e) {
      setResultado({ ok: false, texto: e instanceof Error ? e.message : 'Erro ao gravar' });
    } finally {
      setEnviando(false);
    }
  }

  if (pessoas.loading || projetos.loading) return <Skeleton className="h-96 max-w-5xl mx-auto" />;
  if (pessoas.error || projetos.error)
    return <div className="text-destructive">Erro: {String(pessoas.error ?? projetos.error)}</div>;

  return (
    <div className="space-y-6 w-full max-w-5xl mx-auto">
      <div>
        <h2 className="text-2xl font-bold text-foreground">Simulador de realocação</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Escolha uma pessoa parada e um projeto em risco. A Torre mostra o que muda no próximo mês e você aprova ou recusa.
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>1 · Quem e para onde</CardTitle></CardHeader>
        <CardContent className="grid md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="pessoa">Pessoa com uso abaixo de 20% (últimas 12 semanas)</Label>
            <Select value={pessoaId} onValueChange={(v) => { setPessoaId(v); setDestinoId(''); setResultado(null); }}>
              <SelectTrigger id="pessoa"><SelectValue placeholder="Escolha uma pessoa" /></SelectTrigger>
              <SelectContent>
                {(pessoas.data ?? []).map((r) => (
                  <SelectItem key={`${r.colaborador_id}-${r.projeto_origem}`} value={r.colaborador_id}>
                    {r.colaborador_id} · {r.nome} · {r.papel} {r.senioridade} · {r.projeto_origem} · uso {pct(r.utilizacao_media)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="destino">Projeto destino (em atenção ou crítico)</Label>
            <Select value={destinoId} onValueChange={(v) => { setDestinoId(v); setResultado(null); }} disabled={!pessoa}>
              <SelectTrigger id="destino"><SelectValue placeholder="Escolha o projeto" /></SelectTrigger>
              <SelectContent>
                {destinos.map((o) => (
                  <SelectItem key={o.projeto_id} value={o.projeto_id}>
                    {o.projeto_id} · {o.situacao} · causa: {CAUSAS[o.causa_principal] ?? o.causa_principal}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {pessoa && destino && (
        <Card>
          <CardHeader><CardTitle>2 · O que muda no próximo mês</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <div><div className="text-xs text-muted-foreground">Horas paradas que viram produção</div>
                <div className="text-2xl font-bold">{horasMes.toLocaleString('pt-BR', { maximumFractionDigits: 0 })} h</div></div>
              <div><div className="text-xs text-muted-foreground">Ociosidade que deixa de ser paga</div>
                <div className="text-2xl font-bold">{reais(ociosidadeMes)}</div></div>
              <div><div className="text-xs text-muted-foreground">Dias de cronograma recuperados no destino</div>
                <div className="text-2xl font-bold">{campoCausa ? `${diasRecuperados.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} d` : '—'}</div></div>
              <div><div className="text-xs text-muted-foreground">Atraso projetado do destino hoje</div>
                <div className="text-2xl font-bold">{num(destino.atraso_projetado_dias) > 0 ? `+${num(destino.atraso_projetado_dias)} d` : '—'}</div></div>
            </div>
            <div className="flex flex-wrap items-end gap-4">
              <div className="space-y-1">
                <Label htmlFor="onb">Horas de onboarding (premissa)</Label>
                <Input id="onb" className="w-32" inputMode="numeric" value={horasOnboarding} onChange={(e) => setHorasOnboarding(e.target.value)} />
              </div>
              <div className="text-sm text-muted-foreground">Custo da mobilização: {reais(custoMobilizacao)}</div>
              <div className={`text-lg font-semibold ${saldo >= 0 ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-700 dark:text-red-300'}`}>
                Saldo do mês: {reais(saldo)}
              </div>
            </div>
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Como a conta é feita</summary>
              <ul className="list-disc pl-5 mt-2 space-y-1">
                <li>Horas = horas paradas por semana da pessoa (média de 12 semanas no timesheet) × {SEMANAS} semanas.</li>
                <li>Ociosidade = custo da hora parada por semana × {SEMANAS}: o que a Vértice paga hoje sem produzir.</li>
                <li>Dias recuperados = dias de impacto que o status semanal do destino atribuiu a {campoCausa ? 'falta de SRE' : 'uma causa que esse papel não resolve'} nos últimos 90 dias ÷ 90 × 30.</li>
                <li>Mobilização = horas de onboarding × custo/hora da pessoa ({reais(pessoa.custo_hora, 2)}/h).</li>
                <li>Saldo = ociosidade evitada − mobilização. Os dias recuperados ficam fora da conta em R$, de propósito: não viram dinheiro sem uma premissa de multa ou receita.</li>
              </ul>
            </details>
          </CardContent>
        </Card>
      )}

      {pessoa && destino && (
        <Card>
          <CardHeader><CardTitle>3 · Decisão</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Label htmlFor="just">Justificativa (fica registrada com o seu usuário)</Label>
            <textarea id="just" className="w-full min-h-24 rounded-md border bg-background p-2 text-sm"
                      value={justificativa} onChange={(e) => setJustificativa(e.target.value)}
                      placeholder={`Ex.: mover ${pessoa.colaborador_id} do ${pessoa.projeto_origem} para o ${destino.projeto_id} na segunda.`} />
            <div className="flex gap-3">
              <Button disabled={enviando || justificativa.trim().length < 10} onClick={() => void decidir('aprovada')}>Aprovar</Button>
              <Button variant="outline" disabled={enviando || justificativa.trim().length < 10} onClick={() => void decidir('recusada')}>Recusar</Button>
            </div>
            {resultado && (
              <div className={resultado.ok ? 'text-emerald-700 dark:text-emerald-300' : 'text-destructive'}>{resultado.texto}</div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

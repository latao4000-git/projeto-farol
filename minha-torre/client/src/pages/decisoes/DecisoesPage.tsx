import { Card, CardContent, CardHeader, CardTitle, Skeleton } from '@databricks/appkit-ui/react';
import { useEffect, useState } from 'react';
import { reais } from '../../lib/dados';

interface Decisao {
  id: number;
  projeto_origem: string;
  projeto_destino: string;
  recurso_id: string;
  tipo: string;
  decisao: string;
  justificativa: string;
  horas_recuperadas_mes: string | null;
  economia_mes: string | null;
  dias_recuperados: string | null;
  usuario: string;
  criado_em: string;
}

export function DecisoesPage() {
  const [linhas, setLinhas] = useState<Decisao[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/decisoes')
      .then((r) => (r.ok ? (r.json() as Promise<Decisao[]>) : Promise.reject(new Error(r.statusText))))
      .then(setLinhas)
      .catch((e) => setErro(e instanceof Error ? e.message : 'erro'));
  }, []);

  return (
    <div className="space-y-6 w-full max-w-6xl mx-auto">
      <div>
        <h2 className="text-2xl font-bold text-foreground">Decisões do dono e da diretoria</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Gravadas no Lakebase (Postgres), tabela <code>torre.decisoes</code>, com o usuário do login e o horário.
        </p>
      </div>
      <Card>
        <CardHeader><CardTitle>Histórico</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          {!linhas && !erro && <Skeleton className="h-40" />}
          {erro && <div className="text-destructive">Erro: {erro}</div>}
          {linhas && linhas.length === 0 && <div className="text-muted-foreground">Nenhuma decisão ainda. Use o simulador.</div>}
          {linhas && linhas.length > 0 && (
            <table className="w-full table-fixed text-sm">
              <thead className="text-left text-muted-foreground border-b">
                <tr>
                  <th className="py-2 w-[5%]">Nº</th><th className="w-[13%]">Quando</th><th className="w-[16%]">Recurso</th>
                  <th className="w-[9%]">Decisão</th><th className="w-[26%]">Justificativa</th>
                  <th className="w-[10%] text-right">Ociosidade evitada/mês</th><th className="w-[21%] pl-3">Por</th>
                </tr>
              </thead>
              <tbody>
                {linhas.map((d) => (
                  <tr key={d.id} className="border-b last:border-0 align-top">
                    <td className="py-2">{d.id}</td>
                    <td>{new Date(d.criado_em).toLocaleString('pt-BR')}</td>
                    <td>{d.recurso_id}: {d.projeto_origem} → {d.projeto_destino}</td>
                    <td className={d.decisao === 'aprovada' ? 'text-emerald-700 dark:text-emerald-300 font-medium' : 'text-muted-foreground'}>{d.decisao}</td>
                    <td className="truncate" title={d.justificativa}>{d.justificativa}</td>
                    <td className="text-right">{d.economia_mes == null ? '—' : reais(d.economia_mes)}</td>
                    <td className="pl-3 truncate">{d.usuario}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

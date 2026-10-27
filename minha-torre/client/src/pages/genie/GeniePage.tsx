import { GenieChat } from '@databricks/appkit-ui/react';

export function GeniePage() {
  return (
    <div className="space-y-6 w-full max-w-4xl mx-auto">
      <div>
        <h2 className="text-2xl font-bold text-foreground">Perguntar</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Genie &ldquo;Farol · Diretoria + Contratos&rdquo;: projetos, causa do atraso no status semanal, risco de
          estouro em 30 dias e o que o contrato de fornecedor diz.
          Experimente: <i>&ldquo;Quanto dá para cobrar de multa da CodeForge?&rdquo;</i>
        </p>
      </div>
      <div className="h-[min(640px,72vh)] border rounded-lg overflow-hidden">
        <GenieChat alias="default" />
      </div>
    </div>
  );
}

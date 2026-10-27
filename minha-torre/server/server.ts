import { createApp, analytics, genie, lakebase, server } from '@databricks/appkit';
import { registrarRotasDecisoes } from './routes/decisoes';
import { registrarRotaScore } from './routes/score';

// Leitura: config/queries/*.sql no SQL warehouse (gold da Vértice).
// Conversa: Genie "Farol · Diretoria + Contratos".
// Escrita: Lakebase (Postgres), tabela torre.decisoes.
createApp({
  plugins: [analytics(), genie(), lakebase(), server()],
  // Sem cache: quem acabou de aprovar uma realocação quer ver o número de agora.
  cache: { enabled: false },
  async onPluginsReady(appkit) {
    await registrarRotasDecisoes(appkit);
    registrarRotaScore(appkit);
  },
}).catch(console.error);

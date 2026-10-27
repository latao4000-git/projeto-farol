-- Noite 1 · Setup do ambiente
-- Cria a casa onde o dado vai morar: um catálogo, três schemas e um volume.
--
-- Rode no SQL Editor (selecione tudo e Ctrl+Enter) ou pelo terminal:
--   python3 scripts/run_sql.py setup/00-setup-catalogo.sql --profile SEU-PERFIL

-- O catálogo é o topo da hierarquia no Unity Catalog: catálogo > schema > tabela.
CREATE CATALOG IF NOT EXISTS lakehouse_vertice
  COMMENT 'Imersão Jornada de Dados · Torre de Controle de Projetos da Vértice Tecnologia';

-- Os três schemas são as três camadas do medalhão. Criamos os três agora,
-- mesmo que hoje só a bronze receba dado: o desenho vem antes do código.
CREATE SCHEMA IF NOT EXISTS lakehouse_vertice.bronze
  COMMENT 'Ingestão crua. O dado como veio de cada ferramenta (Excel, ClickUp, MS Project) e sistema, sujeira inclusa.';
CREATE SCHEMA IF NOT EXISTS lakehouse_vertice.silver
  COMMENT 'Limpo, deduplicado, tipado e centralizado: as três ferramentas num modelo só. Preenchido na noite 2.';
CREATE SCHEMA IF NOT EXISTS lakehouse_vertice.gold
  COMMENT 'KPIs da carteira de projetos (SPI, CPI, estouro previsto, ociosidade), prontos para consumo. Noite 2.';

-- O volume guarda ARQUIVO, não tabela: planilhas, exports do ClickUp e do Project, CSVs e PDFs.
CREATE VOLUME IF NOT EXISTS lakehouse_vertice.bronze.raw
  COMMENT 'Arquivos originais: planilhas Excel, JSON do ClickUp, XML do MS Project, CSVs de PMO, RH, timesheet, financeiro e compras, e os contratos em PDF.';

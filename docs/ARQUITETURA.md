# Arquitetura

```
LogiTrace/
├── backend/                  API FastAPI, regras de negócio, geoprocessamento, grafos, simulação, otimização
│   ├── app/
│   │   ├── api/              rotas HTTP (facilities, territory, network, scenarios, optimization, flows,
│   │   │                     analytics, exports, tiles, meta) — só orquestram e validam
│   │   ├── core/             configuração (.env), logging, premissas paramétricas
│   │   ├── db/               engine/sessões SQLAlchemy, base declarativa
│   │   ├── models/           ORM: referência territorial, infraestrutura, rede, fluxos, cenários, jobs
│   │   ├── ingestion/        download, catálogo de fontes, importadores por fonte, validação e proveniência
│   │   ├── network/          construtor do grafo, motor em memória (SciPy/NetworkX), análises estruturais
│   │   ├── scenarios/        motor de cenários (base × alterações) e simulação de eventos discretos (SimPy)
│   │   ├── optimization/     montagem de dados e modelos OR-Tools (SCIP, GLOP, Routing)
│   │   ├── reports/          relatórios PDF (ReportLab + Matplotlib)
│   │   ├── jobs.py           tarefas assíncronas (pool de threads + tabela `job`)
│   │   └── cli.py            linha de comando de ingestão e construção da rede
│   ├── alembic/              migrações (inclui view materializada e índices de busca sem acento)
│   └── tests/                pytest: unidade (sem banco) e integração (PostGIS de teste)
├── frontend/                 Next.js (App Router) + React + TypeScript estrito
│   ├── src/app/              páginas: mapa, explorador, território, rede, cenários, otimização, fluxos, painel, dados
│   ├── src/components/       mapa (MapLibre + deck.gl), painéis, gráficos (ECharts), shadcn/ui
│   ├── src/lib/              cliente HTTP tipado com validação Zod, store Zustand, formatação, escalas
│   └── e2e/                  Playwright
├── scripts/                  setup sem Docker (PostgreSQL/PostGIS portátil), banco, ambiente de desenvolvimento
├── data/raw/                 arquivos baixados (fora do Git; reprodutíveis via `app.cli download`)
└── docs/
```

## Fluxo de dados

1. **Ingestão** (`app/ingestion`): cada execução cria um `import_run` (arquivo, SHA-256, contagens, relatório de
   validação). Registros recebem `source_id`, `import_run_id` e `content_hash`; reimportações detectam alterações.
2. **Agregações**: `mv_municipality_infra` (extensão de rodovia/ferrovia/hidrovia por município via interseção
   PostGIS) — pré-calculada porque a interseção nacional é cara e muda só na reimportação.
3. **Grafo** (`app/network/builder.py`): versão imutável em `network_version/node/edge`, com parâmetros,
   premissas, importações usadas e checksum.
4. **Consultas interativas**: a API carrega a versão do grafo em memória (≈2 s, uma vez) e responde rotas em ~10 ms.
5. **Tarefas pesadas** (cenários, otimizações, criticidade, reconstrução da rede): `POST` devolve `job_id`;
   o frontend acompanha `GET /api/jobs/{id}`. Sem Redis: um pool de threads por processo é suficiente para um
   servidor; o contrato permite trocar por fila externa sem mudar o frontend.

## Modelo de dados (PostgreSQL + PostGIS, SRID 4326)

| Tabela | Conteúdo |
|---|---|
| `data_source`, `import_run` | catálogo de fontes e histórico de importações |
| `region`, `state`, `municipality` | base territorial IBGE (população 2022, PIB, regiões imediatas/intermediárias, geometria, ponto representativo) |
| `facility` | instalações; `record_class` ∈ {official, user, synthetic} — oficiais são somente leitura pela API |
| `infra_segment` | trechos rodoviários, ferroviários, hidroviários e eixos estruturantes como importados |
| `network_version`, `network_node`, `network_edge` | grafo versionado; arestas guardam km por classe de via, km federais, transbordos e segmentos de origem |
| `flow` | fluxos OD; `flow_class` ∈ {observed, modeled, hypothetical, synthetic} (restrição CHECK) |
| `assumption` | premissas paramétricas com unidade e justificativa |
| `scenario`, `scenario_change`, `scenario_run` | cenários, alterações e execuções (snapshot de entradas, hashes de entradas/resultados) |
| `optimization_run` | problema, parâmetros, status, qualidade, gap, restrições, premissas e resultados |
| `job` | tarefas assíncronas |

Índices GiST em todas as geometrias; índices por categoria/UF/modal; busca por nome sem acento
(`unaccent_name()` IMMUTABLE + índice funcional).

## Grafo logístico

Construção em EPSG:5880 (SIRGAS 2000 / Brazil Polyconic, metros):

1. Segmentos válidos (exclui rodovias *planejadas* e *em obras de implantação* e trens urbanos de passageiros).
2. Extremidades a menos de 250 m viram o mesmo nó (fecho transitivo via k-d tree).
3. Extremidade solta junto ao interior de outra linha divide essa linha (junção em T). **Cruzamentos sem
   extremidade comum não viram junção** (evita falsas conexões em viadutos e pontes).
4. Municípios (ponto representativo) e instalações são projetados na via mais próxima (até 60 km) e, quando
   existe outra via a até 15 km com ponto de ligação distinto, recebem um segundo conector.
5. Terminais intermodais (portos, terminais portuários/ferroviários, portos secos) recebem arestas de transbordo
   para o nó ferroviário/hidroviário mais próximo (até 15 km).
6. Nós de grau 2 do mesmo modal são contraídos (preservando âncoras e sem criar arestas paralelas).

Cada aresta guarda **km por classe** (duplicada, pavimentada, em obras, implantada, leito natural, travessia,
ferrovia, hidrovia, acesso), km federais e nº de transbordos. Tempo e custo são recalculados vetorialmente
para qualquer conjunto de premissas — cenários de custo não exigem reconstruir a rede.

**Conectores não são atalhos**: os conectores de municípios e instalações não intermodais recebem penalidade
aditiva de 10⁶ nos pesos; um caminho legítimo usa no máximo um conector em cada ponta. Caminhos que
atravessariam um município (entrar por um conector e sair por outro) são detectados e tratados como
"sem ligação". Distâncias, tempos e custos reportados vêm sempre das arestas, nunca dos pesos penalizados.

## Desempenho

- Tiles MVT (`ST_AsMVT`) com seleção por zoom: abaixo de z6 os trechos são agregados por modal/jurisdição
  e simplificados (tile nacional ≈ 80 KB em vez de ≈ 700 KB); cache LRU em memória + `Cache-Control`.
- Instalações (≈3,3 mil pontos) enviadas como GeoJSON enxuto com agrupamento no MapLibre.
- Rotas: Dijkstra do SciPy (C) sobre CSR; matrizes de custo para otimização em segundos.
- Agregações territoriais via view materializada; hexágonos via `ST_HexagonGrid` no banco.
- Geometrias de rotas simplificadas (~300 m) para exibição; cálculos usam a geometria completa.
- GZip nas respostas; paginação no servidor; limites de tamanho em consultas e uploads.

## Segurança

- Validação de entrada com Pydantic e Zod (contratos verificados também no cliente).
- Registros oficiais imutáveis pela API; edições restritas a `record_class = 'user'`.
- Segredos só em `backend/.env`; o navegador acessa a API pelo proxy `/api` do Next.js.
- Banco ouvindo apenas em `localhost`, autenticação SCRAM.
- Sem autenticação de usuários nesta versão (uso local/intranet). Ver [LIMITACOES.md](LIMITACOES.md).

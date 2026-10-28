# LogiTrace — Plataforma Nacional de Inteligência Logística

Plataforma geoespacial para explorar a infraestrutura logística brasileira, analisar o território, calcular rotas
em uma rede multimodal, simular cenários e otimizar redes de distribuição — com dados públicos rastreáveis
(IBGE) e premissas explícitas. Roda **sem Docker**: Node.js, Python e PostgreSQL/PostGIS instalados localmente.

| Camada | Tecnologias |
|---|---|
| Interface | Next.js 16 (App Router), React 19, TypeScript estrito, Tailwind CSS 4, shadcn/ui (Base UI), MapLibre GL JS 6, deck.gl 9, Apache ECharts 6, TanStack Query 5, Zustand 5, Zod 4 |
| API e cálculo | Python 3.11, FastAPI, Pydantic 2, SQLAlchemy 2 + GeoAlchemy2, GeoPandas/Shapely/PyProj/Pyogrio, NetworkX, SciPy (Dijkstra em C), OR-Tools (SCIP, GLOP, Routing), SimPy, ReportLab/Matplotlib, openpyxl |
| Dados | PostgreSQL 17 + PostGIS 3.6 (índices GiST, `ST_AsMVT`, `ST_HexagonGrid`), Alembic |
| Testes | Pytest (unidade + integração com PostGIS), Vitest, Playwright |

---

## 1. O que a plataforma faz

| Módulo | Rota | Destaques |
|---|---|---|
| Mapa nacional | `/` | Tiles vetoriais servidos pelo PostGIS por nível de zoom (rodovias por pavimento, ferrovias, hidrovias, corredores, UFs, municípios), instalações agrupadas, calor, hexágonos, polos econômicos, fluxos em arcos, análise de área desenhada, alcance em horas pela rede, painel de detalhes com proveniência |
| Explorador | `/explorador` | Busca e filtros combinados (categoria, modal, UF, classe do registro, capacidade, área visível), lista paginada e ordenável sincronizada com o mapa, exportação CSV/XLSX/GeoJSON, cadastro e importação (CSV/GeoJSON) de instalações do usuário com validação |
| Inteligência territorial | `/territorio` | Indicadores com denominador, período e fonte (por região, UF, região imediata, município), coropléticos por quantis, HHI/Gini, hexágonos e calor, **cobertura pela rede** (não em linha reta) com classificação que considera população, oferta relativa (QL), distância e conectividade, áreas candidatas (heurística gulosa), comparação entre UFs, relatório PDF |
| Motor de redes | `/rede` | Rotas por distância, tempo ou custo; rodoviário ou multimodal; até 5 alternativas; sinuosidade; conectividade e componentes isolados; pontes (NetworkX) com população isolada; criticidade por uso e impacto de remoção |
| Simulador de cenários | `/cenarios` | Interdições (trecho clicado, área, terminal), nova instalação, remoção, capacidade, custos/velocidades, fatores de demanda; avaliação base × cenário (pares OD, cobertura, alocação ótima LP, simulação SimPy de docas); reexecução reprodutível com hash; exportações e PDF |
| Otimização | `/otimizacao` | p-mediana, localização capacitada, máxima cobertura (MCLP), alocação/transporte (LP com preços-sombra), fronteira custo × cobertura, roteirização (CVRP); status OPTIMAL/FEASIBLE/HEURISTIC explícito, gap, restrições e premissas |
| Fluxos | `/fluxos` | Fluxos IBGE 2024 por modal (rodoviário CIOT, ferroviário, aquaviário, aéreo), arcos com espessura ∝ √volume, matriz OD, concentração, fluxos hipotéticos — classes observado/modelado/hipotético/sintético sempre separadas |
| Painel | `/painel` | KPIs calculados com metadados (definição, unidade, período, fonte, denominador, limitações), resultados recentes de cenários e otimizações, conexões críticas |
| Dados | `/dados` | Catálogo de fontes (URL, licença, atribuição, cobertura, data, atualização, limitações), histórico de importações, premissas editáveis, versões do grafo |

Documentação da API (OpenAPI): `http://localhost:8000/docs`.

---

## 2. Instalação (Windows, sem Docker)

Pré-requisitos: **Node.js ≥ 20**, **Python 3.11**, PowerShell. PostgreSQL é opcional (o script instala uma cópia portátil).

```powershell
.\scripts\setup.ps1
```

O script:
1. `setup-postgres.ps1` — baixa os binários oficiais do PostgreSQL 17 (EDB) e o bundle PostGIS 3.6 (OSGeo, MD5 verificado) para `.runtime\`, inicializa o cluster na porta **5433** com autenticação SCRAM e senhas geradas, cria `logitrace` e `logitrace_test` com PostGIS e grava `backend\.env`. Nada é instalado como serviço; não requer administrador.
2. Cria o ambiente Python (`backend\.venv`), instala `requirements-dev.txt` (produção + ingestão + testes) e aplica as migrações Alembic.
3. `python -m app.cli setup` — baixa as bases públicas (IBGE, OurAirports), importa território, instalações, segmentos e fluxos, recalcula agregações e constrói o grafo.
4. `npm install` no frontend (o `postinstall` copia o worker do MapLibre para `public/`).

Para iniciar depois: `.\scripts\dev.ps1` (banco + API em :8000 + Next.js em :3000). Para parar o banco: `.\scripts\db.ps1 stop`.

### Usando um PostgreSQL já instalado (Windows, Linux ou macOS)

```bash
createdb logitrace && createdb logitrace_test
psql -d logitrace -c "CREATE EXTENSION postgis"; psql -d logitrace_test -c "CREATE EXTENSION postgis"
cp backend/.env.example backend/.env   # ajuste usuário, senha e porta
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head && .venv/bin/python -m app.cli setup
.venv/bin/uvicorn app.main:app --port 8000
cd ../frontend && npm install && npm run dev
```

### Configuração

| Variável | Onde | Padrão | Descrição |
|---|---|---|---|
| `LOGITRACE_DATABASE_URL` | `backend/.env` | — | Conexão SQLAlchemy (psycopg) |
| `LOGITRACE_TEST_DATABASE_URL` | `backend/.env` | — | Banco usado pelos testes de integração (recriado a cada execução) |
| `LOGITRACE_CORS_ORIGINS` | `backend/.env` | `["http://localhost:3000"]` | Origens permitidas |
| `LOGITRACE_SOLVER_TIME_LIMIT_S` | `backend/.env` | `60` | Tempo-limite padrão dos solvers |
| `LOGITRACE_JOB_WORKERS` | `backend/.env` | `2` | Tarefas pesadas simultâneas |
| `LOGITRACE_API_URL` | ambiente do Next.js | `http://localhost:8000` | Destino do proxy `/api/*` (sem expor a URL ao navegador) |
| `NEXT_PUBLIC_BASEMAP_STYLE` | `frontend/.env.local` | OpenFreeMap *dark* | Estilo do mapa base; se indisponível, a aplicação usa fundo neutro e mantém as camadas próprias |

Nenhuma chave de API é necessária. Segredos ficam apenas em `backend/.env` (fora do Git).

---

## 3. Linha de comando do backend

```bash
python -m app.cli download          # baixa os arquivos para data/raw (idempotente)
python -m app.cli ingest            # território, instalações, terminais, segmentos, fluxos (+ agregações)
python -m app.cli ingest --only flows
python -m app.cli refresh-stats     # recalcula mv_municipality_infra
python -m app.cli build-network     # nova versão imutável do grafo
python -m app.cli setup             # tudo acima
```

Reimportações são idempotentes: cada registro tem hash de conteúdo; a execução registra novos, alterados,
inalterados, rejeitados e ausentes (registros oficiais não são apagados silenciosamente).

---

## 4. Testes

```bash
cd backend && .venv/Scripts/python -m pytest          # 46 testes: unidade + integração (PostGIS)
cd frontend && npm test                              # Vitest
cd frontend && npm run test:e2e                      # Playwright (requer API e dados carregados)
npm run typecheck && npm run build                   # TypeScript estrito e build de produção
```

Os testes incluem casos de referência calculáveis à mão (grafo de 7 nós, p-mediana com ótimo conhecido,
LP com preço-sombra esperado), interrupções que alteram a conectividade, restrições de capacidade,
consistência de custos, importação/validação, contratos da API e reprodutibilidade de cenários.
`LOGITRACE_SKIP_DB=1` executa apenas os testes que não usam banco.

---

## 5. Documentação adicional

- [docs/ARQUITETURA.md](docs/ARQUITETURA.md) — camadas, modelo de dados, grafo, motores de cálculo, desempenho.
- [docs/DADOS.md](docs/DADOS.md) — fontes, licenças, cobertura, validação e proveniência.
- [docs/METODOLOGIA.md](docs/METODOLOGIA.md) — rotas, cobertura, cenários, otimização, premissas.
- [docs/LIMITACOES.md](docs/LIMITACOES.md) — o que a plataforma não afirma e por quê.

Atribuição: dados © IBGE (Logística dos Transportes 2014 e 2024, Censo 2022, Malhas, PIB dos Municípios);
nomes de aeroportos: OurAirports (domínio público); mapa base © OpenStreetMap contributors / OpenFreeMap.

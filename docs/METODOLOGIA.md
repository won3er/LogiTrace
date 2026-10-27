# Metodologia

## Rotas
- Caminho mínimo por Dijkstra (SciPy) no grafo versionado; métrica = distância (km), tempo (h) ou custo (R$/t).
- Tempo = Σ km por classe ÷ velocidade da classe + transbordos × tempo de transbordo.
- Custo = Σ km por classe × custo/t·km do modal (× fator de não pavimentada) + km federais × pedágio + transbordos × custo de transbordo (+ valor do tempo, se definido).
- Alternativas: método de penalização (arestas usadas ficam 60% mais caras na busca seguinte; descarta rotas com > 90% de sobreposição).
- Origem/destino em ponto livre: ligado ao nó rodoviário mais próximo (distância de ligação informada).
- A distância em linha reta é exibida apenas para comparação (índice de sinuosidade).

## Conectividade e criticidade
- Componentes conexos (SciPy), pontes (NetworkX `bridges`) agregadas em árvore de componentes 2-aresta-conexos para medir a população isolada por cada ponte.
- Criticidade: pares entre capitais com peso gravitacional (pop_i × pop_j). Uso de uma aresta = soma dos pesos dos pares cujo menor caminho a utiliza. Impacto = variação média ponderada do custo quando a aresta é removida e as rotas recalculadas; pares desconectados contados à parte.

## Inteligência territorial
- Indicadores sempre com numerador, denominador, período e fonte; classes de mapa por quantis.
- Concentração: HHI e Gini entre unidades com ≥ 1 instalação.
- **Cobertura**: distância na rede (Dijkstra multi-origem) até a instalação mais próxima das categorias escolhidas.
  Classificação por região imediata:
  - *baixa cobertura relativa*: quociente locacional (oferta ÷ população relativas) < 0,5 **e** < 50% da população dentro do limiar;
  - *atendida por vizinhas*: QL < 0,5, mas ≥ 80% da população alcança instalação dentro do limiar;
  - *sem conexão*: > 50% da população sem ligação terrestre na base;
  - *adequada*: demais casos. Ter poucas instalações, isoladamente, nunca classifica uma região como mal atendida.
- Áreas candidatas: heurística gulosa de máxima cobertura incremental (garantia ≥ 1 − 1/e do ótimo); para solução exata use a otimização MCLP.

## Cenários
Base e cenário são avaliados pela mesma rotina; o cenário aplica alterações em memória:

| Alteração | Efeito |
|---|---|
| `closure` | remove arestas por segmento, aresta, área (bbox/polígono) ou terminal |
| `new_facility` | nova instalação ligada ao nó rodoviário mais próximo (trecho de acesso somado ao custo) |
| `remove_facility`, `capacity` | altera o conjunto e as capacidades (t/ano) das instalações de atendimento |
| `cost` | sobrescreve premissas (custos, velocidades, pedágio, transbordo, valor do tempo) |
| `demand` | fator global ou por UF |

Avaliação: (1) pares OD — pares definidos ou todos os 351 pares de capitais; (2) cobertura; (3) alocação de
demanda por LP (GLOP, ótimo comprovado) com capacidades, demanda não atendida penalizada e preços-sombra
(gargalos); (4) opcionalmente, simulação de eventos discretos (SimPy) das docas para filas e utilização.
Deltas de distância/tempo/custo somam apenas pares conectados nos dois estados; desconexões são contadas à parte.

**Reprodutibilidade**: cada execução grava o snapshot completo das entradas (configuração, alterações, premissas,
versão da rede) e os hashes de entradas e de resultados. "Reexecutar" usa exatamente o mesmo snapshot e
compara os hashes (testado automaticamente).

## Otimização (OR-Tools)
| Problema | Formulação | Solver | Qualidade |
|---|---|---|---|
| p-mediana | min Σ d_i c_ij x_ij; Σ_j x_ij = 1; x_ij ≤ y_j; Σ y_j = p | SCIP (MIP) | OPTIMAL ou FEASIBLE (gap) |
| Localização capacitada | min Σ f_j y_j + Σ d_i c_ij x_ij + M Σ d_i u_i; Σ_j x_ij + u_i = 1; Σ_i d_i x_ij ≤ K_j y_j | SCIP (MIP) | idem |
| Máxima cobertura | max Σ d_i z_i; z_i ≤ Σ_{j∈N_i} y_j; Σ y_j = p | SCIP (MIP) | idem |
| Transporte/alocação | min Σ c_ij x_ij + M Σ u_i; balanço de demanda; capacidade | GLOP (LP) | OPTIMAL (+ preços-sombra) |
| Fronteira custo × cobertura | série de p-mediana e MCLP para p = 1…P; dominância em (p, custo, cobertura) | SCIP | pior status da série |
| CVRP | roteirização com capacidade e distância máxima | OR-Tools Routing (Guided Local Search) | HEURISTIC |

Custo e cobertura nunca são somados implicitamente: a fronteira mostra as alternativas não dominadas.
Toda execução registra objetivo, restrições, premissas, status, gap, tempo de solução e hash das entradas.

## Premissas paramétricas
Velocidades por classe de via, custos por t·km por modal, fator de vias não pavimentadas, pedágio (0 por padrão),
transbordo, valor do tempo (0 por padrão), tolerâncias da rede, demanda per capita, giro anual de armazéns e raio
de cobertura. Todas têm unidade e justificativa (`GET /api/assumptions`, página **Dados**) e podem ser
sobrescritas por cenário sem alterar o padrão. Nenhuma é apresentada como dado observado.

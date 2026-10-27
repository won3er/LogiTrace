# Limitações conhecidas

## Dados
- **Malha e instalações de 2014** (IBGE/SNV): não refletem duplicações, concessões, novas ferrovias (ex.: trechos da FIOL/FICO) ou terminais posteriores. Fluxos são de 2024 (rodoviário: CIOT 2023), portanto há defasagem entre rede e fluxos.
- **Sem capacidade viária, pedágios reais, restrições de peso/altura ou sazonalidade** de hidrovias. Tempos e custos são premissas.
- **Armazenagem agregada por município**, sem identificação de armazéns individuais. Não existe base pública nacional de centros de distribuição privados: CDs devem ser cadastrados pelo usuário.
- **Demanda = população × premissa** (proxy de consumo). Para um produto específico, substitua por dados próprios.
- Fluxos do IBGE são **ligações bidirecionais esquemáticas**: não indicam sentido nem trajeto; o rodoviário conta operações (CIOT), não toneladas. Unidades diferentes nunca são somadas.
- Coordenadas de algumas instalações (ex.: portos) são aproximadas na fonte; terminais 2024 usam a extremidade da ligação esquemática.
- Fontes ANTT, ANTAQ, DNIT e ONTL não foram integradas diretamente (ver [DADOS.md](DADOS.md)).

## Modelagem de rede
- Bitolas ferroviárias diferentes e direitos de passagem entre concessionárias não são modelados; trechos ferroviários próximos (≤ 250 m) são unidos.
- Cruzamentos sem extremidade comum não viram junção (correto para viadutos, mas pode omitir algumas interseções reais em nível).
- Conectores de acesso são linhas retas × 1,3 até a via mais próxima (até 60 km); 62 municípios sem via a essa distância ficam fora da rede (majoritariamente acesso fluvial/aéreo).
- Mão única e restrições de conversão não existem na base: o grafo é não direcionado.
- Interdições removem arestas inteiras do grafo contraído; a granularidade depende do comprimento dos trechos.

## Plataforma
- Sem autenticação/perfis de usuário nesta versão (pensada para uso local ou em intranet). A estrutura de API permite acrescentar autenticação (ex.: OAuth2/JWT do FastAPI) e controle de acesso por papel.
- Tarefas assíncronas rodam em threads do processo da API: reiniciar a API interrompe tarefas em andamento (o status fica registrado). Para múltiplos servidores, substituir por fila externa (ex.: Redis + RQ/Celery).
- O mapa base depende do serviço OpenFreeMap; sem internet, a aplicação usa fundo neutro e mantém todas as camadas próprias.
- Relatórios PDF usam mapas estáticos (Matplotlib) para garantir reprodutibilidade, não capturas do mapa interativo.

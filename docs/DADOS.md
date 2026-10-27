# Fontes e ingestão de dados

O catálogo completo (com contagens e última importação) está em `GET /api/sources` e na página **Dados**.

| Fonte | URL | Licença / atribuição | Cobertura | Referência | Método | Limitações |
|---|---|---|---|---|---|---|
| IBGE — API de Localidades | servicodados.ibge.gov.br/api/v1/localidades/municipios | Dados públicos IBGE, citar a fonte | 5.570 municípios, UFs, regiões imediatas/intermediárias | divisão vigente no download | JSON via API | sem coordenadas |
| IBGE — Malhas territoriais | servicodados.ibge.gov.br/api/v3/malhas/paises/BR (qualidade intermediária) | idem | UFs e municípios | malha vigente | GeoJSON via API | geometria simplificada; ponto representativo = `ST_PointOnSurface`, não a sede |
| IBGE — Censo 2022 (SIDRA 4709) | apisidra.ibge.gov.br/values/t/4709/n6/all/v/93/p/2022 | idem | municípios | 2022 | API SIDRA | população é *proxy* de demanda |
| IBGE — PIB dos Municípios (SIDRA 5938, var. 37) | apisidra.ibge.gov.br/values/t/5938/n6/all/v/37/p/last | idem | municípios | último ano publicado | API SIDRA | preços correntes; polos = limiar de PIB |
| IBGE — Logística dos Transportes 2014 | geoftp.ibge.gov.br/…/logistica_dos_transportes/2014/base_de_dados_2014.zip | idem | rodovias (SNV), ferrovias, hidrovias, portos, terminais, portos secos, armazéns, aeroportos, aeródromos, fronteiras, eixos estruturantes | 2014 (aeroportos 2010) | shapefiles; importador por camada | ver abaixo |
| IBGE — Logística dos Transportes 2024 (fluxos consolidados) | geoftp.ibge.gov.br/…/2024/Base_de_dados/Fluxos_Consolidados_de_Mercadorias/ | idem | ligações bidirecionais: rodoviário (CIOT 2023), ferroviário (TU), aquaviário (t, por mercadoria), aéreo (kg) | publicação 2024 | GeoPackages | ligações esquemáticas; CIOT conta operações, não toneladas |
| OurAirports | davidmegginson.github.io/ourairports-data/airports.csv | domínio público | aeroportos | contínua | CSV | usado só para nomes/ICAO (associação espacial < 5 km) |
| OpenFreeMap / OpenStreetMap | openfreemap.org | ODbL — © OpenStreetMap contributors | mundial | contínua | estilo de mapa no navegador | apenas fundo; não alimenta cálculos |

Fontes avaliadas e não integradas nesta versão: ANTT (bases de concessões/fluxos), ANTAQ (Estatístico
Aquaviário), DNIT (SNV atualizado), Infra S.A./ONTL. Os fluxos IBGE 2024 já consolidam ANTT/ANTAQ/ANAC/CIOT;
a arquitetura de importadores (`app/ingestion/*.py` + catálogo em `sources.py`) permite acrescentar cada uma
como novo módulo. Não há *scraping*: apenas arquivos e APIs publicados.

## Validação aplicada

| Verificação | Implementação |
|---|---|
| Sistema de referência | camada sem `.prj` é rejeitada; transformação explícita para EPSG:4326 (SIRGAS 2000 → WGS84) |
| Geometria | pontos nulos, (0,0), não finitos ou fora do envelope do Brasil rejeitados; linhas/polígonos inválidos reparados com `make_valid` (registrado como aviso) |
| Campos obrigatórios | nome/coordenadas em cadastros do usuário; códigos de município validados contra a base IBGE |
| Duplicidade | por `(fonte, identificador externo)`; no upload do usuário, por nome + coordenada |
| Codificação | shapefiles com UTF-8 declarado e latin-1 real corrigidos registro a registro |
| Valores | fluxos com valor ausente/não positivo rejeitados; unidades diferentes nunca são somadas |

Cada `import_run` guarda SHA-256 do arquivo, contagens (lidos, novos, alterados, inalterados, rejeitados),
amostra de IDs alterados e de registros ausentes no novo arquivo.

## Instalações importadas (observações por categoria)

| Categoria | Registros | Observações |
|---|---|---|
| Armazenagem | 1.724 | **um registro agregado por município**, na sede; capacidade estática (t); sem nome/operador |
| Aeródromos | 557 | ICAO e tipo de uso |
| Terminais portuários | 249 (2014) + 185 (2024) | os de 2024 vêm das extremidades das ligações aquaviárias (código ANTAQ) |
| Terminais ferroviários | 255 | extremidades das ligações ferroviárias 2024 (código do terminal) |
| Aeroportos | 138 | passageiros e carga 2010; nome via OurAirports quando associado |
| Portos secos | 62 | recinto alfandegado |
| Portos públicos | 61 | movimentação total; nome derivado do município |
| Pontos de fronteira | 25 | administração |

Nenhum atributo ausente é estimado: capacidade, operador e situação aparecem como "não informado na fonte".

"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Navigation, Timer, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ErrorBox, KV, Loading } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { CATEGORY_COLORS, MODAL_LABELS } from "@/lib/constants";
import { fmt, fmtBRL, fmtCompact } from "@/lib/format";
import type { Selection } from "@/lib/store";

type Reach = { municipalities: number; population: number; codes: number[]; hours: number; note: string };

const RELIABILITY: Record<string, string> = { alta: "text-emerald-300", média: "text-amber-300", baixa: "text-red-300" };

export function EntityDetails({ selection, onClose, onReach }: {
  selection: NonNullable<Selection>;
  onClose: () => void;
  onReach?: (r: Reach | null) => void;
}) {
  return (
    <div className="flex h-full flex-col" data-testid="entity-details">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          {selection.kind === "facility" ? "Instalação" : selection.kind === "segment" ? "Segmento de infraestrutura" : "Município"}
        </span>
        <button className="ml-auto text-muted-foreground hover:text-foreground" onClick={onClose} aria-label="Fechar detalhes">
          <X className="size-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {selection.kind === "facility" && <FacilityDetails id={selection.id} onReach={onReach} />}
        {selection.kind === "segment" && <SegmentDetails id={selection.id} />}
        {selection.kind === "municipality" && <MunicipalityDetails code={selection.code} />}
      </div>
    </div>
  );
}

function FacilityDetails({ id, onReach }: { id: number; onReach?: (r: Reach | null) => void }) {
  const q = useQuery({ queryKey: ["facility", id], queryFn: () => api<Record<string, any>>(`/facilities/${id}`) });
  const [hours, setHours] = useState(6);
  const reach = useQuery({
    queryKey: ["reach", id, hours],
    queryFn: () => api<Reach>(`/facilities/${id}/reach`, { query: { hours } }),
    enabled: false,
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const f = q.data!;
  const attrs = Object.entries(f.attributes ?? {}).filter(([, v]) => v !== null && v !== "");
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="flex items-center gap-2">
          <span className="size-2.5 rounded-full" style={{ background: CATEGORY_COLORS[f.category] }} />
          <span className="text-xs text-muted-foreground">{f.category_label}</span>
          {f.record_class !== "official" && <Badge variant="outline">{f.record_class === "user" ? "usuário" : "sintético"}</Badge>}
        </div>
        <h3 className="mt-1 text-base leading-snug font-semibold">{f.name}</h3>
        <div className="text-xs text-muted-foreground">
          {f.municipality_name ?? "município não identificado"}
          {f.uf ? `/${f.uf}` : ""} · {fmt(f.lat, 4)}, {fmt(f.lon, 4)}
        </div>
      </div>
      <div className="rounded-lg border border-border p-2">
        <KV k="Modalidade" v={MODAL_LABELS[f.modal] ?? f.modal} />
        <KV k="Subcategoria" v={f.subcategory ?? "—"} />
        <KV k="Operador" v={f.operator ?? "não informado na fonte"} />
        <KV k="Capacidade" v={f.capacity_value !== null ? `${fmt(f.capacity_value, 0)} ${f.capacity_unit ?? ""}` : "não informada na fonte"} />
        <KV k="Situação" v={f.status ?? "não informada na fonte"} />
        <KV k="Confiabilidade" v={<span className={RELIABILITY[f.reliability]}>{f.reliability}</span>} />
        <KV k="Referência" v={f.source_reference ?? "—"} />
      </div>
      {attrs.length > 0 && (
        <div className="rounded-lg border border-border p-2">
          <div className="mb-1 text-xs font-medium text-muted-foreground">Atributos da fonte</div>
          {attrs.map(([k, v]) => (
            <KV key={k} k={k.replaceAll("_", " ")} v={typeof v === "number" ? fmt(v, 2) : String(v)} />
          ))}
        </div>
      )}
      {f.limitations && <p className="rounded-lg bg-amber-500/10 p-2 text-xs text-amber-100/90">Limitações: {f.limitations}</p>}
      {f.source && (
        <div className="space-y-0.5 text-xs text-muted-foreground">
          <div>
            Fonte: <span className="text-foreground">{f.source.name}</span> ({f.source.publisher})
          </div>
          <div>Licença: {f.source.license}</div>
          <a href={f.source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
            origem dos dados <ExternalLink className="size-3" />
          </a>
          <div>Importação #{f.import_run_id ?? "—"} · atualizado {new Date(f.updated_at).toLocaleDateString("pt-BR")}</div>
        </div>
      )}
      {f.nearest_municipality && (
        <div className="text-xs text-muted-foreground">
          Sede municipal mais próxima: {f.nearest_municipality.name}/{f.nearest_municipality.uf} ({fmt(f.nearest_municipality.straight_km, 1)} km em linha reta)
        </div>
      )}
      <div className="space-y-2 rounded-lg border border-border p-2">
        <div className="flex items-center gap-2 text-xs font-medium">
          <Timer className="size-3.5" /> Alcance pela rede rodoviária
        </div>
        <div className="flex items-center gap-2">
          <select
            className="h-8 rounded-md border border-input bg-input/30 px-2 text-sm"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            aria-label="Horas de viagem"
          >
            {[2, 4, 6, 8, 12, 24].map((h) => (
              <option key={h} value={h}>
                até {h} h
              </option>
            ))}
          </select>
          <Button
            size="sm"
            variant="secondary"
            onClick={async () => {
              const r = await reach.refetch();
              onReach?.(r.data ?? null);
            }}
          >
            Calcular
          </Button>
        </div>
        {reach.data && (
          <div className="text-xs">
            <b>{reach.data.municipalities}</b> municípios · <b>{fmtCompact(reach.data.population)}</b> hab. em até {reach.data.hours} h
            <div className="mt-0.5 text-muted-foreground">{reach.data.note}</div>
          </div>
        )}
        {reach.error && <ErrorBox error={reach.error} />}
      </div>
      <Link href={`/rede?origin_facility=${id}`} className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
        <Navigation className="size-3" /> Traçar rota a partir desta instalação
      </Link>
    </div>
  );
}

function SegmentDetails({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["segment", id], queryFn: () => api<Record<string, any>>(`/network/segments/${id}`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const s = q.data!;
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="text-xs text-muted-foreground">{MODAL_LABELS[s.modal] ?? s.modal}</div>
        <h3 className="mt-1 text-base leading-snug font-semibold">{s.code ?? s.name ?? "Trecho"}</h3>
        {s.name && s.code && <div className="text-xs text-muted-foreground">{s.name}</div>}
      </div>
      <div className="rounded-lg border border-border p-2">
        <KV k="Extensão" v={`${fmt(s.length_km, 2)} km`} />
        <KV k="Jurisdição" v={s.jurisdiction ?? "—"} />
        <KV k="Superfície / situação" v={s.surface ?? "—"} />
        <KV k="UF" v={s.uf ?? "—"} />
        {s.attributes?.operadora && <KV k="Operadora" v={s.attributes.operadora} />}
        <KV k="Arestas do grafo" v={s.network_edges?.length ?? 0} />
        <KV k="Capacidade" v="não disponível na fonte" />
      </div>
      <p className="text-xs text-muted-foreground">
        Fonte: {s.source} ({s.reference_date}). {s.limitations}
      </p>
      <Link href={`/cenarios?close_segment=${id}`} className="inline-flex text-xs text-primary hover:underline">
        Simular interdição deste trecho →
      </Link>
    </div>
  );
}

function MunicipalityDetails({ code }: { code: number }) {
  const q = useQuery({ queryKey: ["municipality", code], queryFn: () => api<Record<string, any>>(`/territory/municipalities/${code}`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const m = q.data!;
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="text-xs text-muted-foreground">
          {m.region} · RGI {m.immediate_region_name}
        </div>
        <h3 className="mt-1 text-base font-semibold">
          {m.name}/{m.uf}
        </h3>
        <div className="text-xs text-muted-foreground">Código IBGE {m.code}</div>
      </div>
      <div className="rounded-lg border border-border p-2">
        <KV k={`População (${m.population_year})`} v={fmt(m.population, 0)} />
        <KV k={`PIB (${m.gdp_year ?? "—"})`} v={m.gdp_thousand_brl ? fmtBRL(m.gdp_thousand_brl * 1000) : "—"} />
        <KV k="Área" v={`${fmt(m.area_km2, 1)} km²`} />
        <KV k="Rodovias" v={`${fmt(m.infrastructure?.road?.km, 1)} km (${fmt(m.infrastructure?.road?.km_paved, 1)} pav.)`} />
        <KV k="Ferrovias" v={`${fmt(m.infrastructure?.rail?.km ?? 0, 1)} km`} />
        <KV k="Hidrovias" v={`${fmt(m.infrastructure?.waterway?.km ?? 0, 1)} km`} />
      </div>
      {m.facilities?.length > 0 && (
        <div className="rounded-lg border border-border p-2">
          <div className="mb-1 text-xs font-medium text-muted-foreground">Instalações no município ({m.facilities.length})</div>
          {m.facilities.slice(0, 12).map((f: any) => (
            <div key={f.id} className="flex items-center gap-2 py-0.5 text-xs">
              <span className="size-2 rounded-full" style={{ background: CATEGORY_COLORS[f.category] }} />
              <span className="truncate">{f.name}</span>
            </div>
          ))}
        </div>
      )}
      <div className="rounded-lg border border-border p-2">
        <div className="mb-1 text-xs font-medium text-muted-foreground">Instalação mais próxima por categoria (linha reta)</div>
        {m.nearest_by_category?.map((n: any) => (
          <KV key={n.category} k={n.category} v={`${fmt(n.straight_km, 1)} km`} />
        ))}
      </div>
      {m.observed_flows?.length > 0 && (
        <div className="rounded-lg border border-border p-2">
          <div className="mb-1 text-xs font-medium text-muted-foreground">Fluxos observados (IBGE 2024)</div>
          {m.observed_flows.map((f: any) => (
            <KV key={f.dataset} k={f.dataset.replace("ibge_2024_", "")} v={`${fmtCompact(f.total)} ${f.unit} · ${f.links} lig.`} />
          ))}
        </div>
      )}
      <ul className="space-y-0.5 text-[11px] text-muted-foreground">
        {m.notes?.map((n: string) => <li key={n}>• {n}</li>)}
      </ul>
    </div>
  );
}

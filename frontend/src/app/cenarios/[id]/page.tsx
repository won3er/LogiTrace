"use client";

import type { Layer } from "@deck.gl/core";
import { GeoJsonLayer, ScatterplotLayer } from "@deck.gl/layers";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileText, MousePointerClick, Play, Plus, RotateCcw, Save, Trash2, XCircle } from "lucide-react";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Chart } from "@/components/chart";
import { Caveat, ErrorBox, Field, JobProgress, KV, Loading, Stat } from "@/components/common";
import { MultiCheck } from "@/components/multi-check";
import { MunicipalityPicker } from "@/components/municipality-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useJob } from "@/hooks/use-job";
import { api, downloadUrl } from "@/lib/api";
import { UFS } from "@/lib/constants";
import { fmt, fmtBRL, fmtDate, fmtPct, fmtSigned } from "@/lib/format";
import { FacilitySchema, pageOf, type MunicipalityHit } from "@/lib/types";

const MapView = dynamic(() => import("@/components/map/map-view").then((m) => m.MapView), { ssr: false });

type Change = { change_type: string; payload: Record<string, any>; note?: string | null };
type Config = Record<string, any>;
type Pick = null | "segment" | "bbox" | "new_facility";
const CHANGE_LABELS: Record<string, string> = {
  closure: "Interdição", new_facility: "Nova instalação", remove_facility: "Remover instalação",
  capacity: "Capacidade", cost: "Custos", demand: "Demanda",
};

export default function ScenarioDetail() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const sc = useQuery({ queryKey: ["scenario", id], queryFn: () => api<Record<string, any>>(`/scenarios/${id}`) });
  const assumptions = useQuery({ queryKey: ["assumptions"], queryFn: () => api<any[]>("/assumptions") });
  const [name, setName] = useState("");
  const [cfg, setCfg] = useState<Config | null>(null);
  const [changes, setChanges] = useState<Change[]>([]);
  const [services, setServices] = useState<{ id: number; name: string }[]>([]);
  const [pick, setPick] = useState<Pick>(null);
  const [bboxStart, setBboxStart] = useState<[number, number] | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (sc.data && cfg === null) {
      setName(sc.data.name);
      setCfg(sc.data.config);
      setChanges(sc.data.changes.map((c: Change) => ({ change_type: c.change_type, payload: c.payload, note: c.note })));
      setRunId(sc.data.runs[0]?.id ?? null);
      const ids: number[] = sc.data.config.service_facility_ids ?? [];
      if (ids.length)
        Promise.all(ids.map((i) => api<Record<string, any>>(`/facilities/${i}`).catch(() => ({ id: i, name: `#${i}` }))))
          .then((fs) => setServices(fs.map((f) => ({ id: f.id, name: f.name }))));
    }
  }, [sc.data, cfg]);

  const upd = (patch: Config) => { setCfg((c) => ({ ...c!, ...patch })); setDirty(true); };
  const addChange = (c: Change) => { setChanges((cs) => [...cs, c]); setDirty(true); };

  const save = useMutation({
    mutationFn: () => api(`/scenarios/${id}`, { method: "PUT", body: { name, description: sc.data?.description, config: { ...cfg, service_facility_ids: services.map((s) => s.id) }, changes } }),
    onSuccess: () => { setDirty(false); qc.invalidateQueries({ queryKey: ["scenario", id] }); },
  });
  const run = useMutation({
    mutationFn: async () => {
      if (dirty) await save.mutateAsync();
      return api<{ job_id: number }>(`/scenarios/${id}/run`, { method: "POST" });
    },
    onSuccess: (r) => setJobId(r.job_id),
  });
  const rerun = useMutation({
    mutationFn: (rid: number) => api<{ job_id: number }>(`/scenarios/runs/${rid}/rerun`, { method: "POST" }),
    onSuccess: (r) => setJobId(r.job_id),
  });
  const job = useJob(jobId);
  useEffect(() => {
    if (job.data?.status === "success" && job.data.ref_id) {
      setRunId(job.data.ref_id);
      qc.invalidateQueries({ queryKey: ["scenario", id] });
      toast.success("Cenário executado");
    }
  }, [job.data?.status, job.data?.ref_id, id, qc]);
  const result = useQuery({ queryKey: ["scenario-run", runId], queryFn: () => api<Record<string, any>>(`/scenarios/runs/${runId}`), enabled: !!runId });
  const routes = useQuery({ queryKey: ["scenario-routes", runId], queryFn: () => api<GeoJSON.FeatureCollection>(`/scenarios/runs/${runId}/routes`), enabled: result.data?.status === "success" });

  const onMapClick = async (ll: [number, number]) => {
    if (pick === "segment") {
      const s = await api<Record<string, any>>("/network/nearest", { query: { lon: ll[0], lat: ll[1] } });
      if (s?.id) { addChange({ change_type: "closure", payload: { segment_ids: [s.id] }, note: `${s.code ?? s.modal} — ${s.name ?? ""}`.slice(0, 120) }); toast.info(`Trecho ${s.code ?? s.id} interditado (a ${fmt(s.km, 2)} km do clique)`); }
      setPick(null);
    } else if (pick === "bbox") {
      if (!bboxStart) { setBboxStart(ll); return; }
      const b = [Math.min(bboxStart[0], ll[0]), Math.min(bboxStart[1], ll[1]), Math.max(bboxStart[0], ll[0]), Math.max(bboxStart[1], ll[1])];
      addChange({ change_type: "closure", payload: { bbox: b.map((x) => +x.toFixed(4)) }, note: "área interditada" });
      setBboxStart(null);
      setPick(null);
    } else if (pick === "new_facility") {
      addChange({ change_type: "new_facility", payload: { lon: +ll[0].toFixed(5), lat: +ll[1].toFixed(5), name: `Novo CD ${changes.filter((c) => c.change_type === "new_facility").length + 1}`, capacity_t: 2_000_000 } });
      setPick(null);
    }
  };

  const r = result.data;
  const deckLayers = useMemo(() => {
    const out: Layer[] = [];
    if (routes.data) {
      out.push(new GeoJsonLayer({ id: "base", data: { ...routes.data, features: routes.data.features.filter((f: any) => f.properties.kind === "base") } as any,
        getLineColor: [148, 163, 184, 170], lineWidthMinPixels: 4, pickable: true }));
      out.push(new GeoJsonLayer({ id: "scen", data: { ...routes.data, features: routes.data.features.filter((f: any) => f.properties.kind === "scenario") } as any,
        getLineColor: [244, 114, 182, 220], lineWidthMinPixels: 2, pickable: true }));
      out.push(new GeoJsonLayer({ id: "closed", data: { ...routes.data, features: routes.data.features.filter((f: any) => f.properties.kind === "closed") } as any,
        getLineColor: [239, 68, 68, 255], lineWidthMinPixels: 6 }));
    }
    const svc = r?.results?.scenario?.service?.open_facilities ?? [];
    if (svc.length)
      out.push(new ScatterplotLayer({ id: "svc", data: svc, pickable: true, getPosition: (f: any) => [f.lon, f.lat], radiusUnits: "pixels",
        getRadius: (f: any) => 6 + 10 * Math.min(1, f.utilization ?? 0), getFillColor: (f: any) => (f.binding ? [239, 68, 68, 220] : [34, 211, 238, 220]),
        getLineColor: [255, 255, 255], stroked: true, lineWidthMinPixels: 1.5 }));
    const newF = changes.filter((c) => c.change_type === "new_facility").map((c) => c.payload);
    if (newF.length)
      out.push(new ScatterplotLayer({ id: "newf", data: newF, getPosition: (p: any) => [p.lon, p.lat], getRadius: 9, radiusUnits: "pixels",
        getFillColor: [250, 204, 21, 220], getLineColor: [15, 23, 42], stroked: true, lineWidthMinPixels: 2 }));
    const boxes = changes.filter((c) => c.change_type === "closure" && c.payload.bbox).map((c) => c.payload.bbox);
    if (boxes.length)
      out.push(new GeoJsonLayer({ id: "boxes", data: { type: "FeatureCollection", features: boxes.map((b: number[]) => ({ type: "Feature", properties: {},
        geometry: { type: "Polygon", coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]] } })) } as any,
        getFillColor: [239, 68, 68, 30], getLineColor: [239, 68, 68, 200], lineWidthMinPixels: 1.5 }));
    return out;
  }, [routes.data, r, changes]);

  if (sc.isLoading || !cfg) return <Loading className="p-6" />;
  if (sc.error) return <ErrorBox error={sc.error} className="m-6" />;
  const cmp = r?.results?.comparison;
  const svcCmp = cmp?.service;

  return (
    <div className="absolute inset-0 grid grid-cols-1 overflow-y-auto lg:grid-cols-[360px_minmax(0,1fr)] xl:grid-cols-[400px_minmax(0,1fr)_440px] xl:grid-rows-[minmax(0,1fr)] xl:overflow-hidden">
      {/* ------------------------------------------------ editor */}
      <div className="space-y-4 border-b border-border p-3 lg:max-h-[70vh] lg:overflow-y-auto lg:border-r xl:max-h-none xl:min-h-0 xl:border-b-0">
        <Input value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} className="h-9 text-base font-medium" />
        <section className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Avaliação</h3>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Métrica de roteamento">
              <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={cfg.metric ?? "cost"} onChange={(e) => upd({ metric: e.target.value })}>
                <option value="cost">Custo (R$/t)</option><option value="time">Tempo (h)</option><option value="distance">Distância (km)</option>
              </select>
            </Field>
            <Field label="Rede">
              <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={cfg.mode ?? "road"} onChange={(e) => upd({ mode: e.target.value })}>
                <option value="road">Rodoviária</option><option value="multimodal">Multimodal</option>
              </select>
            </Field>
          </div>
          <Field label="Pares origem-destino">
            <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={(cfg.od_pairs?.length ? "custom" : cfg.od_benchmark) ?? "capitals"}
              onChange={(e) => upd(e.target.value === "custom" ? { od_benchmark: "none" } : { od_benchmark: e.target.value, od_pairs: [] })}>
              <option value="capitals">Todos os pares de capitais (351)</option>
              <option value="none">Nenhum / pares personalizados</option>
            </select>
          </Field>
          <OdEditor pairs={cfg.od_pairs ?? []} onChange={(p) => upd({ od_pairs: p })} />
        </section>

        <section className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Instalações de atendimento e demanda</h3>
          <FacilityAdder onAdd={(f) => { if (!services.find((s) => s.id === f.id)) { setServices([...services, f]); setDirty(true); } }} />
          {services.map((s) => (
            <div key={s.id} className="flex items-center gap-2 text-xs">
              <span className="flex-1 truncate">{s.name}</span>
              <button className="text-muted-foreground hover:text-red-300" onClick={() => { setServices(services.filter((x) => x.id !== s.id)); setDirty(true); }}><Trash2 className="size-3.5" /></button>
            </div>
          ))}
          <div className="grid grid-cols-2 gap-2">
            <Field label="Nível da demanda">
              <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={cfg.demand?.level ?? "immediate_region"} onChange={(e) => upd({ demand: { ...cfg.demand, level: e.target.value } })}>
                <option value="state">UF</option><option value="intermediate_region">Região intermediária</option>
                <option value="immediate_region">Região imediata</option><option value="municipality">Município</option>
              </select>
            </Field>
            <Field label="Recorte">
              <MultiCheck label={cfg.demand?.ufs?.length ? cfg.demand.ufs.join(", ") : "Brasil"} value={cfg.demand?.ufs ?? []}
                onChange={(v) => upd({ demand: { ...cfg.demand, ufs: v.length ? v : null } })} options={UFS.map((u) => ({ value: u, label: u }))} />
            </Field>
            <Field label="Raio de cobertura (km)"><Input type="number" value={cfg.coverage_km ?? ""} placeholder="premissa (300)" onChange={(e) => upd({ coverage_km: e.target.value ? Number(e.target.value) : null })} /></Field>
            <Field label="Capacidade padrão (t/ano)"><Input type="number" value={cfg.default_capacity_t ?? 2000000} onChange={(e) => upd({ default_capacity_t: Number(e.target.value) })} /></Field>
          </div>
          <label className="flex items-center gap-2 text-xs"><Switch checked={cfg.run_des ?? true} onCheckedChange={(v) => upd({ run_des: v })} /> Simulação de eventos discretos (SimPy) das instalações</label>
        </section>

        <section className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Alterações do cenário</h3>
          <div className="flex flex-wrap gap-1.5">
            <Button size="xs" variant={pick === "segment" ? "default" : "outline"} onClick={() => setPick(pick === "segment" ? null : "segment")} data-testid="pick-segment"><MousePointerClick /> Interditar trecho</Button>
            <Button size="xs" variant={pick === "bbox" ? "default" : "outline"} onClick={() => { setBboxStart(null); setPick(pick === "bbox" ? null : "bbox"); }}><MousePointerClick /> Interditar área</Button>
            <Button size="xs" variant={pick === "new_facility" ? "default" : "outline"} onClick={() => setPick(pick === "new_facility" ? null : "new_facility")} data-testid="pick-new-facility"><Plus /> Nova instalação</Button>
          </div>
          <ChangeAdder services={services} assumptions={assumptions.data ?? []} onAdd={addChange} />
          {changes.length === 0 && <p className="text-xs text-muted-foreground">Sem alterações: a execução comparará a base com ela mesma.</p>}
          {changes.map((c, i) => (
            <div key={i} className="rounded-lg border border-border p-2 text-xs" data-testid="change-item">
              <div className="flex items-center gap-2">
                <Badge variant="outline">{CHANGE_LABELS[c.change_type]}</Badge>
                <span className="truncate text-muted-foreground">{c.note}</span>
                <button className="ml-auto text-muted-foreground hover:text-red-300" onClick={() => { setChanges(changes.filter((_, j) => j !== i)); setDirty(true); }}><Trash2 className="size-3.5" /></button>
              </div>
              {c.change_type === "new_facility" ? (
                <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                  <Input className="h-7 text-xs" value={c.payload.name} onChange={(e) => { const cs = [...changes]; cs[i] = { ...c, payload: { ...c.payload, name: e.target.value } }; setChanges(cs); setDirty(true); }} />
                  <Input className="h-7 text-xs" type="number" value={c.payload.capacity_t} onChange={(e) => { const cs = [...changes]; cs[i] = { ...c, payload: { ...c.payload, capacity_t: Number(e.target.value) } }; setChanges(cs); setDirty(true); }} />
                </div>
              ) : (
                <code className="mt-1 block truncate text-[11px] text-muted-foreground">{JSON.stringify(c.payload)}</code>
              )}
            </div>
          ))}
        </section>

        <div className="sticky bottom-0 flex gap-2 bg-background/90 py-2 backdrop-blur">
          <Button variant="secondary" onClick={() => save.mutate()} disabled={!dirty || save.isPending}><Save /> Salvar</Button>
          <Button onClick={() => run.mutate()} disabled={run.isPending || job.data?.status === "running" || job.data?.status === "queued"} data-testid="run-scenario"><Play /> Executar</Button>
        </div>
        <ErrorBox error={save.error ?? run.error} />
        <JobProgress job={job.data} label="Executando base e cenário" />
      </div>

      {/* ------------------------------------------------ mapa */}
      <div className="relative order-first h-[50vh] min-h-[320px] lg:order-none lg:h-[70vh] xl:h-auto xl:min-h-0">
        <MapView vectors={{ roads: true, rail: cfg.mode === "multimodal", waterways: cfg.mode === "multimodal", states: true }}
          deckLayers={deckLayers} onMapClick={pick ? onMapClick : undefined} cursor={pick ? "crosshair" : undefined}
          getTooltip={(info: any) => info.layer?.id === "svc" ? `${info.object.name}: ${fmtPct(info.object.utilization)} da capacidade` : info.object?.properties?.label ? `${info.object.properties.label} (${info.layer.id === "base" ? "base" : "cenário"})` : null} />
        {pick && (
          <div className="absolute top-3 left-1/2 z-10 -translate-x-1/2 rounded-lg border border-border bg-card px-3 py-1.5 text-xs shadow">
            {pick === "segment" ? "Clique sobre a rodovia/ferrovia/hidrovia a interditar" : pick === "bbox" ? (bboxStart ? "Clique no canto oposto da área" : "Clique no primeiro canto da área") : "Clique onde ficará a nova instalação"}
          </div>
        )}
        <div className="absolute bottom-8 left-3 z-10 hidden sm:block space-y-0.5 rounded-lg border border-border bg-card/90 px-3 py-2 text-xs backdrop-blur">
          <div className="flex items-center gap-2"><span className="h-1 w-4 bg-slate-400" /> rota na base</div>
          <div className="flex items-center gap-2"><span className="h-1 w-4 bg-pink-400" /> rota no cenário</div>
          <div className="flex items-center gap-2"><span className="h-1.5 w-4 bg-red-500" /> trecho interditado</div>
          <div className="flex items-center gap-2"><span className="size-2.5 rounded-full bg-cyan-400" /> instalação (vermelha = capacidade esgotada)</div>
        </div>
      </div>

      {/* ------------------------------------------------ resultados */}
      <div className="border-t border-border p-3 lg:col-span-2 xl:col-span-1 xl:min-h-0 xl:overflow-y-auto xl:border-t-0 xl:border-l">
        {!r && <p className="text-sm text-muted-foreground">Execute o cenário para ver os resultados comparados com a base.</p>}
        {r?.status === "failed" && <ErrorBox error={r.error} />}
        {r?.status === "success" && (
          <div className="space-y-3" data-testid="scenario-results">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>Execução #{r.id} · {fmtDate(r.finished_at)} · rede v{r.network_version_id} · {fmt(r.duration_ms / 1000, 1)} s</span>
              {r.reproduced === true && <Badge className="border-emerald-500/40 bg-emerald-500/15 text-emerald-300"><CheckCircle2 className="size-3" /> reproduzida: resultado idêntico</Badge>}
              {r.reproduced === false && <Badge className="border-red-500/40 bg-red-500/15 text-red-300"><XCircle className="size-3" /> divergente da original</Badge>}
            </div>
            <div className="text-[11px] text-muted-foreground">hash entradas {r.input_hash.slice(0, 12)} · hash resultados {r.result_hash?.slice(0, 12)}</div>
            <Tabs defaultValue="summary">
              <TabsList className="h-auto w-full flex-wrap">
                <TabsTrigger value="summary">Resumo</TabsTrigger>
                <TabsTrigger value="routes">Rotas</TabsTrigger>
                <TabsTrigger value="service">Atendimento</TabsTrigger>
                <TabsTrigger value="inputs">Entradas</TabsTrigger>
              </TabsList>
              <TabsContent value="summary" className="mt-3 space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Pares OD afetados" value={`${cmp.od_pairs_affected} / ${r.summary.od_pairs}`} />
                  <Stat label="Pares desconectados" value={cmp.od_pairs_disconnected} tone={cmp.od_pairs_disconnected ? "up" : "neutral"} />
                  <Stat label="Δ soma de custos (R$/t)" value={fmtSigned(cmp.od_delta_sum_cost_brl, 2)} tone={cmp.od_delta_sum_cost_brl > 0 ? "up" : cmp.od_delta_sum_cost_brl < 0 ? "down" : "neutral"} />
                  <Stat label="Δ soma de distâncias" value={fmtSigned(cmp.od_delta_sum_km, 0, "km")} />
                  {svcCmp?.coverage_share && <Stat label="Cobertura (pop. no raio)" value={fmtPct(svcCmp.coverage_share.scenario)} sub={`base ${fmtPct(svcCmp.coverage_share.base)}`} tone={svcCmp.coverage_share.delta > 0 ? "down" : svcCmp.coverage_share.delta < 0 ? "up" : "neutral"} />}
                  {svcCmp?.service_level && <Stat label="Demanda atendida" value={fmtPct(svcCmp.service_level.scenario)} sub={`base ${fmtPct(svcCmp.service_level.base)}`} />}
                  {svcCmp?.transport_cost && <Stat label="Custo de transporte" value={fmtBRL(svcCmp.transport_cost.scenario)} sub={`base ${fmtBRL(svcCmp.transport_cost.base)}`} />}
                  {svcCmp?.unmet_t && <Stat label="Demanda não atendida" value={`${fmt(svcCmp.unmet_t.scenario, 0)} t`} sub={`base ${fmt(svcCmp.unmet_t.base, 0)} t`} />}
                </div>
                <div className="flex flex-wrap gap-1.5 text-xs">
                  {(["xlsx", "csv", "geojson"] as const).map((f) => (
                    <a key={f} href={downloadUrl(`/exports/scenario-runs/${r.id}.${f}`)} className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-accent"><Download className="size-3" /> {f.toUpperCase()}</a>
                  ))}
                  <a href={downloadUrl(`/reports/scenario-runs/${r.id}.pdf`)} className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-accent" data-testid="scenario-pdf"><FileText className="size-3" /> Relatório PDF</a>
                  <Button size="xs" variant="outline" onClick={() => rerun.mutate(r.id)} data-testid="rerun"><RotateCcw /> Reexecutar com as mesmas entradas</Button>
                </div>
                <Caveat>Custos e tempos derivam de premissas paramétricas registradas na aba “Entradas”. A demanda é proxy populacional.</Caveat>
                <RunHistory runs={sc.data?.runs ?? []} current={r.id} onPick={setRunId} />
              </TabsContent>
              <TabsContent value="routes" className="mt-3">
                <table className="w-full text-xs">
                  <thead className="text-left text-muted-foreground"><tr><th className="py-1">Par</th><th className="text-right">Δ km</th><th className="text-right">Δ h</th><th className="text-right">Δ R$/t</th></tr></thead>
                  <tbody>
                    {cmp.pairs.map((p: any, i: number) => (
                      <tr key={i} className="border-t border-border/60">
                        <td className="py-1">{p.origin} → {p.dest}{!p.scenario_connected && <span className="ml-1 text-red-300">desconectado</span>}</td>
                        <td className="text-right tabular">{fmtSigned(p.delta_km, 1)}</td>
                        <td className="text-right tabular">{fmtSigned(p.delta_time_h, 2)}</td>
                        <td className="text-right tabular">{fmtSigned(p.delta_cost_brl_t, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {cmp.pairs.length === 0 && <p className="text-xs text-muted-foreground">Nenhum par afetado.</p>}
              </TabsContent>
              <TabsContent value="service" className="mt-3 space-y-3">
                {r.results.scenario.service ? <ServiceView base={r.results.baseline.service} scen={r.results.scenario.service} /> : <p className="text-xs text-muted-foreground">Sem instalações de atendimento configuradas.</p>}
              </TabsContent>
              <TabsContent value="inputs" className="mt-3 space-y-2 text-xs">
                <div className="font-medium">Alterações aplicadas</div>
                {r.results.scenario.applied_changes.map((a: any, i: number) => (
                  <div key={i} className="rounded border border-border p-1.5"><b>{CHANGE_LABELS[a.type]}</b> {a.edges_closed !== undefined && `· ${a.edges_closed} arestas`} {a.snap_km !== undefined && `· ligada à rede a ${a.snap_km} km`}<code className="block truncate text-muted-foreground">{JSON.stringify(a.payload)}</code></div>
                ))}
                <div className="font-medium">Premissas usadas</div>
                {Object.entries(r.inputs.assumptions as Record<string, number>).map(([k, v]) => <KV key={k} k={k} v={v} />)}
              </TabsContent>
            </Tabs>
          </div>
        )}
      </div>
    </div>
  );
}

function ServiceView({ base, scen }: { base: any; scen: any }) {
  const names: string[] = scen.open_facilities.map((f: any) => f.name);
  const baseUtil = Object.fromEntries((base?.open_facilities ?? []).map((f: any) => [f.key, f.utilization]));
  return (
    <>
      <Chart height={Math.max(160, names.length * 26)} option={{
        legend: { top: 0 }, tooltip: { trigger: "axis", valueFormatter: (v: any) => `${(v * 100).toFixed(1)}%` },
        grid: { top: 28, left: 8, right: 16, bottom: 8, containLabel: true },
        xAxis: { type: "value", max: 1, axisLabel: { formatter: (v: number) => `${v * 100}%` } },
        yAxis: { type: "category", data: names, axisLabel: { width: 130, overflow: "truncate", fontSize: 10 } },
        series: [
          { name: "Base", type: "bar", data: scen.open_facilities.map((f: any) => baseUtil[f.key] ?? null), itemStyle: { color: "#64748b" } },
          { name: "Cenário", type: "bar", data: scen.open_facilities.map((f: any) => f.utilization), itemStyle: { color: "#22d3ee" } },
        ],
      }} />
      <div className="text-[11px] text-muted-foreground">Alocação: {scen.solver.solver} — {scen.solver.quality === "OPTIMAL" ? "ótimo comprovado (LP)" : scen.solver.quality}. Preço-sombra = redução de custo por t adicional de capacidade.</div>
      <table className="w-full text-xs">
        <thead className="text-left text-muted-foreground"><tr><th className="py-1">Instalação</th><th className="text-right">Carga t/ano</th><th className="text-right">Util.</th><th className="text-right">Preço-sombra</th></tr></thead>
        <tbody>
          {scen.open_facilities.map((f: any) => (
            <tr key={f.key} className="border-t border-border/60">
              <td className="py-1">{f.name} <span className="text-muted-foreground">({f.capacity_source})</span></td>
              <td className="text-right tabular">{fmt(f.load_t, 0)}</td>
              <td className={`text-right tabular ${f.binding ? "text-red-300" : ""}`}>{fmtPct(f.utilization)}</td>
              <td className="text-right tabular">{fmt(f.capacity_shadow_price, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {scen.operations && (
        <div className="space-y-1">
          <div className="text-xs font-medium">Operação diária (SimPy, {scen.operations.days} dias, semente {scen.operations.seed})</div>
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground"><tr><th className="py-1">Instalação</th><th className="text-right">Docas</th><th className="text-right">Uso docas</th><th className="text-right">Espera p95</th></tr></thead>
            <tbody>
              {scen.operations.facilities.map((o: any) => (
                <tr key={o.key} className="border-t border-border/60">
                  <td className="py-1">{o.name}{o.bottleneck && <span className="ml-1 text-red-300">gargalo</span>}</td>
                  <td className="text-right tabular">{o.docks}</td>
                  <td className="text-right tabular">{fmtPct(o.dock_utilization)}</td>
                  <td className="text-right tabular">{fmt(o.p95_wait_h, 1)} h</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[11px] text-muted-foreground">{scen.operations.assumptions.join(" · ")}</div>
        </div>
      )}
      {scen.underserved?.length > 0 && (
        <div>
          <div className="text-xs font-medium">Regiões com atendimento insuficiente</div>
          {scen.underserved.slice(0, 12).map((d: any) => (
            <KV key={d.key} k={d.name} v={d.unmet_t > 0 ? `${fmt(d.unmet_t, 0)} t não atendidas` : `${fmt(d.km, 0)} km até a instalação`} />
          ))}
        </div>
      )}
    </>
  );
}

function RunHistory({ runs, current, onPick }: { runs: any[]; current: number; onPick: (id: number) => void }) {
  if (runs.length <= 1) return null;
  return (
    <div>
      <div className="mb-1 text-xs font-medium">Histórico de execuções</div>
      {runs.map((x) => (
        <button key={x.id} onClick={() => onPick(x.id)} className={`flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-accent ${x.id === current ? "bg-accent" : ""}`}>
          #{x.id} · {fmtDate(x.finished_at)} {x.rerun_of && <span className="text-muted-foreground">(reexecução de #{x.rerun_of})</span>}
          <span className="ml-auto font-mono text-[10px] text-muted-foreground">{x.result_hash?.slice(0, 8)}</span>
        </button>
      ))}
    </div>
  );
}

function OdEditor({ pairs, onChange }: { pairs: any[]; onChange: (p: any[]) => void }) {
  const [o, setO] = useState<MunicipalityHit | null>(null);
  const [d, setD] = useState<MunicipalityHit | null>(null);
  return (
    <div className="space-y-1.5">
      {pairs.map((p, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <span className="flex-1 truncate">{p.origin.label} → {p.dest.label} ({fmt(p.volume_t, 0)} t)</span>
          <button className="text-muted-foreground hover:text-red-300" onClick={() => onChange(pairs.filter((_, j) => j !== i))}><Trash2 className="size-3.5" /></button>
        </div>
      ))}
      <div className="grid grid-cols-[1fr_1fr_auto] gap-1.5">
        <MunicipalityPicker value={o} onChange={setO} placeholder="Origem" />
        <MunicipalityPicker value={d} onChange={setD} placeholder="Destino" />
        <Button size="icon" variant="outline" disabled={!o || !d} title="Adicionar par"
          onClick={() => { onChange([...pairs, { origin: { type: "municipality", id: o!.code, label: `${o!.name}/${o!.uf}` }, dest: { type: "municipality", id: d!.code, label: `${d!.name}/${d!.uf}` }, volume_t: 1000 }]); setO(null); setD(null); }}>
          <Plus />
        </Button>
      </div>
    </div>
  );
}

function FacilityAdder({ onAdd }: { onAdd: (f: { id: number; name: string }) => void }) {
  const [q, setQ] = useState("");
  const res = useQuery({
    queryKey: ["fac-add", q],
    queryFn: () => api("/facilities", { query: { q, page_size: 8, sort: "capacity", order: "desc" }, schema: pageOf(FacilitySchema) }),
    enabled: q.length >= 2,
  });
  return (
    <div className="relative">
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Adicionar instalação de atendimento (buscar)…" className="h-8" data-testid="facility-adder" />
      {q.length >= 2 && res.data && (
        <div className="absolute top-9 right-0 left-0 z-30 max-h-56 overflow-auto rounded-lg border border-border bg-popover shadow-xl">
          {res.data.items.map((f) => (
            <button key={f.id} className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-accent" onClick={() => { onAdd({ id: f.id, name: f.name }); setQ(""); }}>
              <span className="truncate">{f.name}</span>
              <span className="ml-auto shrink-0 text-muted-foreground">{f.uf} {f.capacity_value ? `· ${fmt(f.capacity_value, 0)} t` : ""}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ChangeAdder({ services, assumptions, onAdd }: { services: { id: number; name: string }[]; assumptions: any[]; onAdd: (c: Change) => void }) {
  const [kind, setKind] = useState("cost");
  const [key, setKey] = useState("cost.road.brl_tkm");
  const [val, setVal] = useState("");
  const [fac, setFac] = useState<number | null>(null);
  const [uf, setUf] = useState("");
  const a = assumptions.find((x) => x.key === key);
  return (
    <div className="space-y-1.5 rounded-lg border border-dashed border-border p-2">
      <div className="flex gap-1.5">
        <select className="h-7 rounded-md border border-input bg-input/30 px-1.5 text-xs" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="cost">Custo / velocidade (premissa)</option>
          <option value="demand">Fator de demanda</option>
          <option value="capacity">Capacidade de instalação</option>
          <option value="remove_facility">Remover instalação</option>
          <option value="closure_facility">Interditar terminal</option>
        </select>
        <Button size="xs" variant="secondary" className="ml-auto" disabled={(kind !== "remove_facility" && kind !== "closure_facility" && !val)}
          onClick={() => {
            if (kind === "cost") onAdd({ change_type: "cost", payload: { overrides: { [key]: Number(val) } }, note: `${key}: ${a?.value} → ${val} ${a?.unit ?? ""}` });
            if (kind === "demand") onAdd({ change_type: "demand", payload: uf ? { uf_factors: { [uf]: Number(val) } } : { global_factor: Number(val) }, note: `demanda ×${val}${uf ? ` em ${uf}` : " (global)"}` });
            if (kind === "capacity" && fac) onAdd({ change_type: "capacity", payload: { facility_id: fac, capacity_t: Number(val) }, note: `capacidade de #${fac} = ${val} t/ano` });
            if (kind === "remove_facility" && fac) onAdd({ change_type: "remove_facility", payload: { facility_id: fac }, note: `remove #${fac}` });
            if (kind === "closure_facility" && fac) onAdd({ change_type: "closure", payload: { facility_id: fac }, note: `terminal #${fac} interditado` });
            setVal("");
          }}>
          <Plus /> Adicionar
        </Button>
      </div>
      {kind === "cost" && (
        <div className="grid grid-cols-[1fr_90px] gap-1.5">
          <select className="h-7 rounded-md border border-input bg-input/30 px-1.5 text-xs" value={key} onChange={(e) => setKey(e.target.value)}>
            {assumptions.filter((x) => /^(cost|speed|time)\./.test(x.key)).map((x) => <option key={x.key} value={x.key}>{x.description} ({x.value} {x.unit})</option>)}
          </select>
          <Input className="h-7 text-xs" type="number" step="any" value={val} onChange={(e) => setVal(e.target.value)} placeholder={String(a?.value ?? "")} />
        </div>
      )}
      {kind === "demand" && (
        <div className="grid grid-cols-2 gap-1.5">
          <select className="h-7 rounded-md border border-input bg-input/30 px-1.5 text-xs" value={uf} onChange={(e) => setUf(e.target.value)}>
            <option value="">Todas as UFs</option>
            {UFS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
          <Input className="h-7 text-xs" type="number" step="0.05" value={val} onChange={(e) => setVal(e.target.value)} placeholder="fator, ex.: 1.2" />
        </div>
      )}
      {(kind === "capacity" || kind === "remove_facility" || kind === "closure_facility") && (
        <div className="grid grid-cols-[1fr_110px] gap-1.5">
          <select className="h-7 rounded-md border border-input bg-input/30 px-1.5 text-xs" value={fac ?? ""} onChange={(e) => setFac(Number(e.target.value) || null)}>
            <option value="">Instalação…</option>
            {services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          {kind === "capacity" && <Input className="h-7 text-xs" type="number" value={val} onChange={(e) => setVal(e.target.value)} placeholder="t/ano" />}
        </div>
      )}
    </div>
  );
}

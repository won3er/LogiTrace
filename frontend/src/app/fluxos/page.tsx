"use client";

import { ArcLayer } from "@deck.gl/layers";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Plus } from "lucide-react";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Chart } from "@/components/chart";
import { Caveat, ErrorBox, Field, KV, Loading } from "@/components/common";
import { MultiCheck } from "@/components/multi-check";
import { MunicipalityPicker } from "@/components/municipality-picker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, downloadUrl } from "@/lib/api";
import { FLOW_CLASS_COLORS, UFS } from "@/lib/constants";
import { fmt, fmtCompact, fmtPct } from "@/lib/format";
import type { MunicipalityHit } from "@/lib/types";

const MapView = dynamic(() => import("@/components/map/map-view").then((m) => m.MapView), { ssr: false });
type Dataset = { dataset: string; flow_class: string; class_label: string; modal: string; unit: string; period: string; links: number; total: number; notes: string | null };
const DS_LABEL: Record<string, string> = {
  ibge_2024_rodoviario_ciot: "Rodoviário (CIOT)",
  ibge_2024_ferroviario: "Ferroviário",
  ibge_2024_aquaviario_cabotagem_interior: "Aquaviário — cabotagem e interior",
  ibge_2024_aquaviario_internacional: "Aquaviário — longo curso",
  ibge_2024_aereo_domestico: "Aéreo — doméstico",
  ibge_2024_aereo_internacional: "Aéreo — internacional",
  usuario_hipotetico: "Hipotéticos do usuário",
};

export default function FlowsPage() {
  const qc = useQueryClient();
  const ds = useQuery({ queryKey: ["flow-ds"], queryFn: () => api<Dataset[]>("/flows/datasets") });
  const [dataset, setDataset] = useState("ibge_2024_ferroviario");
  const [uf, setUf] = useState<string[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [limit, setLimit] = useState(800);
  const [level, setLevel] = useState<"uf" | "region">("region");
  const cur = ds.data?.find((d) => d.dataset === dataset);
  const products = useQuery({ queryKey: ["flow-prod", dataset], queryFn: () => api<{ product_group: string; total: number }[]>("/flows/products", { query: { dataset } }), enabled: dataset.includes("aquaviario_cabotagem") });
  const q = { dataset, uf, product_group: groups, limit };
  const flows = useQuery({ queryKey: ["flows", q], queryFn: () => api<Record<string, any>>("/flows", { query: q }) });
  const matrix = useQuery({ queryKey: ["matrix", dataset, level, groups], queryFn: () => api<Record<string, any>>("/flows/matrix", { query: { dataset, level, product_group: groups } }), enabled: !dataset.includes("internacional") });
  const conc = useQuery({ queryKey: ["conc", dataset], queryFn: () => api<Record<string, any>>("/flows/concentration", { query: { dataset, top: 15 } }) });

  const layers = useMemo(() => {
    if (!flows.data) return [];
    const max = flows.data.items[0]?.value ?? 1;
    return [new ArcLayer({
      id: "arcs", data: flows.data.items, pickable: true, greatCircle: dataset.includes("internacional"),
      getSourcePosition: (d: any) => [d.olon, d.olat], getTargetPosition: (d: any) => [d.dlon, d.dlat],
      getWidth: (d: any) => 0.6 + 9 * Math.sqrt(d.value / max),
      getSourceColor: (d: any) => [...(FLOW_CLASS_COLORS[d.flow_class] ?? [148, 163, 184]), 200] as any,
      getTargetColor: (d: any) => (d.flow_class === "observed" ? [250, 204, 21, 200] : [...(FLOW_CLASS_COLORS[d.flow_class] ?? [148, 163, 184]), 200]) as any,
    })];
  }, [flows.data, dataset]);

  return (
    <div className="absolute inset-0 grid grid-cols-1 overflow-y-auto md:grid-cols-[340px_minmax(0,1fr)] md:grid-rows-[minmax(0,1fr)] md:overflow-hidden lg:grid-cols-[420px_minmax(0,1fr)]">
      <div className="space-y-3 p-3 border-b border-border md:min-h-0 md:overflow-y-auto md:border-b-0 md:border-r">
        <Field label="Conjunto de dados">
          <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={dataset} onChange={(e) => { setDataset(e.target.value); setGroups([]); }} data-testid="flow-dataset">
            {ds.data?.map((d) => <option key={d.dataset} value={d.dataset}>{DS_LABEL[d.dataset] ?? d.dataset} · {d.class_label}</option>)}
          </select>
        </Field>
        {cur && (
          <div className="rounded-lg border border-border p-2 text-xs">
            <KV k="Classe" v={<span style={{ color: `rgb(${FLOW_CLASS_COLORS[cur.flow_class].join(",")})` }}>{cur.class_label}</span>} />
            <KV k="Unidade" v={cur.unit} />
            <KV k="Período" v={cur.period} />
            <KV k="Ligações" v={fmt(cur.links, 0)} />
            <KV k="Total" v={`${fmtCompact(cur.total)} ${cur.unit}`} />
            {cur.notes && <div className="mt-1 text-muted-foreground">{cur.notes}</div>}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <MultiCheck label="UF (origem ou destino)" value={uf} onChange={setUf} options={UFS.map((u) => ({ value: u, label: u }))} />
          {products.data && <MultiCheck label="Mercadoria" value={groups} onChange={setGroups} options={products.data.slice(0, 60).map((p) => ({ value: p.product_group, label: p.product_group.slice(0, 60), count: Math.round(p.total / 1000) }))} />}
        </div>
        <Field label="Maiores ligações exibidas"><Input type="number" min={50} max={20000} value={limit} onChange={(e) => setLimit(Number(e.target.value) || 800)} /></Field>
        {flows.isLoading && <Loading />}
        <ErrorBox error={flows.error} />
        {flows.data && (
          <>
            <p className="text-xs text-muted-foreground">{flows.data.shown_links} de {fmt(flows.data.total_links, 0)} ligações ({fmtPct(flows.data.shown_share)} do total em {flows.data.unit}).</p>
            <Caveat>{flows.data.caveat} Classes nunca são misturadas: observados (fonte real), modelados (cenários), hipotéticos (usuário) e sintéticos (demonstração) têm cores e conjuntos separados.</Caveat>
            <div className="flex gap-1.5 text-xs">
              {(["csv", "xlsx", "geojson"] as const).map((f) => <a key={f} href={downloadUrl(`/exports/flows.${f}`, q)} className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-accent"><Download className="size-3" /> {f.toUpperCase()}</a>)}
            </div>
          </>
        )}
        <Tabs defaultValue="matrix">
          <TabsList className="h-auto w-full flex-wrap">
            <TabsTrigger value="matrix">Matriz OD</TabsTrigger>
            <TabsTrigger value="conc">Concentração</TabsTrigger>
            <TabsTrigger value="hyp">Hipotético</TabsTrigger>
          </TabsList>
          <TabsContent value="matrix" className="mt-2 space-y-2">
            <select className="h-7 rounded-md border border-input bg-input/30 px-1.5 text-xs" value={level} onChange={(e) => setLevel(e.target.value as any)}>
              <option value="region">Grandes regiões</option><option value="uf">UFs</option>
            </select>
            {matrix.data && (
              <>
                <Chart height={level === "uf" ? 420 : 260} option={{
                  tooltip: { formatter: (p: any) => `${matrix.data!.labels[p.data[1]]} ↔ ${matrix.data!.labels[p.data[0]]}: ${fmtCompact(p.data[2])} ${matrix.data!.unit}` },
                  grid: { top: 8, left: 8, right: 8, bottom: 40, containLabel: true },
                  xAxis: { type: "category", data: matrix.data.labels, axisLabel: { fontSize: 9 } },
                  yAxis: { type: "category", data: matrix.data.labels, axisLabel: { fontSize: 9 } },
                  visualMap: { min: 0, max: Math.max(...matrix.data.matrix.flat()), calculable: false, orient: "horizontal", left: "center", bottom: 0, itemHeight: 120,
                    inRange: { color: ["#0c1a2b", "#0e7490", "#22d3ee", "#fde68a"] }, textStyle: { color: "#94a3b8", fontSize: 9 }, formatter: (v: any) => fmtCompact(v) },
                  series: [{ type: "heatmap", data: matrix.data.matrix.flatMap((row: number[], i: number) => row.map((v, j) => [j, i, v])) }],
                }} />
                <KV k="Fluxo intrarregional" v={fmtPct(matrix.data.intra_share)} />
                <KV k="HHI dos pares" v={fmt(matrix.data.hhi_pairs, 0)} />
                <p className="text-[11px] text-muted-foreground">{matrix.data.note}</p>
              </>
            )}
            {dataset.includes("internacional") && <p className="text-xs text-muted-foreground">Matriz por UF indisponível para fluxos internacionais.</p>}
          </TabsContent>
          <TabsContent value="conc" className="mt-2 space-y-2">
            {conc.data && (
              <>
                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded border border-border p-1.5"><div className="text-muted-foreground">HHI</div><b className="tabular">{fmt(conc.data.hhi, 0)}</b></div>
                  <div className="rounded border border-border p-1.5"><div className="text-muted-foreground">Top 5</div><b className="tabular">{fmtPct(conc.data.top5_share)}</b></div>
                  <div className="rounded border border-border p-1.5"><div className="text-muted-foreground">Top 10</div><b className="tabular">{fmtPct(conc.data.top10_share)}</b></div>
                </div>
                {conc.data.top.map((t: any) => <KV key={t.key} k={t.name} v={`${fmtCompact(t.value)} · ${fmtPct(t.share)}`} />)}
                <p className="text-[11px] text-muted-foreground">{conc.data.definition}</p>
              </>
            )}
          </TabsContent>
          <TabsContent value="hyp" className="mt-2">
            <HypotheticalForm onDone={() => { qc.invalidateQueries({ queryKey: ["flow-ds"] }); setDataset("usuario_hipotetico"); }} />
          </TabsContent>
        </Tabs>
      </div>
      <div className="relative order-first h-[50vh] min-h-[320px] md:order-none md:h-auto md:min-h-0">
        <MapView vectors={{ roads: false, rail: dataset.includes("ferro"), waterways: dataset.includes("aqua"), states: true }} deckLayers={layers}
          getTooltip={(info: any) => info.object ? `${info.object.origin_name} ↔ ${info.object.dest_name}\n${fmt(info.object.value, 0)} ${info.object.unit} · ${info.object.class_label}` : null} />
        <div className="absolute bottom-8 left-3 z-10 hidden sm:block space-y-0.5 rounded-lg border border-border bg-card/90 px-3 py-2 text-xs backdrop-blur">
          {Object.entries({ observed: "Observado (fonte real)", modeled: "Modelado", hypothetical: "Hipotético (usuário)", synthetic: "Sintético" }).map(([k, l]) => (
            <div key={k} className="flex items-center gap-2"><span className="h-1 w-4" style={{ background: `rgb(${FLOW_CLASS_COLORS[k].join(",")})` }} />{l}</div>
          ))}
          <div className="text-muted-foreground">Espessura ∝ √volume</div>
        </div>
      </div>
    </div>
  );
}

function HypotheticalForm({ onDone }: { onDone: () => void }) {
  const [o, setO] = useState<MunicipalityHit | null>(null);
  const [d, setD] = useState<MunicipalityHit | null>(null);
  const [value, setValue] = useState(10000);
  const m = useMutation({
    mutationFn: () => api("/flows/hypothetical", { body: { origin_code: String(o!.code), dest_code: String(d!.code), value, unit: "t/ano" } }),
    onSuccess: () => { toast.success("Fluxo hipotético registrado (classe separada dos observados)"); onDone(); },
  });
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">Fluxos hipotéticos ficam na classe “hipotético”, nunca misturados aos observados.</p>
      <MunicipalityPicker value={o} onChange={setO} placeholder="Origem" />
      <MunicipalityPicker value={d} onChange={setD} placeholder="Destino" />
      <Field label="Volume (t/ano)"><Input type="number" value={value} onChange={(e) => setValue(Number(e.target.value))} /></Field>
      <Button size="sm" disabled={!o || !d || m.isPending} onClick={() => m.mutate()}><Plus /> Registrar</Button>
      <ErrorBox error={m.error} />
    </div>
  );
}

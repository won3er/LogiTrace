"use client";

import { ScatterplotLayer } from "@deck.gl/layers";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Download, MapPinned, Plus, Upload } from "lucide-react";
import dynamic from "next/dynamic";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ErrorBox, Field, Loading, MAP_ASIDE } from "@/components/common";
import { EntityDetails } from "@/components/entity-details";
import { MultiCheck } from "@/components/multi-check";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api, downloadUrl, uploadFile } from "@/lib/api";
import { CATEGORY_COLORS, CATEGORY_LABELS, hexToRgb, MODAL_LABELS, UFS } from "@/lib/constants";
import { fmt } from "@/lib/format";
import type { Selection } from "@/lib/store";
import { FacilitySchema, pageOf, type Facility } from "@/lib/types";

const MapView = dynamic(() => import("@/components/map/map-view").then((m) => m.MapView), { ssr: false });
type Facets = Record<"category" | "modal" | "uf" | "record_class", { value: string; count: number; label: string }[]>;

export default function ExplorerPage() {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string[]>([]);
  const [modal, setModal] = useState<string[]>([]);
  const [uf, setUf] = useState<string[]>([]);
  const [rclass, setRclass] = useState<string[]>([]);
  const [hasCap, setHasCap] = useState(false);
  const [bbox, setBbox] = useState<string | null>(null);
  const [sort, setSort] = useState<{ col: string; order: "asc" | "desc" }>({ col: "name", order: "asc" });
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState<Selection>(null);
  const [fly, setFly] = useState<{ lon: number; lat: number; zoom?: number; t: number } | null>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);

  const filters = { q: q || undefined, category, modal, uf, record_class: rclass, has_capacity: hasCap || undefined, bbox: bbox ?? undefined };
  const facets = useQuery({ queryKey: ["facets-all"], queryFn: () => api<Facets>("/facilities/facets") });
  const list = useQuery({
    queryKey: ["fac-list", filters, sort, page],
    queryFn: () => api("/facilities", { query: { ...filters, sort: sort.col, order: sort.order, page, page_size: 50 }, schema: pageOf(FacilitySchema) }),
    placeholderData: keepPreviousData,
  });
  const geo = useQuery({
    queryKey: ["fac-geo-ex", filters],
    queryFn: () => api<GeoJSON.FeatureCollection>("/facilities/geojson", { query: filters }),
    placeholderData: keepPreviousData,
  });

  const highlight = useMemo(
    () => [
      new ScatterplotLayer<Facility>({
        id: "page-items", data: list.data?.items ?? [], getPosition: (d) => [d.lon, d.lat], getRadius: 7, radiusUnits: "pixels",
        stroked: true, getLineColor: [255, 255, 255, 220], lineWidthMinPixels: 1.5,
        getFillColor: (d) => [...hexToRgb(CATEGORY_COLORS[d.category] ?? "#e2e8f0"), sel?.kind === "facility" && sel.id === d.id ? 255 : 120] as [number, number, number, number],
        updateTriggers: { getFillColor: [sel] },
      }),
    ],
    [list.data, sel],
  );

  const setFilter = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setPage(1);
  };
  const th = (col: string, label: string, cls = "") => (
    <th className={`cursor-pointer px-2 py-1.5 font-medium select-none hover:text-foreground ${cls}`}
      onClick={() => setSort((s) => ({ col, order: s.col === col && s.order === "asc" ? "desc" : "asc" }))}>
      <span className="inline-flex items-center gap-1">
        {label}
        {sort.col === col && (sort.order === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
      </span>
    </th>
  );
  const exportQ = { ...filters };
  const totalPages = Math.max(1, Math.ceil((list.data?.total ?? 0) / 50));

  return (
    <div className="absolute inset-0 grid grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(520px,46%)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)] lg:overflow-hidden">
      <div className="flex flex-col border-b border-border lg:min-h-0 lg:border-b-0 lg:border-r">
        <div className="space-y-2 border-b border-border p-3">
          <div className="flex gap-2">
            <Input value={q} onChange={(e) => setFilter(setQ)(e.target.value)} placeholder="Nome, município, operador ou UF" className="h-8" data-testid="explorer-q" />
            <NewFacilityDialog />
            <ImportDialog />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <MultiCheck label="Categoria" testId="filter-category" value={category} onChange={setFilter(setCategory)}
              options={(facets.data?.category ?? []).map((c) => ({ value: c.value, label: CATEGORY_LABELS[c.value] ?? c.label, count: c.count, color: CATEGORY_COLORS[c.value] }))} />
            <MultiCheck label="Modalidade" value={modal} onChange={setFilter(setModal)}
              options={(facets.data?.modal ?? []).map((c) => ({ value: c.value, label: MODAL_LABELS[c.value] ?? c.value, count: c.count }))} />
            <MultiCheck label="UF" value={uf} onChange={setFilter(setUf)} options={UFS.map((u) => ({ value: u, label: u, count: facets.data?.uf.find((x) => x.value === u)?.count }))} />
            <MultiCheck label="Origem do registro" value={rclass} onChange={setFilter(setRclass)}
              options={[{ value: "official", label: "Oficial (importado)" }, { value: "user", label: "Usuário (editável)" }, { value: "synthetic", label: "Sintético" }]} />
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Switch checked={hasCap} onCheckedChange={setFilter(setHasCap)} /> com capacidade
            </label>
            <Button size="sm" variant={bbox ? "default" : "outline"} onClick={() => {
              const b = mapRef.current?.getBounds();
              if (bbox || !b) setBbox(null);
              else setBbox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((x) => x.toFixed(4)).join(","));
              setPage(1);
            }} data-testid="filter-bbox">
              <MapPinned /> {bbox ? "Remover filtro de área" : "Filtrar pela área visível"}
            </Button>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span data-testid="explorer-total">{fmt(list.data?.total ?? 0, 0)} registros</span>
            <span className="ml-auto">Exportar:</span>
            {(["csv", "xlsx", "geojson"] as const).map((f) => (
              <a key={f} href={downloadUrl(`/exports/facilities.${f}`, exportQ)} className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 hover:bg-accent">
                <Download className="size-3" /> {f.toUpperCase()}
              </a>
            ))}
          </div>
        </div>
        <div className="max-h-[60vh] min-h-0 flex-1 overflow-auto lg:max-h-none">
          <ErrorBox error={list.error} className="m-3" />
          {list.isLoading ? <Loading className="px-3" /> : (
            <table className="w-full min-w-[640px] text-sm" data-testid="explorer-table">
              <thead className="sticky top-0 z-10 bg-card text-left text-xs text-muted-foreground">
                <tr>
                  {th("name", "Nome")}
                  {th("category", "Categoria")}
                  {th("uf", "UF / município")}
                  {th("capacity", "Capacidade", "text-right")}
                  <th className="px-2 py-1.5 font-medium">Fonte</th>
                </tr>
              </thead>
              <tbody>
                {list.data?.items.map((f) => (
                  <tr key={f.id}
                    className={`cursor-pointer border-t border-border/60 hover:bg-accent/50 ${sel?.kind === "facility" && sel.id === f.id ? "bg-primary/10" : ""}`}
                    onClick={() => { setSel({ kind: "facility", id: f.id }); setFly({ lon: f.lon, lat: f.lat, zoom: 10, t: Date.now() }); }}>
                    <td className="max-w-64 truncate px-2 py-1.5" title={f.name}>
                      {f.name} {f.record_class === "user" && <Badge variant="outline" className="ml-1">usuário</Badge>}
                    </td>
                    <td className="px-2 py-1.5 whitespace-nowrap">
                      <span className="mr-1.5 inline-block size-2 rounded-full" style={{ background: CATEGORY_COLORS[f.category] }} />
                      {f.category_label}
                    </td>
                    <td className="max-w-48 truncate px-2 py-1.5 text-muted-foreground">{f.uf ?? "—"} · {f.municipality_name ?? "—"}</td>
                    <td className="px-2 py-1.5 text-right tabular whitespace-nowrap">{f.capacity_value !== null ? `${fmt(f.capacity_value, 0)} ${f.capacity_unit ?? ""}` : <span className="text-muted-foreground">n/d</span>}</td>
                    <td className="px-2 py-1.5 text-xs whitespace-nowrap text-muted-foreground">{f.source_key?.replace("ibge_", "IBGE ") ?? "—"} {f.source_reference}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2 text-xs">
          <Button size="xs" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Anterior</Button>
          <span className="tabular">Página {page} de {totalPages}</span>
          <Button size="xs" variant="outline" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Próxima</Button>
          <span className="ml-auto text-muted-foreground">“n/d”: atributo não disponível na fonte (não estimado).</span>
        </div>
      </div>
      <div className="relative order-first h-[45vh] min-h-[300px] lg:order-none lg:h-auto lg:min-h-0">
        <MapView facilities={{ visible: true, data: geo.data }} deckLayers={highlight} flyTo={fly}
          onSelect={(s) => s?.kind === "facility" && setSel(s)} onLoad={(m) => (mapRef.current = m)} />
        {sel && (
          <aside className={MAP_ASIDE}>
            <EntityDetails selection={sel} onClose={() => setSel(null)} />
          </aside>
        )}
      </div>
    </div>
  );
}

function NewFacilityDialog() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", category: "centro_distribuicao", lon: "", lat: "", capacity_value: "", capacity_unit: "t/ano", operator: "" });
  const m = useMutation({
    mutationFn: () => api<{ id: number; note: string }>("/facilities", {
      body: { name: form.name, category: form.category, lon: Number(form.lon), lat: Number(form.lat),
        capacity_value: form.capacity_value ? Number(form.capacity_value) : null, capacity_unit: form.capacity_value ? form.capacity_unit : null,
        operator: form.operator || null },
    }),
    onSuccess: (r) => { toast.success(`Instalação #${r.id} cadastrada`, { description: r.note }); qc.invalidateQueries(); setOpen(false); },
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="secondary" />}><Plus /> Cadastrar</DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Nova instalação do usuário</DialogTitle></DialogHeader>
        <p className="text-xs text-muted-foreground">Registros do usuário são editáveis e ficam separados dos dados oficiais (classe “usuário”, confiabilidade baixa).</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Nome"><Input value={form.name} onChange={set("name")} /></Field>
          <Field label="Categoria">
            <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={form.category} onChange={set("category")}>
              <option value="centro_distribuicao">Centro de distribuição</option>
              <option value="armazem">Armazém</option>
              <option value="instalacao_usuario">Outra instalação</option>
            </select>
          </Field>
          <Field label="Longitude"><Input value={form.lon} onChange={set("lon")} placeholder="-46.63" /></Field>
          <Field label="Latitude"><Input value={form.lat} onChange={set("lat")} placeholder="-23.55" /></Field>
          <Field label="Capacidade (opcional)"><Input value={form.capacity_value} onChange={set("capacity_value")} /></Field>
          <Field label="Unidade"><Input value={form.capacity_unit} onChange={set("capacity_unit")} /></Field>
          <Field label="Operador (opcional)"><Input value={form.operator} onChange={set("operator")} /></Field>
        </div>
        <ErrorBox error={m.error} />
        <Button onClick={() => m.mutate()} disabled={!form.name || !form.lon || !form.lat || m.isPending}>Salvar</Button>
      </DialogContent>
    </Dialog>
  );
}

function ImportDialog() {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [res, setRes] = useState<Record<string, any> | null>(null);
  const run = useMutation({
    mutationFn: (dry: boolean) => uploadFile<Record<string, any>>("/facilities/import", file!, { dry_run: dry }),
    onSuccess: (r) => { setRes(r); if (!r.dry_run) { qc.invalidateQueries(); toast.success(`${r.created} instalações importadas`); } },
  });
  return (
    <Dialog>
      <DialogTrigger render={<Button size="sm" variant="outline" />}><Upload /> Importar</DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Importar instalações (CSV ou GeoJSON)</DialogTitle></DialogHeader>
        <p className="text-xs text-muted-foreground">CSV com colunas <code>name, lon, lat</code> (opcionais: category, modal, operator, capacity_value, capacity_unit, status, address) ou GeoJSON de pontos. Validação: coordenadas no território, campos obrigatórios e duplicidades.</p>
        <input type="file" accept=".csv,.geojson,.json" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setRes(null); }} className="text-sm" />
        <div className="flex gap-2">
          <Button variant="secondary" disabled={!file || run.isPending} onClick={() => run.mutate(true)}>Validar</Button>
          <Button disabled={!file || run.isPending} onClick={() => run.mutate(false)}>Importar</Button>
        </div>
        <ErrorBox error={run.error} />
        {res && (
          <div className="space-y-1 rounded-lg border border-border p-2 text-xs">
            <div>Linhas: {res.rows} · válidas: {res.valid} · criadas: {res.created} · rejeitadas: {res.rejected_total} · duplicadas: {res.duplicates}</div>
            {res.rejected?.slice(0, 8).map((r: any) => <div key={r.ref} className="text-red-300">linha {r.ref}: {r.reason}</div>)}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

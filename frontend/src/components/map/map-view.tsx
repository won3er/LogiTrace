"use client";

import type { Layer, PickingInfo } from "@deck.gl/core";
import { MapboxOverlay } from "@deck.gl/mapbox";
import * as maplibregl from "maplibre-gl";
import type { ExpressionSpecification, GeoJSONSource, MapMouseEvent, StyleSpecification } from "maplibre-gl";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { BASEMAP_STYLE, BRAZIL_VIEW, CATEGORY_COLORS } from "@/lib/constants";
import { useMapStore, type Selection } from "@/lib/store";
import { cn } from "@/lib/utils";

export type VectorToggles = Partial<
  Record<"roads" | "rail" | "waterways" | "corridors" | "states" | "municipalities" | "network", boolean>
>;

export type Choropleth = {
  source: "states" | "municipalities";
  colors: Record<number, string>;
  opacity?: number;
};

type Props = {
  vectors?: VectorToggles;
  facilities?: { visible: boolean; data?: GeoJSON.FeatureCollection | null };
  choropleth?: Choropleth | null;
  deckLayers?: Layer[];
  onSelect?: (s: Selection, lngLat: [number, number]) => void;
  onMapClick?: (lngLat: [number, number]) => void;
  onDeckClick?: (info: PickingInfo) => void;
  getTooltip?: (info: PickingInfo) => string | null;
  flyTo?: { lon: number; lat: number; zoom?: number; t: number } | null;
  fitBounds?: [number, number, number, number] | null;
  cursor?: string;
  className?: string;
  children?: ReactNode;
  onLoad?: (map: maplibregl.Map) => void;
};

const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#0b1020" } }],
};

const SURFACE_COLOR: ExpressionSpecification = [
  "match",
  ["get", "surface"],
  "Duplicada", "#fbbf24",
  "Pavimentada", "#f59e0b",
  "Em obras de duplicação", "#f59e0b",
  "Implantada", "#a16207",
  "Leito Natural", "#78716c",
  "Planejada", "#57534e",
  "#d97706",
];

const CATEGORY_MATCH: ExpressionSpecification = [
  "match",
  ["get", "category"],
  ...Object.entries(CATEGORY_COLORS).flat(),
  "#e2e8f0",
] as unknown as ExpressionSpecification;

function tileUrl(layer: string) {
  return `${window.location.origin}/api/tiles/${layer}/{z}/{x}/{y}.pbf`;
}

function firstSymbolLayer(map: maplibregl.Map): string | undefined {
  return map.getStyle().layers?.find((l) => l.type === "symbol")?.id;
}

function addOwnLayers(map: maplibregl.Map) {
  if (map.getSource("lt-segments")) return;
  const before = firstSymbolLayer(map);
  map.addSource("lt-states", { type: "vector", tiles: [tileUrl("states")], minzoom: 0, maxzoom: 10, promoteId: "code" });
  map.addSource("lt-municipalities", { type: "vector", tiles: [tileUrl("municipalities")], minzoom: 4, maxzoom: 12, promoteId: "code" });
  map.addSource("lt-segments", { type: "vector", tiles: [tileUrl("segments")], minzoom: 2, maxzoom: 14, promoteId: "id" });
  map.addSource("lt-corridors", { type: "vector", tiles: [tileUrl("corridors")], minzoom: 2, maxzoom: 14 });
  map.addSource("lt-network", { type: "vector", tiles: [tileUrl("network")], minzoom: 4, maxzoom: 14 });
  map.addSource("lt-facilities", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
    cluster: true,
    clusterRadius: 42,
    clusterMaxZoom: 8,
  });

  const fillColor: ExpressionSpecification = ["to-color", ["coalesce", ["feature-state", "color"], "rgba(0,0,0,0)"]];
  map.addLayer({ id: "lt-mun-choro", type: "fill", source: "lt-municipalities", "source-layer": "municipalities",
    paint: { "fill-color": fillColor, "fill-opacity": 0.75 }, layout: { visibility: "none" } }, before);
  map.addLayer({ id: "lt-mun-pop", type: "fill", source: "lt-municipalities", "source-layer": "municipalities",
    paint: {
      "fill-color": ["interpolate", ["linear"], ["ln", ["max", 1, ["coalesce", ["get", "population"], 1]]],
        7, "#0b1d33", 9.5, "#164e63", 11.5, "#0e7490", 13.5, "#22d3ee", 16.3, "#ecfeff"],
      "fill-opacity": 0.55 }, layout: { visibility: "none" } }, before);
  map.addLayer({ id: "lt-mun-line", type: "line", source: "lt-municipalities", "source-layer": "municipalities",
    paint: { "line-color": "#334155", "line-width": 0.3 }, layout: { visibility: "none" } }, before);
  map.addLayer({ id: "lt-states-choro", type: "fill", source: "lt-states", "source-layer": "states",
    paint: { "fill-color": fillColor, "fill-opacity": 0.7 }, layout: { visibility: "none" } }, before);
  map.addLayer({ id: "lt-states-line", type: "line", source: "lt-states", "source-layer": "states",
    paint: { "line-color": "#64748b", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.6, 8, 1.4] } }, before);

  map.addLayer({ id: "lt-water", type: "line", source: "lt-segments", "source-layer": "segments", filter: ["==", ["get", "modal"], "waterway"],
    paint: { "line-color": "#38bdf8", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.6, 10, 2], "line-opacity": 0.75 } }, before);
  map.addLayer({ id: "lt-roads", type: "line", source: "lt-segments", "source-layer": "segments", filter: ["==", ["get", "modal"], "road"],
    paint: {
      "line-color": SURFACE_COLOR,
      "line-width": ["interpolate", ["linear"], ["zoom"], 3, ["case", ["==", ["get", "jurisdiction"], "federal"], 0.9, 0.4], 10,
        ["case", ["==", ["get", "surface"], "Duplicada"], 3.2, 1.8]],
      "line-opacity": 0.85 },
    layout: { "line-cap": "round", "line-join": "round" } }, before);
  map.addLayer({ id: "lt-rail", type: "line", source: "lt-segments", "source-layer": "segments", filter: ["==", ["get", "modal"], "rail"],
    paint: { "line-color": "#c4b5fd", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1, 10, 2.6], "line-dasharray": [2, 1.2] } }, before);
  map.addLayer({ id: "lt-corridors", type: "line", source: "lt-corridors", "source-layer": "corridors",
    paint: { "line-color": "#f43f5e", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.5, 10, 4], "line-opacity": 0.55, "line-blur": 1 },
    layout: { visibility: "none" } }, before);
  map.addLayer({ id: "lt-network", type: "line", source: "lt-network", "source-layer": "network",
    paint: {
      "line-color": ["match", ["get", "modal"], "road", "#fde68a", "rail", "#c4b5fd", "waterway", "#7dd3fc", "transfer", "#34d399", "#94a3b8"],
      "line-width": 1.2, "line-opacity": 0.9 }, layout: { visibility: "none" } }, before);
  map.addLayer({ id: "lt-seg-highlight", type: "line", source: "lt-segments", "source-layer": "segments",
    paint: { "line-color": "#ffffff", "line-width": 5, "line-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.9, 0] } }, before);

  map.addLayer({ id: "lt-fac-cluster", type: "circle", source: "lt-facilities", filter: ["has", "point_count"],
    paint: {
      "circle-color": "rgba(34,211,238,0.22)", "circle-stroke-color": "#22d3ee", "circle-stroke-width": 1.2,
      "circle-radius": ["step", ["get", "point_count"], 13, 20, 17, 80, 22, 250, 28] } });
  map.addLayer({ id: "lt-fac-cluster-count", type: "symbol", source: "lt-facilities", filter: ["has", "point_count"],
    layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 11, "text-font": ["Noto Sans Regular"] },
    paint: { "text-color": "#e0f2fe" } });
  map.addLayer({ id: "lt-fac", type: "circle", source: "lt-facilities", filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-color": CATEGORY_MATCH,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 3.2, 10, 7],
      "circle-stroke-color": ["case", ["==", ["get", "record_class"], "user"], "#facc15", "#0b1020"],
      "circle-stroke-width": ["case", ["==", ["get", "record_class"], "user"], 2, 1] } });
}

const VECTOR_LAYERS: Record<keyof VectorToggles, string[]> = {
  roads: ["lt-roads"],
  rail: ["lt-rail"],
  waterways: ["lt-water"],
  corridors: ["lt-corridors"],
  states: ["lt-states-line"],
  municipalities: ["lt-mun-pop", "lt-mun-line"],
  network: ["lt-network"],
};

export function MapView({
  vectors = {}, facilities, choropleth, deckLayers = [], onSelect, onMapClick, onDeckClick, getTooltip,
  flyTo, fitBounds, cursor, className, children, onLoad,
}: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const [ready, setReady] = useState(false);
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const handlers = useRef({ onSelect, onMapClick, onDeckClick, getTooltip });
  handlers.current = { onSelect, onMapClick, onDeckClick, getTooltip };
  const selectedSeg = useRef<number | null>(null);

  useEffect(() => {
    if (!el.current) return;
    maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");
    const map = new maplibregl.Map({
      container: el.current,
      style: BASEMAP_STYLE,
      center: [BRAZIL_VIEW.longitude, BRAZIL_VIEW.latitude],
      zoom: BRAZIL_VIEW.zoom,
      minZoom: 2.5,
      maxZoom: 15,
      attributionControl: { compact: true, customAttribution: "Dados: IBGE · Processamento: LogiTrace" },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric", maxWidth: 120 }), "bottom-right");
    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    overlayRef.current = overlay;
    map.addControl(overlay as unknown as maplibregl.IControl);

    let styled = false;
    const fallback = setTimeout(() => {
      if (!styled) map.setStyle(FALLBACK_STYLE); // mapa base indisponível: segue com as camadas próprias
    }, 9000);
    map.on("style.load", () => {
      styled = true;
      clearTimeout(fallback);
      addOwnLayers(map);
      // em telas pequenas a atribuição começa recolhida (ícone "i") para não cobrir legendas
      if (window.matchMedia("(max-width: 639px)").matches)
        map.getContainer().querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
      setReady(true);
      onLoad?.(map);
    });

    map.on("click", async (e: MapMouseEvent) => {
      const h = handlers.current;
      const ll: [number, number] = [e.lngLat.lng, e.lngLat.lat];
      if (h.onMapClick) {
        h.onMapClick(ll);
        return;
      }
      const picked = overlay.pickObject({ x: e.point.x, y: e.point.y, radius: 4 });
      if (picked?.object) {
        h.onDeckClick?.(picked);
        return;
      }
      const cl = map.queryRenderedFeatures(e.point, { layers: ["lt-fac-cluster"] });
      if (cl.length) {
        const src = map.getSource("lt-facilities") as GeoJSONSource;
        const zoom = await src.getClusterExpansionZoom(cl[0].properties.cluster_id as number);
        map.easeTo({ center: (cl[0].geometry as GeoJSON.Point).coordinates as [number, number], zoom });
        return;
      }
      const pad = 5;
      const box: [maplibregl.PointLike, maplibregl.PointLike] = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
      const fac = map.queryRenderedFeatures(box, { layers: ["lt-fac"] });
      if (fac.length) {
        h.onSelect?.({ kind: "facility", id: Number(fac[0].properties.id) }, ll);
        return;
      }
      const segLayers = ["lt-roads", "lt-rail", "lt-water"].filter((l) => map.getLayoutProperty(l, "visibility") !== "none");
      const seg = map.queryRenderedFeatures(box, { layers: segLayers }).find((f) => f.properties.id !== undefined);
      if (seg && map.getZoom() >= 6) {
        h.onSelect?.({ kind: "segment", id: Number(seg.properties.id) }, ll);
        return;
      }
      const mun = map.queryRenderedFeatures(e.point, { layers: ["lt-mun-pop", "lt-mun-choro"] });
      if (mun.length) {
        h.onSelect?.({ kind: "municipality", code: Number(mun[0].properties.code) }, ll);
        return;
      }
      h.onSelect?.(null, ll);
    });

    let raf = 0;
    map.on("mousemove", (e) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        if (!map.getLayer("lt-fac")) return;
        const h = handlers.current;
        const picked = overlay.pickObject({ x: e.point.x, y: e.point.y, radius: 3 });
        if (picked?.object && h.getTooltip) {
          const t = h.getTooltip(picked);
          setHover(t ? { x: e.point.x, y: e.point.y, text: t } : null);
          map.getCanvas().style.cursor = t ? "pointer" : "";
          return;
        }
        const f = map.queryRenderedFeatures(e.point, { layers: ["lt-fac", "lt-fac-cluster"] })[0];
        if (f) {
          const p = f.properties;
          setHover({ x: e.point.x, y: e.point.y, text: p.point_count ? `${p.point_count} instalações — clique para ampliar` : String(p.name) });
          map.getCanvas().style.cursor = "pointer";
          return;
        }
        const s = map.getZoom() >= 6
          ? map.queryRenderedFeatures(e.point, { layers: ["lt-roads", "lt-rail", "lt-water"].filter((l) => map.getLayoutProperty(l, "visibility") !== "none") })[0]
          : undefined;
        if (s?.properties.id !== undefined) {
          const p = s.properties;
          const label = p.modal === "road" ? `${p.code ?? "Rodovia"} · ${p.surface ?? "sem classificação"}` : p.modal === "rail" ? `Ferrovia ${p.name ?? ""}` : "Via navegável";
          setHover({ x: e.point.x, y: e.point.y, text: label });
          map.getCanvas().style.cursor = "pointer";
          return;
        }
        setHover(null);
        map.getCanvas().style.cursor = "";
      });
    });
    map.on("mouseout", () => setHover(null));

    return () => {
      clearTimeout(fallback);
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // visibilidade das camadas vetoriais
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (Object.keys(VECTOR_LAYERS) as (keyof VectorToggles)[]).forEach((k) => {
      const vis = vectors[k] ?? (k === "roads" || k === "rail" || k === "waterways" || k === "states");
      VECTOR_LAYERS[k].forEach((id) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", vis ? "visible" : "none"));
    });
  }, [ready, vectors]);

  // instalações (agrupadas)
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const src = map.getSource("lt-facilities") as GeoJSONSource | undefined;
    src?.setData(facilities?.data ?? { type: "FeatureCollection", features: [] });
    ["lt-fac", "lt-fac-cluster", "lt-fac-cluster-count"].forEach((id) =>
      map.setLayoutProperty(id, "visibility", facilities?.visible ? "visible" : "none"),
    );
  }, [ready, facilities?.visible, facilities?.data]);

  // coropléticos via feature-state
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    for (const s of ["states", "municipalities"] as const) {
      map.removeFeatureState({ source: `lt-${s}`, sourceLayer: s });
    }
    map.setLayoutProperty("lt-mun-choro", "visibility", choropleth?.source === "municipalities" ? "visible" : "none");
    map.setLayoutProperty("lt-states-choro", "visibility", choropleth?.source === "states" ? "visible" : "none");
    if (!choropleth) return;
    const layer = choropleth.source === "states" ? "lt-states-choro" : "lt-mun-choro";
    map.setPaintProperty(layer, "fill-opacity", choropleth.opacity ?? 0.75);
    for (const [code, color] of Object.entries(choropleth.colors)) {
      map.setFeatureState({ source: `lt-${choropleth.source}`, sourceLayer: choropleth.source, id: Number(code) }, { color });
    }
  }, [ready, choropleth]);

  useEffect(() => {
    overlayRef.current?.setProps({ layers: deckLayers });
  }, [deckLayers]);

  useEffect(() => {
    if (flyTo && mapRef.current) mapRef.current.flyTo({ center: [flyTo.lon, flyTo.lat], zoom: flyTo.zoom ?? 9, speed: 1.6 });
  }, [flyTo]);

  useEffect(() => {
    if (fitBounds && mapRef.current)
      mapRef.current.fitBounds([[fitBounds[0], fitBounds[1]], [fitBounds[2], fitBounds[3]]], { padding: 60, maxZoom: 11, duration: 900 });
  }, [fitBounds]);

  useEffect(() => {
    if (mapRef.current) mapRef.current.getCanvas().style.cursor = cursor ?? "";
  }, [cursor]);

  // destaque do segmento selecionado na store global
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    return useMapStore.subscribe((s) => {
      const target = { source: "lt-segments", sourceLayer: "segments" };
      if (selectedSeg.current !== null) map.setFeatureState({ ...target, id: selectedSeg.current }, { selected: false });
      selectedSeg.current = s.selection?.kind === "segment" ? s.selection.id : null;
      if (selectedSeg.current !== null) map.setFeatureState({ ...target, id: selectedSeg.current }, { selected: true });
    });
  }, [ready]);

  return (
    <div className={cn("relative h-full w-full overflow-hidden", className)}>
      <div ref={el} style={{ position: "absolute", inset: 0 }} data-testid="map" />
      {!ready && (
        <div className="absolute inset-0 grid place-items-center bg-background/60 text-sm text-muted-foreground">Carregando mapa…</div>
      )}
      {hover && (
        <div
          className="pointer-events-none absolute z-20 max-w-xs rounded-md border border-border bg-popover/95 px-2 py-1 text-xs shadow-lg"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
        >
          {hover.text}
        </div>
      )}
      {children}
    </div>
  );
}

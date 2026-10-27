"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2, MapPin, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { CATEGORY_COLORS } from "@/lib/constants";
import { fmtCompact } from "@/lib/format";
import { useMapStore } from "@/lib/store";
import { FacilitySchema, pageOf, type MunicipalityHit } from "@/lib/types";

function useDebounced<T>(v: T, ms = 250): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

export function GlobalSearch() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const dq = useDebounced(q.trim());
  const router = useRouter();
  const { fly, select } = useMapStore();
  const box = useRef<HTMLDivElement>(null);

  const muns = useQuery({
    queryKey: ["search-mun", dq],
    queryFn: () => api<MunicipalityHit[]>("/territory/municipalities", { query: { q: dq, limit: 6 } }),
    enabled: dq.length >= 2,
  });
  const facs = useQuery({
    queryKey: ["search-fac", dq],
    queryFn: () => api("/facilities", { query: { q: dq, page_size: 6 }, schema: pageOf(FacilitySchema) }),
    enabled: dq.length >= 2,
  });

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const go = (lon: number, lat: number, zoom: number, sel: Parameters<typeof select>[0]) => {
    setOpen(false);
    setQ("");
    router.push("/");
    select(sel);
    setTimeout(() => fly(lon, lat, zoom), 50);
  };

  const show = open && dq.length >= 2;
  return (
    <div ref={box} className="relative">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="Buscar município, porto, terminal, armazém…"
        className="h-8 pl-8"
        aria-label="Busca global"
      />
      {show && (
        <div className="absolute top-9 right-0 left-0 z-50 overflow-hidden rounded-lg border border-border bg-popover shadow-xl">
          <div className="px-3 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Municípios</div>
          {(muns.data ?? []).map((m) => (
            <button
              key={m.code}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent"
              onClick={() => go(m.lon, m.lat, 9, { kind: "municipality", code: m.code })}
            >
              <MapPin className="size-3.5 text-muted-foreground" />
              <span className="truncate">
                {m.name}/{m.uf}
              </span>
              <span className="ml-auto text-xs text-muted-foreground tabular">{fmtCompact(m.population)} hab.</span>
            </button>
          ))}
          {muns.data?.length === 0 && <div className="px-3 py-1.5 text-xs text-muted-foreground">Nenhum município</div>}
          <div className="px-3 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Instalações</div>
          {(facs.data?.items ?? []).map((f) => (
            <button
              key={f.id}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent"
              onClick={() => go(f.lon, f.lat, 11, { kind: "facility", id: f.id })}
            >
              <Building2 className="size-3.5" style={{ color: CATEGORY_COLORS[f.category] }} />
              <span className="truncate">{f.name}</span>
              <span className="ml-auto shrink-0 text-xs text-muted-foreground">{f.uf ?? ""}</span>
            </button>
          ))}
          {facs.data?.items.length === 0 && <div className="px-3 pb-2 text-xs text-muted-foreground">Nenhuma instalação</div>}
        </div>
      )}
    </div>
  );
}

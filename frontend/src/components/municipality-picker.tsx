"use client";

import { useQuery } from "@tanstack/react-query";
import { MapPin, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { fmtCompact } from "@/lib/format";
import type { MunicipalityHit } from "@/lib/types";

export function MunicipalityPicker({
  value, onChange, placeholder = "Município…", testId,
}: {
  value: MunicipalityHit | null;
  onChange: (m: MunicipalityHit | null) => void;
  placeholder?: string;
  testId?: string;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [dq, setDq] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const t = setTimeout(() => setDq(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  const res = useQuery({
    queryKey: ["mun-pick", dq],
    queryFn: () => api<MunicipalityHit[]>("/territory/municipalities", { query: { q: dq, limit: 8 } }),
    enabled: dq.length >= 2,
  });

  if (value)
    return (
      <div className="flex h-8 items-center gap-2 rounded-lg border border-input bg-input/30 px-2.5 text-sm" data-testid={testId}>
        <MapPin className="size-3.5 text-primary" />
        <span className="truncate">
          {value.name}/{value.uf}
        </span>
        <button className="ml-auto text-muted-foreground hover:text-foreground" onClick={() => onChange(null)} aria-label="Limpar">
          <X className="size-3.5" />
        </button>
      </div>
    );
  return (
    <div ref={box} className="relative">
      <Input
        value={q}
        placeholder={placeholder}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        className="h-8"
        data-testid={testId}
      />
      {open && dq.length >= 2 && (
        <div className="absolute top-9 right-0 left-0 z-40 max-h-64 overflow-auto rounded-lg border border-border bg-popover shadow-xl">
          {(res.data ?? []).map((m) => (
            <button
              key={m.code}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm hover:bg-accent"
              onClick={() => {
                onChange(m);
                setQ("");
                setOpen(false);
              }}
            >
              <span className="truncate">
                {m.name}/{m.uf}
              </span>
              <span className="ml-auto text-xs text-muted-foreground tabular">{fmtCompact(m.population)}</span>
            </button>
          ))}
          {res.data?.length === 0 && <div className="px-2.5 py-2 text-xs text-muted-foreground">Nenhum resultado</div>}
        </div>
      )}
    </div>
  );
}

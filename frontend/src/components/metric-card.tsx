"use client";

import { Info } from "lucide-react";
import type { ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fmt } from "@/lib/format";
import type { Metric } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Indicador com definição, unidade, período, fonte, denominador e limitações sempre acessíveis. */
export function MetricCard({ m, className, digits = 1, extra }: { m: Metric; className?: string; digits?: number; extra?: ReactNode }) {
  return (
    <div className={cn("rounded-lg border border-border bg-card p-3", className)} data-testid={`metric-${m.key}`}>
      <div className="flex items-start gap-1.5">
        <div className="text-xs leading-tight text-muted-foreground">{m.label}</div>
        <MetricInfo m={m} />
      </div>
      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span className="text-2xl font-semibold tracking-tight tabular">{fmt(m.value, digits)}</span>
        <span className="text-xs text-muted-foreground">{m.unit}</span>
      </div>
      <div className="mt-1 truncate text-[11px] text-muted-foreground/80">
        {m.period} · {m.source}
      </div>
      {extra}
    </div>
  );
}

export function MetricInfo({ m }: { m: Pick<Metric, "definition" | "unit" | "period" | "source" | "denominator" | "limitations"> }) {
  return (
    <Tooltip>
      <TooltipTrigger render={<button className="ml-auto text-muted-foreground/70 hover:text-foreground" aria-label="Metadados do indicador" />}>
        <Info className="size-3.5" />
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-left">
        <dl className="space-y-1 text-xs">
          <Row k="Definição" v={m.definition} />
          <Row k="Unidade" v={m.unit} />
          <Row k="Período" v={m.period} />
          <Row k="Fonte" v={m.source} />
          {m.denominator && <Row k="Denominador" v={m.denominator} />}
          {m.limitations && <Row k="Limitações" v={m.limitations} />}
        </dl>
      </TooltipContent>
    </Tooltip>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="inline font-medium">{k}: </dt>
      <dd className="inline opacity-90">{v}</dd>
    </div>
  );
}

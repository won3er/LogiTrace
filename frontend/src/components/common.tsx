"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { Progress } from "@/components/ui/progress";
import type { Job } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Painel lateral sobre o mapa: folha inferior no celular, coluna à direita a partir de sm. */
export const MAP_ASIDE =
  "absolute inset-x-2 bottom-2 z-20 flex h-[70%] flex-col overflow-hidden rounded-xl border border-border bg-card/95 shadow-xl backdrop-blur " +
  "sm:inset-x-auto sm:top-3 sm:right-14 sm:bottom-3 sm:h-auto sm:w-80";

export function Panel({ title, actions, children, className, bodyClassName }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string;
}) {
  return (
    <section className={cn("rounded-xl border border-border bg-card/95 shadow-xl backdrop-blur", className)}>
      {(title || actions) && (
        <header className="flex items-center gap-2 border-b border-border px-3 py-2">
          <h2 className="text-sm font-medium">{title}</h2>
          <div className="ml-auto flex items-center gap-1">{actions}</div>
        </header>
      )}
      <div className={cn("p-3", bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-4 sm:px-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 max-w-3xl text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>
    </div>
  );
}

export function Loading({ label = "Carregando…", className }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2 py-6 text-sm text-muted-foreground", className)}>
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorBox({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className={cn("flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200", className)}>
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{msg}</span>
    </div>
  );
}

export function Caveat({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100/90", className)}>
      <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-400" />
      <div>{children}</div>
    </div>
  );
}

export function JobProgress({ job, label }: { job: Job | undefined; label: string }) {
  if (!job) return null;
  if (job.status === "failed") return <ErrorBox error={job.error?.split("\n")[0] ?? "Falha na tarefa"} />;
  if (job.status === "success") return null;
  return (
    <div className="space-y-1.5 rounded-lg border border-border bg-muted/40 p-3" data-testid="job-progress">
      <div className="flex items-center gap-2 text-sm">
        <Loader2 className="size-4 animate-spin text-primary" /> {label}
        <span className="ml-auto text-xs text-muted-foreground">{job.status === "queued" ? "na fila" : "executando"}</span>
      </div>
      <Progress value={Math.max(5, job.progress * 100)} />
      {job.message && <div className="text-xs text-muted-foreground">{job.message}</div>}
    </div>
  );
}

export function KV({ k, v, className }: { k: ReactNode; v: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 py-0.5 text-sm", className)}>
      <span className="text-muted-foreground">{k}</span>
      <span className="text-right tabular">{v}</span>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-muted-foreground/80">{hint}</span>}
    </label>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "up" | "down" | "neutral" }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn("text-lg font-semibold tabular", tone === "up" && "text-red-300", tone === "down" && "text-emerald-300")}>{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

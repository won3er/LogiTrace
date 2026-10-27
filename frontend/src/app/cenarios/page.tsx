"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { FlaskConical, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { ErrorBox, Loading, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Template = { key: string; name: string; description: string; change_types: string[] };
type ScenarioRow = { id: number; name: string; description: string | null; created_at: string; runs: number; last_run_at: string | null };

const PRESETS: Record<string, { name: string; config: Record<string, unknown> }> = {
  interruption: { name: "Interrupção de infraestrutura", config: { od_benchmark: "capitals", metric: "cost", mode: "road" } },
  new_dc: { name: "Novo centro de distribuição", config: { od_benchmark: "none", demand: { level: "immediate_region", ufs: ["SP"] } } },
  redistribution: { name: "Redistribuição de demanda", config: { od_benchmark: "none", demand: { level: "immediate_region", ufs: ["PR", "SC", "RS"] } } },
  costs: { name: "Alteração de custos", config: { od_benchmark: "capitals" } },
  demand: { name: "Variação de demanda", config: { od_benchmark: "none", demand: { level: "immediate_region", ufs: ["SP", "MG"] } } },
  capacity: { name: "Alteração de capacidade", config: { od_benchmark: "none", demand: { level: "immediate_region", ufs: ["GO", "MT", "MS"] } } },
};

export default function ScenariosPage() {
  const router = useRouter();
  const templates = useQuery({ queryKey: ["templates"], queryFn: () => api<Template[]>("/scenarios/templates") });
  const list = useQuery({ queryKey: ["scenarios"], queryFn: () => api<ScenarioRow[]>("/scenarios") });
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<{ id: number }>("/scenarios", { body }),
    onSuccess: (r) => router.push(`/cenarios/${r.id}`),
  });

  // atalho vindo do mapa: "simular interdição deste trecho"
  const once = useRef(false);
  useEffect(() => {
    const seg = new URLSearchParams(window.location.search).get("close_segment");
    if (seg && !once.current) {
      once.current = true;
      create.mutate({
        name: `Interdição do segmento ${seg}`,
        config: { od_benchmark: "capitals", metric: "cost", mode: "road" },
        changes: [{ change_type: "closure", payload: { segment_ids: [Number(seg)] }, note: "criado a partir do mapa" }],
      });
    }
  }, [create]);

  return (
    <div>
      <PageHeader title="Simulador de cenários" subtitle="Cada cenário é a base oficial + alterações. A base nunca é modificada; toda execução registra parâmetros, premissas, versão da rede e hashes para reprodução." />
      <div className="grid gap-6 p-4 sm:p-6 lg:grid-cols-[1fr_420px]">
        <div>
          <h2 className="mb-3 text-sm font-medium">Cenários salvos</h2>
          {list.isLoading && <Loading />}
          <ErrorBox error={list.error ?? create.error} />
          {list.data?.length === 0 && <p className="text-sm text-muted-foreground">Nenhum cenário ainda. Comece por um modelo ao lado.</p>}
          <div className="grid gap-2">
            {list.data?.map((s) => (
              <Link key={s.id} href={`/cenarios/${s.id}`} className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 hover:bg-accent/40" data-testid="scenario-row">
                <FlaskConical className="size-4 text-primary" />
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{s.name}</div>
                  <div className="text-xs text-muted-foreground">criado {fmtDate(s.created_at)} · {s.runs} execuções{s.last_run_at ? ` · última ${fmtDate(s.last_run_at)}` : ""}</div>
                </div>
              </Link>
            ))}
          </div>
        </div>
        <div>
          <h2 className="mb-3 text-sm font-medium">Novo cenário a partir de um modelo</h2>
          <div className="grid gap-2">
            {templates.data?.map((t) => (
              <div key={t.key} className="rounded-lg border border-border bg-card p-3">
                <div className="flex items-center gap-2">
                  <div className="text-sm font-medium">{t.name}</div>
                  <Button size="xs" className="ml-auto" disabled={create.isPending} data-testid={`new-${t.key}`}
                    onClick={() => create.mutate({ name: PRESETS[t.key]?.name ?? t.name, description: t.description, config: PRESETS[t.key]?.config ?? {}, changes: [] })}>
                    <Plus /> Criar
                  </Button>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{t.description}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

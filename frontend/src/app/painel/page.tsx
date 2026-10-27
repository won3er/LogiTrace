"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Chart } from "@/components/chart";
import { ErrorBox, Loading, PageHeader } from "@/components/common";
import { MetricCard } from "@/components/metric-card";
import { api } from "@/lib/api";
import { CATEGORY_COLORS, CATEGORY_LABELS, MODAL_COLORS, MODAL_LABELS, QUALITY_LABELS, QUALITY_STYLES } from "@/lib/constants";
import { fmt, fmtBRL, fmtCompact, fmtDate, fmtPct, fmtSigned } from "@/lib/format";
import { MetricSchema } from "@/lib/types";
import { z } from "zod";

const OverviewSchema = z.object({
  metrics: z.array(MetricSchema),
  by_category: z.array(z.object({ category: z.string(), modal: z.string(), n: z.number(), cap: z.number().nullable() })),
  top_states_by_facilities: z.array(z.object({ uf: z.string(), n: z.number(), pop: z.number(), per_100k: z.number() })),
  network: z.object({ version_id: z.number(), label: z.string(), km_by_modal: z.record(z.string(), z.number()).nullable().optional(),
    unconnected_anchors: z.record(z.string(), z.number()).nullable().optional(), transfer_edges: z.number().nullable().optional() }),
  flows: z.array(z.object({ dataset: z.string(), flow_class: z.string(), unit: z.string(), links: z.number(), total: z.number() })),
  recent_scenarios: z.array(z.any()),
  recent_optimizations: z.array(z.any()),
  critical_edges: z.array(z.any()),
  critical_job_id: z.number().nullable(),
});

export default function DashboardPage() {
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api("/analytics/overview", { schema: OverviewSchema }) });
  if (q.isLoading) return <Loading className="p-6" label="Calculando indicadores…" />;
  if (q.error) return <ErrorBox error={q.error} className="m-6" />;
  const d = q.data!;
  const cats = Object.entries(d.by_category.reduce<Record<string, number>>((a, r) => ({ ...a, [r.category]: (a[r.category] ?? 0) + r.n }), {})).sort((a, b) => b[1] - a[1]);
  const km = Object.entries(d.network.km_by_modal ?? {}).filter(([m]) => ["road", "rail", "waterway"].includes(m));
  return (
    <div className="pb-10">
      <PageHeader title="Painel analítico" subtitle="Todos os números são derivados das bases importadas e dos cálculos executados. Passe o cursor no ícone de informação para ver definição, unidade, período, fonte e limitações." />
      <div className="grid gap-3 p-4 sm:grid-cols-2 sm:p-6 lg:grid-cols-3 xl:grid-cols-5" data-testid="kpis">
        {d.metrics.map((m) => <MetricCard key={m.key} m={m} digits={m.unit === "×" ? 3 : m.unit === "%" ? 2 : 0} />)}
      </div>
      <div className="grid gap-4 px-4 sm:px-6 lg:grid-cols-3">
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Instalações por categoria</h2>
          <p className="text-xs text-muted-foreground">Contagem de registros · IBGE 2014/2024 + usuário</p>
          <Chart height={280} option={{
            tooltip: { trigger: "axis" }, grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
            xAxis: { type: "value" }, yAxis: { type: "category", data: cats.map(([c]) => CATEGORY_LABELS[c] ?? c).reverse(), axisLabel: { fontSize: 10 } },
            series: [{ type: "bar", data: cats.map(([c, n]) => ({ value: n, itemStyle: { color: CATEGORY_COLORS[c] ?? "#94a3b8" } })).reverse() }],
          }} />
        </section>
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Extensão da rede por modal (grafo v{d.network.version_id})</h2>
          <p className="text-xs text-muted-foreground">km de arestas após limpeza topológica · malha IBGE 2014</p>
          <Chart height={280} option={{
            tooltip: { trigger: "item", formatter: (p: any) => `${p.name}: ${fmt(p.value, 0)} km (${p.percent}%)` },
            series: [{ type: "pie", radius: ["45%", "72%"], label: { color: "#cbd5e1", formatter: "{b}\n{d}%" },
              data: km.map(([m, v]) => ({ name: MODAL_LABELS[m], value: v, itemStyle: { color: MODAL_COLORS[m] } })) }],
          }} />
          <p className="text-[11px] text-muted-foreground">{d.network.transfer_edges} conexões de transbordo intermodal · {d.network.unconnected_anchors?.municipality ?? 0} municípios sem acesso rodoviário a até 60 km.</p>
        </section>
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">UFs com mais instalações</h2>
          <p className="text-xs text-muted-foreground">Barras: contagem · linha: por 100 mil hab. (pop. 2022)</p>
          <Chart height={280} option={{
            tooltip: { trigger: "axis" }, legend: { top: 0, textStyle: { fontSize: 10 } }, grid: { left: 8, right: 8, top: 28, bottom: 8, containLabel: true },
            xAxis: { type: "category", data: d.top_states_by_facilities.map((s) => s.uf) },
            yAxis: [{ type: "value" }, { type: "value", splitLine: { show: false } }],
            series: [
              { name: "Instalações", type: "bar", data: d.top_states_by_facilities.map((s) => s.n) },
              { name: "por 100 mil hab.", type: "line", yAxisIndex: 1, data: d.top_states_by_facilities.map((s) => s.per_100k) },
            ],
          }} />
        </section>
      </div>
      <div className="mt-4 grid gap-4 px-4 sm:px-6 lg:grid-cols-3">
        <section className="overflow-x-auto rounded-xl border border-border bg-card p-4">
          <h2 className="mb-2 text-sm font-medium">Fluxos de mercadorias por conjunto</h2>
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground"><tr><th className="py-1">Conjunto</th><th>Classe</th><th className="text-right">Ligações</th><th className="text-right">Total</th></tr></thead>
            <tbody>{d.flows.map((f) => (
              <tr key={f.dataset} className="border-t border-border/60"><td className="py-1">{f.dataset.replace("ibge_2024_", "")}</td><td>{f.flow_class}</td><td className="text-right tabular">{fmt(f.links, 0)}</td><td className="text-right tabular">{fmtCompact(f.total)} {f.unit}</td></tr>
            ))}</tbody>
          </table>
          <p className="mt-2 text-[11px] text-muted-foreground">Unidades diferem entre conjuntos e não são somadas.</p>
        </section>
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-2 text-sm font-medium">Resultados de cenários recentes</h2>
          {d.recent_scenarios.length === 0 && <p className="text-xs text-muted-foreground">Nenhuma execução. <Link href="/cenarios" className="text-primary">Criar cenário →</Link></p>}
          {d.recent_scenarios.map((s: any) => (
            <Link key={s.run_id} href={`/cenarios/${s.scenario_id}`} className="block border-t border-border/60 py-1.5 text-xs hover:bg-accent/40">
              <div>Execução #{s.run_id} · {fmtDate(s.finished_at)}</div>
              <div className="text-muted-foreground">{s.summary.od_pairs_affected} pares afetados · Δ custo {fmtSigned(s.summary.od_delta_sum_cost_brl, 2)} R$/t{s.summary.service?.coverage_share ? ` · cobertura ${fmtPct(s.summary.service.coverage_share.base)} → ${fmtPct(s.summary.service.coverage_share.scenario)}` : ""}</div>
            </Link>
          ))}
        </section>
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-2 text-sm font-medium">Otimizações recentes</h2>
          {d.recent_optimizations.length === 0 && <p className="text-xs text-muted-foreground">Nenhuma execução. <Link href="/otimizacao" className="text-primary">Otimizar →</Link></p>}
          {d.recent_optimizations.map((o: any) => (
            <div key={o.run_id} className="border-t border-border/60 py-1.5 text-xs">
              <div className="flex items-center gap-2">#{o.run_id} {o.label ?? o.problem}<span className={`ml-auto rounded border px-1 text-[10px] ${QUALITY_STYLES[o.quality] ?? ""}`}>{QUALITY_LABELS[o.quality] ?? o.quality}</span></div>
              {o.kpis && <div className="text-muted-foreground">{o.kpis.facilities_open} instalações · atendimento {fmtPct(o.kpis.service_level)} · {fmtBRL(o.kpis.transport_cost)}/ano · cobertura {fmtPct(o.kpis.coverage_share)}</div>}
            </div>
          ))}
        </section>
      </div>
      <section className="mx-4 mt-4 overflow-x-auto rounded-xl border border-border bg-card p-4 sm:mx-6">
        <h2 className="mb-2 text-sm font-medium">Conexões críticas (última análise)</h2>
        {d.critical_edges.length === 0 ? <p className="text-xs text-muted-foreground">Nenhuma análise executada. <Link href="/rede" className="text-primary">Executar em Motor de redes → Criticidade</Link></p> : (
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground"><tr><th className="py-1">Conexão</th><th className="text-right">km</th><th className="text-right">Uso (pares ponderados)</th><th className="text-right">Pares afetados</th><th className="text-right">Δ custo médio (R$/t)</th></tr></thead>
            <tbody>{d.critical_edges.map((e: any) => (
              <tr key={e.edge} className="border-t border-border/60"><td className="py-1">{e.code ?? `aresta ${e.edge}`}</td><td className="text-right tabular">{fmt(e.km, 0)}</td><td className="text-right tabular">{fmtPct(e.usage_share)}</td><td className="text-right tabular">{e.affected_pairs}</td><td className="text-right tabular">{fmt(e.weighted_delta, 2)}</td></tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </div>
  );
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { ErrorBox, JobProgress, Loading, PageHeader } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useJob } from "@/hooks/use-job";
import { api } from "@/lib/api";
import { fmt, fmtDate } from "@/lib/format";

export default function DataPage() {
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => api<any[]>("/sources") });
  const imports = useQuery({ queryKey: ["imports"], queryFn: () => api<any[]>("/imports") });
  const versions = useQuery({ queryKey: ["versions"], queryFn: () => api<any[]>("/network/versions") });
  return (
    <div className="pb-10">
      <PageHeader title="Fontes, dados e premissas" subtitle="Proveniência de cada conjunto importado, histórico de importações com validação, premissas paramétricas editáveis e versões do grafo." />
      <Tabs defaultValue="sources" className="px-4 pt-4 sm:px-6">
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="sources">Fontes</TabsTrigger>
          <TabsTrigger value="imports">Importações</TabsTrigger>
          <TabsTrigger value="assumptions">Premissas</TabsTrigger>
          <TabsTrigger value="network">Versões da rede</TabsTrigger>
        </TabsList>
        <TabsContent value="sources" className="mt-4 grid gap-3 lg:grid-cols-2">
          {sources.isLoading && <Loading />}
          {sources.data?.map((s) => (
            <div key={s.key} className="rounded-xl border border-border bg-card p-4 text-sm" data-testid="source-card">
              <div className="flex items-start gap-2">
                <div>
                  <div className="font-medium">{s.name}</div>
                  <div className="text-xs text-muted-foreground">{s.publisher} · referência: {s.reference_date}</div>
                </div>
                <Badge variant="outline" className="ml-auto">confiabilidade {s.reliability}</Badge>
              </div>
              <dl className="mt-2 space-y-1 text-xs">
                <div><dt className="inline text-muted-foreground">Cobertura: </dt><dd className="inline">{s.coverage}</dd></div>
                <div><dt className="inline text-muted-foreground">Licença: </dt><dd className="inline">{s.license}</dd></div>
                <div><dt className="inline text-muted-foreground">Atribuição: </dt><dd className="inline">{s.attribution}</dd></div>
                <div><dt className="inline text-muted-foreground">Atualização: </dt><dd className="inline">{s.update_method}</dd></div>
                <div className="text-amber-100/80"><dt className="inline text-muted-foreground">Limitações: </dt><dd className="inline">{s.limitations}</dd></div>
              </dl>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                <span>{fmt(s.facilities, 0)} instalações · {fmt(s.segments, 0)} segmentos · {fmt(s.flows, 0)} fluxos</span>
                {s.url?.startsWith("http") && <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">origem <ExternalLink className="size-3" /></a>}
                {s.last_import && <span>última importação #{s.last_import.id} ({s.last_import.status}) {fmtDate(s.last_import.finished_at)}</span>}
              </div>
            </div>
          ))}
        </TabsContent>
        <TabsContent value="imports" className="mt-4 overflow-x-auto">
          <ErrorBox error={imports.error} />
          <table className="w-full min-w-[900px] text-xs">
            <thead className="text-left text-muted-foreground"><tr><th className="py-1">#</th><th>Conjunto</th><th>Arquivo / SHA-256</th><th>Status</th><th className="text-right">Lidos</th><th className="text-right">Novos</th><th className="text-right">Alterados</th><th className="text-right">Inalterados</th><th className="text-right">Rejeitados</th><th className="text-right">Avisos</th><th>Concluída</th></tr></thead>
            <tbody>{imports.data?.map((r) => (
              <tr key={r.id} className="border-t border-border/60">
                <td className="py-1">{r.id}</td><td>{r.dataset}</td>
                <td className="max-w-56 truncate" title={r.sha256 ?? ""}>{r.file ?? "—"} <span className="font-mono text-muted-foreground">{r.sha256?.slice(0, 10)}</span></td>
                <td><Badge variant="outline" className={r.status === "success" ? "text-emerald-300" : r.status === "partial" ? "text-amber-300" : "text-red-300"}>{r.status}</Badge></td>
                <td className="text-right tabular">{fmt(r.rows_read, 0)}</td><td className="text-right tabular">{fmt(r.inserted, 0)}</td><td className="text-right tabular">{fmt(r.updated, 0)}</td>
                <td className="text-right tabular">{fmt(r.unchanged, 0)}</td><td className="text-right tabular">{fmt(r.rejected, 0)}</td><td className="text-right tabular">{fmt(r.report?.warnings_total ?? 0, 0)}</td>
                <td>{fmtDate(r.finished_at)}</td>
              </tr>
            ))}</tbody>
          </table>
          <p className="mt-2 text-xs text-muted-foreground">Reimportações comparam o hash de conteúdo de cada registro (por fonte + identificador) e registram novos, alterados, inalterados e ausentes; registros oficiais não são apagados silenciosamente.</p>
        </TabsContent>
        <TabsContent value="assumptions" className="mt-4"><Assumptions /></TabsContent>
        <TabsContent value="network" className="mt-4 space-y-3">
          <RebuildNetwork />
          {versions.data?.map((v) => (
            <div key={v.id} className="rounded-xl border border-border bg-card p-3 text-xs">
              <div className="flex items-center gap-2 text-sm"><b>v{v.id}</b> {v.label} <Badge variant="outline">{v.status}</Badge><span className="ml-auto text-xs text-muted-foreground">{fmtDate(v.created_at)}</span></div>
              <div className="mt-1 text-muted-foreground">{fmt(v.nodes, 0)} nós · {fmt(v.edges, 0)} arestas · checksum {v.checksum?.slice(0, 16)} · importações {v.import_runs?.join(", ")}</div>
              <div className="mt-1 text-muted-foreground">km por modal: {Object.entries(v.stats?.km_by_modal ?? {}).map(([k, x]) => `${k} ${fmt(x as number, 0)}`).join(" · ")} · construída em {v.stats?.build_seconds}s</div>
              <div className="text-muted-foreground">Parâmetros: {JSON.stringify(v.params)}</div>
            </div>
          ))}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Assumptions() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["assumptions"], queryFn: () => api<any[]>("/assumptions") });
  const [edit, setEdit] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: ({ key, value }: { key: string; value: number }) => api(`/assumptions/${key}`, { method: "PUT", body: { value } }),
    onSuccess: (_, v) => { toast.success(`Premissa ${v.key} atualizada`); qc.invalidateQueries({ queryKey: ["assumptions"] }); setEdit((e) => ({ ...e, [v.key]: "" })); },
    onError: (e) => toast.error(String(e)),
  });
  if (q.isLoading) return <Loading />;
  return (
    <div className="overflow-x-auto">
      <p className="mb-3 text-xs text-muted-foreground">Premissas não são dados observados. Alterá-las muda o padrão das próximas execuções; execuções anteriores mantêm o snapshot das premissas que usaram. Para testar sem alterar o padrão, use um cenário de “Alteração de custos”.</p>
      <table className="w-full min-w-[760px] text-xs">
        <thead className="text-left text-muted-foreground"><tr><th className="py-1">Premissa</th><th>Categoria</th><th className="text-right">Valor</th><th className="text-right">Padrão</th><th>Unidade</th><th>Justificativa</th><th></th></tr></thead>
        <tbody>{q.data?.map((a) => (
          <tr key={a.key} className="border-t border-border/60 align-top">
            <td className="py-1.5"><div className="font-mono">{a.key}</div><div className="text-muted-foreground">{a.description}</div></td>
            <td>{a.category}</td>
            <td className="text-right tabular">{a.value}</td><td className="text-right tabular text-muted-foreground">{a.default}</td><td>{a.unit}</td>
            <td className="max-w-md text-muted-foreground">{a.rationale}</td>
            <td className="w-36">
              <div className="flex gap-1">
                <Input className="h-7 text-xs" type="number" step="any" value={edit[a.key] ?? ""} placeholder={String(a.value)} onChange={(e) => setEdit({ ...edit, [a.key]: e.target.value })} />
                <Button size="xs" variant="secondary" disabled={!edit[a.key]} onClick={() => save.mutate({ key: a.key, value: Number(edit[a.key]) })}>OK</Button>
              </div>
            </td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function RebuildNetwork() {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(jobId);
  const m = useMutation({ mutationFn: () => api<{ job_id: number }>("/network/build", { method: "POST" }), onSuccess: (r) => setJobId(r.job_id) });
  useEffect(() => {
    if (job.data?.status === "success") qc.invalidateQueries({ queryKey: ["versions"] });
  }, [job.data?.status, qc]);
  return (
    <div className="space-y-2">
      <Button size="sm" variant="outline" onClick={() => m.mutate()} disabled={m.isPending || job.data?.status === "running"}><RefreshCw /> Construir nova versão da rede</Button>
      <p className="text-xs text-muted-foreground">Necessário após cadastrar instalações do usuário ou alterar premissas de rede (tolerância, raios). Versões anteriores permanecem para reprodução.</p>
      <JobProgress job={job.data} label="Construindo grafo" />
      {job.data?.status === "success" && <p className="text-xs text-emerald-300">Versão v{job.data.ref_id} construída.</p>}
    </div>
  );
}

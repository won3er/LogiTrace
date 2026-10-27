"""Relatórios PDF (ReportLab + Matplotlib): objetivo, área/rede, fontes, premissas, resultados, mapas,
comparação, limitações e recomendações derivadas dos cálculos."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402
from shapely import wkb  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models import DataSource, NetworkVersion, OptimizationRun, Scenario, ScenarioRun  # noqa: E402
from app.network.engine import NetworkGraph  # noqa: E402

INK = colors.HexColor("#0f172a")
ACCENT = colors.HexColor("#0e7490")
_styles = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_styles["Heading1"], textColor=INK, fontSize=17, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=_styles["Heading2"], textColor=ACCENT, fontSize=12.5, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("b", parent=_styles["BodyText"], fontSize=9, leading=12.5)
SMALL = ParagraphStyle("s", parent=BODY, fontSize=7.5, leading=10, textColor=colors.HexColor("#475569"))


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    return str(v)


def _table(rows: list[list[Any]], widths: list[float] | None = None, header: bool = True) -> Table:
    data = [[Paragraph(_fmt(c), SMALL if i else BODY) if not isinstance(c, Paragraph) else c for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("FONTSIZE", (0, 0), (-1, -1), 7.5)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0"))]
    t.setStyle(TableStyle(st))
    return t


def _states_outline(db: Session, ax: Any, bbox: tuple[float, float, float, float] | None = None) -> None:
    for (g,) in db.execute(text("SELECT ST_AsBinary(ST_SimplifyPreserveTopology(geom, 0.02)) FROM state")):
        shp = wkb.loads(bytes(g))
        for poly in getattr(shp, "geoms", [shp]):
            x, y = poly.exterior.xy
            ax.plot(x, y, color="#94a3b8", lw=0.4)
    if bbox:
        ax.set_xlim(bbox[0], bbox[2])
        ax.set_ylim(bbox[1], bbox[3])
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def _fig_to_image(fig: Any, width_cm: float = 17) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    img = Image(buf)
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width_cm * cm
    img.drawHeight = width_cm * cm * ratio
    return img


def _sources_section(db: Session, keys: list[str]) -> list[Any]:
    out: list[Any] = [Paragraph("Fontes utilizadas", H2)]
    rows = [["Fonte", "Referência", "Licença / atribuição", "Limitações"]]
    for s in db.scalars(select(DataSource).where(DataSource.key.in_(keys))):
        rows.append([f"{s.name} ({s.publisher})", s.reference_date, s.attribution, s.limitations])
    out.append(_table(rows, [4.5 * cm, 2.5 * cm, 4 * cm, 6 * cm]))
    return out


def _doc(title: str, story: list[Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm,
                            bottomMargin=1.6 * cm, title=title, author="LogiTrace")

    def footer(canvas: Any, d: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(1.8 * cm, 1 * cm, f"LogiTrace — {title} — gerado em {datetime.now():%d/%m/%Y %H:%M}")
        canvas.drawRightString(A4[0] - 1.8 * cm, 1 * cm, f"p. {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _assumption_rows(a: dict[str, float], keys: tuple[str, ...] = ("speed.", "cost.", "time.", "demand.", "coverage.", "capacity.")) -> list[list[Any]]:
    return [["Premissa", "Valor"]] + [[k, a[k]] for k in sorted(a) if k.startswith(keys)]


# ------------------------------------------------------------------------------------------- cenário
def scenario_report(db: Session, run: ScenarioRun, g: NetworkGraph) -> bytes:
    sc = db.get(Scenario, run.scenario_id)
    assert sc is not None
    res, inp = run.results, run.inputs
    cmp_ = res["comparison"]
    nv = db.get(NetworkVersion, run.network_version_id)
    story: list[Any] = [Paragraph(f"Relatório de cenário — {sc.name}", H1),
                        Paragraph(f"Execução #{run.id} · {run.finished_at:%d/%m/%Y %H:%M} · hash das entradas {run.input_hash[:12]} · "
                                  f"hash dos resultados {(run.result_hash or '')[:12]}", SMALL)]
    story += [Paragraph("Objetivo da análise", H2),
              Paragraph(sc.description or "Avaliar o efeito das alterações do cenário sobre rotas, custos, cobertura e "
                                          "atendimento, comparando com a base sem alterações.", BODY)]
    cfg = inp["config"]
    story += [Paragraph("Área e rede consideradas", H2), Paragraph(
        f"Rede v{run.network_version_id} ({nv.label if nv else ''}; {g.n_nodes:,} nós, {g.n_edges:,} arestas). "
        f"Modo: {'rodoviário' if cfg['mode'] == 'road' else 'multimodal'}; métrica: {cfg['metric']}. "
        f"Pares OD: {'definidos pelo usuário' if cfg['od_pairs'] else 'todos os pares de capitais estaduais'}. "
        f"Demanda: nível {cfg['demand']['level']}{', UFs ' + ', '.join(cfg['demand']['ufs']) if cfg['demand'].get('ufs') else ', Brasil'}.", BODY)]
    story += _sources_section(db, ["ibge_logistica_2014", "ibge_localidades", "ibge_malhas", "ibge_censo2022_pop"])
    story += [Paragraph("Alterações do cenário", H2)]
    rows = [["Tipo", "Parâmetros", "Efeito aplicado"]]
    for ch in res["scenario"]["applied_changes"]:
        eff = ", ".join(f"{k}: {v}" for k, v in ch.items() if k not in ("type", "payload")) or "—"
        rows.append([ch["type"], str(ch["payload"])[:220], eff])
    story.append(_table(rows, [3 * cm, 9 * cm, 5 * cm]))
    story += [Paragraph("Parâmetros e premissas", H2), _table(_assumption_rows(inp["assumptions"]), [9 * cm, 3 * cm])]

    story += [PageBreak(), Paragraph("Resultados", H2)]
    bt, stt = res["baseline"]["od"]["totals"], res["scenario"]["od"]["totals"]
    story.append(_table([
        ["Indicador", "Base", "Cenário", "Variação"],
        ["Pares OD conectados", bt.get("connected"), stt.get("connected"), (stt.get("connected") or 0) - (bt.get("connected") or 0)],
        ["Soma das distâncias (km)", bt.get("sum_km"), stt.get("sum_km"), cmp_["od_delta_sum_km"]],
        ["Soma dos tempos (h)", bt.get("sum_time_h"), stt.get("sum_time_h"), cmp_["od_delta_sum_time_h"]],
        ["Soma dos custos (R$)", bt.get("sum_cost_brl"), stt.get("sum_cost_brl"), cmp_["od_delta_sum_cost_brl"]],
        ["Pares afetados", "—", cmp_["od_pairs_affected"], "—"],
        ["Pares desconectados pelo cenário", "—", cmp_["od_pairs_disconnected"], "—"],
    ], [7 * cm, 3.3 * cm, 3.3 * cm, 3.3 * cm]))
    if cmp_.get("service"):
        rows = [["Indicador de atendimento", "Base", "Cenário", "Variação"]]
        for k, v in cmp_["service"].items():
            rows.append([k, v["base"], v["scenario"], v["delta"]])
        story += [Spacer(1, 6), _table(rows, [7 * cm, 3.3 * cm, 3.3 * cm, 3.3 * cm])]

    fig, ax = plt.subplots(figsize=(8, 7))
    _states_outline(db, ax)
    drawn = 0
    for p in cmp_["pairs"][:15]:
        for kind, color, lw in (("base_edges", "#64748b", 1.6), ("scenario_edges", "#dc2626", 1.1)):
            for e in p.get(kind) or []:
                xs, ys = zip(*g.geometry[e])
                ax.plot(xs, ys, color=color, lw=lw, alpha=0.8)
                drawn += 1
    closed = res["scenario"].get("closed_edge_ids") or []
    for e in closed[:3000]:
        xs, ys = zip(*g.geometry[e])
        ax.plot(xs, ys, color="#111827", lw=2.5)
    svc = res["scenario"].get("service")
    if svc:
        for f in svc["open_facilities"]:
            ax.scatter(f["lon"], f["lat"], s=40, c="#0e7490", edgecolors="white", zorder=5)
    ax.set_title("Rotas afetadas: cinza = base, vermelho = cenário; preto = interdições; azul = instalações", fontsize=8)
    if drawn or closed or svc:
        xs = [c[0] for e in closed[:3000] for c in g.geometry[e]] + [f["lon"] for f in (svc or {}).get("open_facilities", [])]
        ys = [c[1] for e in closed[:3000] for c in g.geometry[e]] + [f["lat"] for f in (svc or {}).get("open_facilities", [])]
        for p in cmp_["pairs"][:15]:
            for e in (p.get("base_edges") or []) + (p.get("scenario_edges") or []):
                xs += [c[0] for c in g.geometry[e]]
                ys += [c[1] for c in g.geometry[e]]
        if xs:
            pad = 1.5
            ax.set_xlim(min(xs) - pad, max(xs) + pad)
            ax.set_ylim(min(ys) - pad, max(ys) + pad)
    story.append(KeepTogether([Paragraph("Mapa", H2), _fig_to_image(fig, 13)]))

    if cmp_["pairs"]:
        rows = [["Origem → destino", "Δ km", "Δ h", "Δ R$/t", "Situação"]]
        for p in cmp_["pairs"][:25]:
            status = "desconectado" if p["base_connected"] and not p["scenario_connected"] else ("rota alterada" if p.get("route_changed") else "custo alterado")
            rows.append([f"{p['origin']} → {p['dest']}", p.get("delta_km"), p.get("delta_time_h"), p.get("delta_cost_brl_t"), status])
        story += [Paragraph("Comparação de rotas (pares mais afetados)", H2), _table(rows, [7.5 * cm, 2 * cm, 2 * cm, 2.2 * cm, 3.3 * cm])]
        top = [p for p in cmp_["pairs"] if p.get("delta_cost_brl_t") is not None][:10]
        if top:
            fig, ax = plt.subplots(figsize=(8, 3.2))
            ax.barh([f"{p['origin'][:14]}→{p['dest'][:14]}" for p in top][::-1], [p["delta_cost_brl_t"] for p in top][::-1], color="#0e7490")
            ax.set_xlabel("Variação de custo (R$/t)")
            ax.tick_params(labelsize=7)
            story.append(_fig_to_image(fig, 15))
    if svc:
        rows = [["Instalação", "Capacidade (t/ano)", "Carga (t/ano)", "Utilização", "Preço-sombra (R$/t)"]]
        for f in svc["open_facilities"]:
            rows.append([f["name"], f["capacity_t"], f["load_t"], f"{(f['utilization'] or 0) * 100:.1f}%", f.get("capacity_shadow_price")])
        story += [Paragraph("Instalações no cenário (alocação ótima — LP)", H2), _table(rows, [6.5 * cm, 2.7 * cm, 2.7 * cm, 2.2 * cm, 2.9 * cm])]

    story += [Paragraph("Limitações", H2)] + [Paragraph("• " + t, BODY) for t in (
        "Malha de 2014 (IBGE/SNV): não inclui obras e alterações posteriores; rodovias sem capacidade e pedágios reais.",
        "Tempo e custo derivam de premissas paramétricas, explicitadas acima; não são observações.",
        "Demanda é proxy populacional (Censo 2022), não medição de consumo logístico.",
        "Interdições removem arestas inteiras do grafo; o efeito local depende da granularidade dos trechos.",
    )]
    story += [Paragraph("Recomendações derivadas dos cálculos", H2)] + [Paragraph("• " + t, BODY) for t in _scenario_recs(cmp_, svc)]
    return _doc(f"Cenário {sc.name}", story)


def _scenario_recs(cmp_: dict[str, Any], svc: dict[str, Any] | None) -> list[str]:
    recs = []
    if cmp_["od_pairs_disconnected"]:
        recs.append(f"{cmp_['od_pairs_disconnected']} pares OD perdem conexão: não há rota alternativa terrestre na base; "
                    "priorize contingência multimodal ou reabertura.")
    if cmp_["od_pairs_affected"]:
        worst = next((p for p in cmp_["pairs"] if p.get("delta_cost_brl_t") is not None), None)
        if worst:
            recs.append(f"Maior impacto em {worst['origin']} → {worst['dest']}: +{worst['delta_cost_brl_t']:.2f} R$/t e "
                        f"+{worst['delta_km']:.0f} km pela melhor alternativa.")
    if svc:
        over = [f["name"] for f in svc.get("overloaded", [])]
        if over:
            recs.append(f"Capacidade restritiva (utilização 100%, preço-sombra > 0) em: {', '.join(over[:6])}. "
                        "Expandir essas instalações reduz custo/demanda não atendida conforme o preço-sombra.")
        unmet = svc["kpis"]["unmet_t"]
        if unmet > 0:
            recs.append(f"Demanda não atendida de {unmet:,.0f} t/ano com as capacidades atuais.")
    if not recs:
        recs.append("As alterações não produzem impacto mensurável nos indicadores calculados.")
    return recs


# ------------------------------------------------------------------------------------------- otimização
def optimization_report(db: Session, run: OptimizationRun) -> bytes:
    res = run.results or {}
    req = run.params["request"]
    story: list[Any] = [Paragraph(f"Relatório de otimização — {run.label or run.problem}", H1),
                        Paragraph(f"Execução #{run.id} · {run.created_at:%d/%m/%Y %H:%M} · rede v{run.network_version_id} · "
                                  f"hash das entradas {run.input_hash[:12]}", SMALL)]
    story += [Paragraph("Objetivo da análise", H2), Paragraph(run.objective or "", BODY),
              Paragraph("Status da solução", H2),
              _table([["Qualidade", "Solver", "Valor objetivo", "Limitante", "Gap", "Tempo (ms)"],
                      [run.solution_quality, run.solver, run.objective_value, run.best_bound,
                       f"{run.gap * 100:.3f}%" if run.gap is not None else "—", run.solve_time_ms]],
                     [2.3 * cm, 4.5 * cm, 3 * cm, 3 * cm, 1.8 * cm, 2.2 * cm])]
    story += [Paragraph("Restrições consideradas", H2)] + [Paragraph("• " + c, BODY) for c in run.constraints or []]
    story += [Paragraph("Premissas", H2)] + [Paragraph("• " + c, BODY) for c in run.assumptions or []]
    story += [Paragraph("Área e rede consideradas", H2), Paragraph(
        f"Demanda: nível {req['demand']['level']}, UFs {', '.join(req['demand'].get('ufs') or ['Brasil'])}. "
        f"Candidatos: {req['candidates']['type']}. Modo {req['mode']}, métrica {req['metric']}.", BODY)]
    story += _sources_section(db, ["ibge_logistica_2014", "ibge_censo2022_pop", "ibge_malhas"])
    k = res.get("kpis")
    if k:
        story += [Paragraph("Resultados", H2), _table([["Indicador", "Valor"]] + [[a, b] for a, b in k.items()], [8 * cm, 5 * cm])]
        fig, ax = plt.subplots(figsize=(8, 7))
        _states_outline(db, ax)
        fac = {f["key"]: f for f in res["open_facilities"]}
        for d in res["demand"]:
            f = fac.get(d["facility"]) if d.get("facility") else None
            if f:
                ax.plot([d["lon"], f["lon"]], [d["lat"], f["lat"]], color="#94a3b8", lw=0.4)
        ax.scatter([d["lon"] for d in res["demand"]], [d["lat"] for d in res["demand"]],
                   s=[max(3, d["demand_t"] / max(x["demand_t"] for x in res["demand"]) * 120) for d in res["demand"]],
                   c=["#f59e0b" if d["unmet_t"] > 1e-6 else "#64748b" for d in res["demand"]], alpha=0.7)
        ax.scatter([f["lon"] for f in fac.values()], [f["lat"] for f in fac.values()], s=90, c="#0e7490", marker="s", edgecolors="white")
        xs = [d["lon"] for d in res["demand"]] + [f["lon"] for f in fac.values()]
        ys = [d["lat"] for d in res["demand"]] + [f["lat"] for f in fac.values()]
        ax.set_xlim(min(xs) - 1, max(xs) + 1)
        ax.set_ylim(min(ys) - 1, max(ys) + 1)
        ax.set_title("Instalações abertas (quadrados), demanda (círculos; laranja = não atendida) e atribuições (esquemáticas)", fontsize=8)
        story.append(KeepTogether([Paragraph("Mapa", H2), _fig_to_image(fig, 13)]))
        rows = [["Instalação", "UF", "Capacidade (t/ano)", "Origem da capacidade", "Carga (t/ano)", "Utilização"]]
        for f in res["open_facilities"]:
            rows.append([f["name"], f["uf"], f["capacity_t"], f["capacity_source"], f["load_t"], f"{(f['utilization'] or 0) * 100:.1f}%"])
        story += [Paragraph("Instalações selecionadas", H2), _table(rows, [5 * cm, 1 * cm, 2.6 * cm, 3.5 * cm, 2.6 * cm, 2 * cm])]
    if res.get("points"):
        pts = res["points"]
        fig, ax = plt.subplots(figsize=(7, 4))
        for model, mk in (("p_median", "o"), ("max_coverage", "s")):
            sel = [p for p in pts if p["model"] == model]
            ax.scatter([p["transport_cost"] / 1e6 for p in sel], [p["coverage_share"] * 100 for p in sel], marker=mk,
                       c=["#94a3b8" if p["dominated"] else "#0e7490" for p in sel], label=model)
            for p in sel:
                ax.annotate(f"p={p['p']}", (p["transport_cost"] / 1e6, p["coverage_share"] * 100), fontsize=6)
        ax.set_xlabel("Custo de transporte (R$ milhões/ano)")
        ax.set_ylabel(f"Cobertura (% demanda ≤ {res['coverage_km']:.0f} km)")
        ax.legend(fontsize=7)
        story += [Paragraph("Fronteira custo × cobertura", H2), _fig_to_image(fig, 14)]
        rows = [["p", "Modelo", "Custo (R$)", "Cobertura", "Não dominada", "Instalações"]]
        for p in pts:
            rows.append([p["p"], p["model"], p["transport_cost"], f"{p['coverage_share'] * 100:.1f}%", "sim" if not p["dominated"] else "não",
                         ", ".join(p["open_names"][:6])])
        story.append(_table(rows, [0.8 * cm, 2.3 * cm, 2.8 * cm, 1.8 * cm, 1.8 * cm, 7.5 * cm]))
    if res.get("routes"):
        rows = [["Veículo", "Km", "Carga", "Sequência"]]
        for r in res["routes"]:
            rows.append([r["vehicle"], r["km"], r["load"], " → ".join(s["name"] for s in r["stops"])])
        story += [Paragraph("Rotas", H2), _table(rows, [1.6 * cm, 1.6 * cm, 1.6 * cm, 12 * cm])]
    story += [Paragraph("Limitações", H2)] + [Paragraph("• " + t, BODY) for t in (
        "A solução é ótima apenas para o modelo formulado e as premissas informadas; mudanças de premissa alteram o resultado.",
        "Linhas de atribuição no mapa são esquemáticas; o custo é calculado pela rota na rede.",
        "Demanda baseada em população (proxy) e capacidades padrão quando a fonte não informa.",
    )]
    story += [Paragraph("Recomendações derivadas dos cálculos", H2)]
    if k:
        story.append(Paragraph(
            f"• Configuração com {k['facilities_open']} instalações atende {k['service_level'] * 100:.1f}% da demanda, custo de "
            f"transporte de R$ {k['transport_cost']:,.0f}/ano e distância média ponderada de {k['weighted_avg_km']:.0f} km.", BODY))
        full = [f["name"] for f in res["open_facilities"] if (f.get("utilization") or 0) >= 0.999]
        if full:
            story.append(Paragraph(f"• Instalações no limite da capacidade: {', '.join(full[:6])}.", BODY))
    if res.get("points"):
        eff = [p for p in res["points"] if not p["dominated"]]
        story.append(Paragraph(f"• {len(eff)} configurações não dominadas; escolha conforme o peso dado a custo e cobertura.", BODY))
    return _doc(f"Otimização #{run.id}", story)


# ------------------------------------------------------------------------------------------- território
def territory_report(db: Session, indicators: dict[str, Any], coverage: dict[str, Any] | None) -> bytes:
    items = indicators["items"]
    story: list[Any] = [Paragraph("Relatório territorial — infraestrutura logística", H1),
                        Paragraph(f"Nível: {indicators['level']} · filtros: {indicators['filters']}", SMALL),
                        Paragraph("Objetivo da análise", H2),
                        Paragraph("Descrever a distribuição espacial da infraestrutura logística e a cobertura pela rede, "
                                  "com denominadores, períodos e fontes explícitos.", BODY)]
    story += _sources_section(db, ["ibge_logistica_2014", "ibge_censo2022_pop", "ibge_pib_municipal", "ibge_malhas"])
    m = indicators["metrics"]
    rows = [["Indicador", "Definição", "Unidade", "Período", "Denominador"]]
    for k in ("facilities_per_100k", "facilities_per_10k_km2", "road_density", "road_paved_share", "storage_t_per_capita"):
        rows.append([m[k]["label"], m[k]["definition"], m[k]["unit"], m[k]["period"], m[k].get("denominator", "—")])
    story += [Paragraph("Definições", H2), _table(rows, [3.5 * cm, 6 * cm, 2.2 * cm, 2.6 * cm, 2.7 * cm])]
    rows = [["Unidade", "População", "Instalações", "Inst./100 mil hab.", "Rodovias (km)", "% pavim.", "Ferrovias (km)"]]
    for r in items[:40]:
        rows.append([r["name"], r["population"], r["facilities"], r["facilities_per_100k"], r["road_km"], r["road_paved_share"], r["rail_km"]])
    story += [Paragraph("Indicadores", H2), _table(rows, [4.6 * cm, 2.2 * cm, 1.8 * cm, 2.2 * cm, 2.2 * cm, 1.6 * cm, 2.2 * cm])]
    c = indicators.get("concentration") or {}
    if c:
        story.append(Paragraph(f"Concentração: HHI {c['hhi']}, top-5 = {c['top5_share'] * 100:.1f}%, Gini {c['gini']}. {c['definition']}", BODY))
    top = items[:15]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.bar([r["name"][:12] for r in top], [r["facilities_per_100k"] or 0 for r in top], color="#0e7490")
    ax.set_ylabel("Instalações por 100 mil hab.")
    ax.tick_params(axis="x", labelsize=6, rotation=60)
    story.append(_fig_to_image(fig, 15))
    if coverage:
        rows = [["Classe", "Unidades", "População", "% pop."]]
        for k, v in coverage["summary"].items():
            rows.append([k, v["units"], v["population"], f"{v['population_share'] * 100:.1f}%"])
        story += [Paragraph("Cobertura pela rede", H2), Paragraph(coverage["method"], BODY), _table(rows, [6 * cm, 2.5 * cm, 3.5 * cm, 2.5 * cm])]
        low = [i for i in coverage["items"] if i["class"] == "baixa_cobertura_relativa"][:15]
        if low:
            rows = [["Região imediata", "UF", "População", "QL", "% pop. no limiar", "Km médio"]]
            for i in low:
                rows.append([i["name"], i["uf"], i["population"], i["location_quotient"], f"{(i['share_within_threshold'] or 0) * 100:.0f}%", i["avg_network_km"]])
            story += [Paragraph("Regiões com baixa cobertura relativa", H2), _table(rows, [5 * cm, 1.2 * cm, 2.6 * cm, 1.6 * cm, 3 * cm, 2.2 * cm])]
    story += [Paragraph("Limitações", H2)] + [Paragraph("• " + t, BODY) for t in (
        "Instalações e malha de 2014; população de 2022: períodos distintos entre numerador e denominador.",
        "Armazéns são registros agregados por município; não há base pública nacional de CDs privados.",
        "Baixa cobertura relativa considera população, oferta relativa, distância na rede e conectividade; "
        "não é um diagnóstico de atendimento real de mercado.",
    )]
    return _doc("Relatório territorial", story)

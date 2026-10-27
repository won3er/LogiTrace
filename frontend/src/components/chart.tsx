"use client";

import * as echarts from "echarts";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

const THEME = {
  color: ["#22d3ee", "#f59e0b", "#a78bfa", "#34d399", "#f472b6", "#38bdf8", "#facc15", "#fb7185"],
  backgroundColor: "transparent",
  textStyle: { color: "#cbd5e1", fontFamily: "var(--font-sans), system-ui, sans-serif" },
  grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
  categoryAxis: { axisLine: { lineStyle: { color: "#334155" } }, axisLabel: { color: "#94a3b8" }, splitLine: { show: false } },
  valueAxis: { axisLine: { lineStyle: { color: "#334155" } }, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
  legend: { textStyle: { color: "#cbd5e1" } },
  tooltip: { backgroundColor: "#0f172a", borderColor: "#334155", textStyle: { color: "#e2e8f0" } },
};
echarts.registerTheme("logitrace", THEME);

export function Chart({ option, className, height = 260 }: { option: echarts.EChartsOption; className?: string; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    inst.current = echarts.init(ref.current, "logitrace", { renderer: "canvas" });
    const ro = new ResizeObserver(() => inst.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      inst.current?.dispose();
    };
  }, []);

  useEffect(() => {
    inst.current?.setOption(option, true);
  }, [option]);

  return <div ref={ref} className={cn("w-full min-w-0 overflow-hidden", className)} style={{ height }} />;
}

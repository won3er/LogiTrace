"use client";

import {
  BarChart3,
  Database,
  FlaskConical,
  Layers,
  Map as MapIcon,
  Network,
  Route,
  Sigma,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { GlobalSearch } from "@/components/global-search";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Mapa nacional", icon: MapIcon },
  { href: "/explorador", label: "Explorador de infraestrutura", icon: Layers },
  { href: "/territorio", label: "Inteligência territorial", icon: Sigma },
  { href: "/rede", label: "Motor de redes", icon: Network },
  { href: "/cenarios", label: "Simulador de cenários", icon: FlaskConical },
  { href: "/otimizacao", label: "Otimização logística", icon: Route },
  { href: "/fluxos", label: "Fluxos de mercadorias", icon: Waypoints },
  { href: "/painel", label: "Painel analítico", icon: BarChart3 },
  { href: "/dados", label: "Fontes, dados e premissas", icon: Database },
];

const SHORT: Record<string, string> = {
  "/": "Mapa", "/explorador": "Explorar", "/territorio": "Território", "/rede": "Redes", "/cenarios": "Cenários",
  "/otimizacao": "Otimizar", "/fluxos": "Fluxos", "/painel": "Painel", "/dados": "Dados",
};

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const current = NAV.find((n) => (n.href === "/" ? path === "/" : path.startsWith(n.href)));
  return (
    <div className="flex h-dvh">
      <nav className="hidden w-14 shrink-0 flex-col items-center gap-1 border-r border-sidebar-border bg-sidebar py-3 md:flex">
        <Link href="/" className="mb-3 grid size-9 place-items-center rounded-lg bg-primary/15 text-primary" aria-label="LogiTrace">
          <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="5" cy="18" r="2" />
            <circle cx="19" cy="6" r="2" />
            <circle cx="12" cy="12" r="2" />
            <path d="M6.5 16.5 10.5 13.5M13.5 10.5l4-3" />
          </svg>
        </Link>
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = current?.href === href;
          return (
            <Tooltip key={href}>
              <TooltipTrigger
                render={
                  <Link
                    href={href}
                    aria-label={label}
                    className={cn(
                      "grid size-9 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground",
                      active && "bg-sidebar-accent text-primary",
                    )}
                  />
                }
              >
                <Icon className="size-[18px]" />
              </TooltipTrigger>
              <TooltipContent side="right">{label}</TooltipContent>
            </Tooltip>
          );
        })}
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="relative z-30 flex h-12 shrink-0 items-center gap-3 border-b border-border bg-background/80 px-3 backdrop-blur sm:gap-4 sm:px-4">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="text-sm font-semibold tracking-tight">LogiTrace</span>
            <span className="hidden truncate text-xs text-muted-foreground sm:inline">{current?.label}</span>
          </div>
          <div className="ml-auto min-w-0 flex-1 sm:max-w-md">
            <GlobalSearch />
          </div>
        </header>
        <main className="relative min-h-0 flex-1 overflow-auto">{children}</main>
        {/* Navegação inferior em telas pequenas */}
        <nav className="flex h-14 shrink-0 items-stretch overflow-x-auto border-t border-sidebar-border bg-sidebar md:hidden" aria-label="Navegação principal">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = current?.href === href;
            return (
              <Link
                key={href}
                href={href}
                aria-label={label}
                className={cn(
                  "flex min-w-14 flex-1 flex-col items-center justify-center gap-0.5 px-1 text-[10px] text-muted-foreground",
                  active && "text-primary",
                )}
              >
                <Icon className="size-[18px]" />
                <span className="max-w-16 truncate">{SHORT[href]}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}

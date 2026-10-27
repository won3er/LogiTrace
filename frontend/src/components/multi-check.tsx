"use client";

import { ChevronDown } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type Option = { value: string; label: string; count?: number; color?: string };

/** Seleção múltipla compacta (filtros combinados). */
export function MultiCheck({
  label, options, value, onChange, className, testId,
}: {
  label: string;
  options: Option[];
  value: string[];
  onChange: (v: string[]) => void;
  className?: string;
  testId?: string;
}) {
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <Popover>
      <PopoverTrigger
        render={
          <button
            data-testid={testId}
            className={cn(
              "flex h-8 items-center gap-1.5 rounded-lg border border-input bg-input/30 px-2.5 text-sm hover:bg-input/50",
              value.length && "border-primary/50 text-primary",
              className,
            )}
          />
        }
      >
        {label}
        {value.length > 0 && <span className="rounded bg-primary/20 px-1 text-xs tabular">{value.length}</span>}
        <ChevronDown className="size-3.5 opacity-60" />
      </PopoverTrigger>
      <PopoverContent className="max-h-80 w-64 overflow-auto p-1.5" align="start">
        <div className="mb-1 flex justify-between px-1.5 text-xs">
          <button className="text-muted-foreground hover:text-foreground" onClick={() => onChange(options.map((o) => o.value))}>
            Todos
          </button>
          <button className="text-muted-foreground hover:text-foreground" onClick={() => onChange([])}>
            Limpar
          </button>
        </div>
        {options.map((o) => (
          <label key={o.value} className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-accent">
            <Checkbox checked={value.includes(o.value)} onCheckedChange={() => toggle(o.value)} />
            {o.color && <span className="size-2.5 rounded-full" style={{ background: o.color }} />}
            <span className="truncate">{o.label}</span>
            {o.count !== undefined && <span className="ml-auto text-xs text-muted-foreground tabular">{o.count}</span>}
          </label>
        ))}
      </PopoverContent>
    </Popover>
  );
}

import { z } from "zod";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function qs(params: Query = {}): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/**
 * Chamada à API do LogiTrace. Quando um schema zod é informado, a resposta é validada:
 * um contrato quebrado vira erro explícito em vez de dado silenciosamente incorreto na tela.
 */
export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Query; schema?: z.ZodType<T>; signal?: AbortSignal } = {},
): Promise<T> {
  const res = await fetch(`/api${path}${qs(opts.query)}`, {
    method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
    headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    throw new ApiError(res.status, `Resposta inválida do servidor (${res.status})`);
  }
  if (!res.ok) {
    const err = (data as { error?: { message?: string; details?: unknown } })?.error;
    throw new ApiError(res.status, err?.message ?? `Erro ${res.status}`, err?.details);
  }
  if (opts.schema) {
    const parsed = opts.schema.safeParse(data);
    if (!parsed.success) {
      console.error("Contrato da API divergente", path, parsed.error.issues);
      throw new ApiError(500, `Contrato da API divergente em ${path}`);
    }
    return parsed.data;
  }
  return data as T;
}

export const downloadUrl = (path: string, query?: Query) => `/api${path}${qs(query)}`;

export async function uploadFile<T>(path: string, file: File, query?: Query): Promise<T> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`/api${path}${qs(query)}`, { method: "POST", body: fd });
  const data = await res.json();
  if (!res.ok) throw new ApiError(res.status, data?.error?.message ?? `Erro ${res.status}`);
  return data as T;
}

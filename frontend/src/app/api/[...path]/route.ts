/**
 * Proxy do site para a API FastAPI.
 * O navegador só conversa com este domínio; a URL interna da API e a chave compartilhada
 * (LOGITRACE_INTERNAL_API_SECRET) ficam apenas no servidor.
 */
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 300; // otimizações e cenários rodam dentro da requisição na API serverless

const API_URL = (process.env.API_INTERNAL_URL ?? process.env.LOGITRACE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const SECRET = process.env.LOGITRACE_INTERNAL_API_SECRET ?? "";
const FORWARD_REQUEST = ["content-type", "accept"];
// content-encoding não é repassado: o fetch do servidor já entrega o corpo descompactado
const FORWARD_RESPONSE = ["content-type", "content-disposition", "cache-control", "x-response-time-ms"];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${API_URL}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  for (const h of FORWARD_REQUEST) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  if (SECRET) headers.set("x-logitrace-key", SECRET);
  const hasBody = !["GET", "HEAD"].includes(req.method);
  let res: Response;
  try {
    res = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return Response.json(
      { error: { status: 502, message: "API indisponível no momento. Tente novamente em alguns segundos." } },
      { status: 502 },
    );
  }
  const out = new Headers();
  for (const h of FORWARD_RESPONSE) {
    const v = res.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(res.body, { status: res.status, headers: out });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;

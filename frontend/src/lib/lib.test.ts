import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, qs } from "./api";
import { fmt, fmtPct, fmtSigned, hours } from "./format";
import { quantileScale, SEQ } from "./scale";
import { FacilitySchema, RouteResponseSchema } from "./types";

describe("formatação pt-BR", () => {
  it("usa separadores brasileiros e trata ausentes", () => {
    expect(fmt(1234567.891, 1)).toBe("1.234.567,9");
    expect(fmt(null)).toBe("—");
    expect(fmtPct(0.1234)).toBe("12,3%");
    expect(fmtSigned(2.5, 1, "km")).toBe("+2,5 km");
    expect(hours(1.5)).toBe("1 h 30 min");
  });
});

describe("escala por quantis", () => {
  it("distribui valores entre as classes e marca ausentes", () => {
    const s = quantileScale([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect(s.breaks).toHaveLength(SEQ.length - 1);
    expect(s.color(1)).toBe(SEQ[0]);
    expect(s.color(12)).toBe(SEQ[SEQ.length - 1]);
    expect(s.color(null)).toBe("#1e293b");
  });
});

describe("cliente da API", () => {
  afterEach(() => vi.restoreAllMocks());

  it("serializa listas como parâmetros repetidos e ignora vazios", () => {
    expect(qs({ uf: ["SP", "MG"], q: "", page: 2, x: undefined })).toBe("?uf=SP&uf=MG&page=2");
  });

  it("propaga a mensagem de erro do contrato {error:{message}}", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: { status: 404, message: "Instalação não encontrada" } }), { status: 404 }));
    await expect(api("/facilities/1")).rejects.toMatchObject({ status: 404, message: "Instalação não encontrada" });
  });

  it("rejeita respostas fora do contrato tipado", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ connected: "sim" }), { status: 200 }));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const err = await api("/network/route", { body: {}, schema: RouteResponseSchema }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toContain("Contrato da API divergente");
  });
});

describe("schemas", () => {
  it("aceita uma instalação oficial válida e rejeita classe de registro desconhecida", () => {
    const f = {
      id: 1, external_id: "porto:1", record_class: "official", name: "Porto", category: "porto", category_label: "Porto",
      subcategory: null, modal: "aquaviario", operator: null, capacity_value: null, capacity_unit: null, status: null, address: null,
      municipality_code: 3548500, municipality_name: "Santos", uf: "SP", lon: -46.3, lat: -23.9, reliability: "média",
      limitations: null, source_key: "ibge", source_name: "IBGE", source_reference: "2014", attributes: {}, updated_at: "2026-01-01",
    };
    expect(FacilitySchema.safeParse(f).success).toBe(true);
    expect(FacilitySchema.safeParse({ ...f, record_class: "inventado" }).success).toBe(false);
  });
});

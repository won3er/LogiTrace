import { expect, test, type Page } from "@playwright/test";

async function pickMunicipality(page: Page, testId: string, query: string, label: RegExp) {
  await page.getByTestId(testId).fill(query);
  await page.getByRole("button", { name: label }).first().click();
}

test("mapa nacional carrega camadas, busca global abre detalhes com proveniência", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("map").locator("canvas").first()).toBeVisible();
  await expect(page.getByTestId("legend")).toContainText("Ferrovia");
  await page.getByTestId("layer-rail").click();
  await expect(page.getByTestId("legend")).not.toContainText("Ferrovia");

  await page.getByLabel("Busca global").fill("Porto de Santos");
  await page.getByRole("button", { name: /^Porto de Santos/ }).click();
  const details = page.getByTestId("entity-details");
  await expect(details).toContainText("Porto de Santos");
  await expect(details).toContainText("Logística dos Transportes no Brasil 2014");
  await expect(details).toContainText("Limitações");
});

test("explorador filtra por categoria e sincroniza contagem e exportação", async ({ page }) => {
  await page.goto("/explorador");
  await expect(page.getByTestId("explorer-total")).toContainText("registros");
  await page.getByTestId("filter-category").click();
  await page.getByRole("checkbox").first().waitFor();
  await page.getByText("Portos públicos", { exact: false }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("explorer-total")).toHaveText("61 registros");
  await expect(page.getByRole("link", { name: "CSV" })).toHaveAttribute("href", /category=porto/);
  await page.getByTestId("explorer-table").locator("tbody tr").first().click();
  await expect(page.getByTestId("entity-details")).toContainText("Porto");
});

test("motor de redes calcula rota e alternativas com distância maior que a linha reta", async ({ page }) => {
  await page.goto("/rede");
  await pickMunicipality(page, "route-origin", "Campinas", /Campinas\/SP/);
  await pickMunicipality(page, "route-dest", "Belo Horizonte", /Belo Horizonte\/MG/);
  await page.getByTestId("calc-route").click();
  const res = page.getByTestId("route-results");
  await expect(res).toContainText("Melhor rota");
  await expect(res).toContainText("Alternativa 1");
  await expect(res).toContainText("linha reta");
});

test("cenário: cria a partir de modelo, altera custo, executa e reproduz", async ({ page }) => {
  await page.goto("/cenarios");
  await page.getByTestId("new-costs").click();
  await page.waitForURL(/\/cenarios\/\d+/);
  await page.locator("select").filter({ hasText: "Custo / velocidade" }).selectOption("cost");
  await page.locator('input[placeholder="0.2"]').fill("0.3");
  await page.getByRole("button", { name: "Adicionar", exact: true }).click();
  await expect(page.getByTestId("change-item")).toHaveCount(1);
  await page.getByTestId("run-scenario").click();
  const results = page.getByTestId("scenario-results");
  await expect(results).toContainText("Pares OD afetados", { timeout: 90_000 });
  await expect(results).toContainText("351");
  await page.getByTestId("rerun").click();
  await expect(results).toContainText("reproduzida: resultado idêntico", { timeout: 90_000 });
  await expect(page.getByTestId("scenario-pdf")).toHaveAttribute("href", /reports\/scenario-runs\/\d+\.pdf/);
});

test("otimização p-mediana retorna solução ótima comprovada", async ({ page }) => {
  await page.goto("/otimizacao");
  await page.getByTestId("p").fill("3");
  await page.getByTestId("run-opt").click();
  await expect(page.getByTestId("quality")).toHaveText("Ótimo comprovado", { timeout: 90_000 });
  await expect(page.getByTestId("opt-results")).toContainText("Demanda atendida");
});

test("painel mostra indicadores com metadados", async ({ page }) => {
  await page.goto("/painel");
  await expect(page.getByTestId("metric-road_km")).toContainText("km");
  await expect(page.getByTestId("metric-avg_capital_km")).toContainText("Cálculo LogiTrace");
});

test.describe("responsividade", () => {
  for (const [name, size] of [["celular", { width: 375, height: 812 }], ["tablet", { width: 768, height: 1024 }]] as const) {
    test(`${name}: nenhuma tela estoura horizontalmente`, async ({ page }) => {
      await page.setViewportSize(size);
      for (const path of ["/", "/explorador", "/territorio", "/rede", "/cenarios", "/otimizacao", "/fluxos", "/painel", "/dados"]) {
        await page.goto(path);
        await page.locator("main").first().waitFor();
        await page.waitForTimeout(1500);
        const docW = await page.evaluate(() => document.documentElement.scrollWidth);
        expect(docW, `${path} em ${size.width}px`).toBeLessThanOrEqual(size.width);
      }
    });
  }

  test("celular: navegação inferior e painel de camadas não cobrem a legenda", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Navegação principal" })).toBeVisible();
    await page.getByTestId("expand-layers").click();
    const panel = await page.getByTestId("collapse-layers").locator("xpath=ancestor::section").boundingBox();
    const legend = await page.getByTestId("legend").boundingBox();
    expect(panel!.y + panel!.height).toBeLessThanOrEqual(legend!.y);
  });

  test("desktop: painel de camadas termina acima da legenda com muitas camadas ativas", async ({ page }) => {
    await page.goto("/");
    for (const k of ["corridors", "poles", "flows"]) await page.getByTestId(`layer-${k}`).click();
    const panel = await page.getByTestId("collapse-layers").locator("xpath=ancestor::section").boundingBox();
    const legend = await page.getByTestId("legend").boundingBox();
    expect(panel!.y + panel!.height).toBeLessThanOrEqual(legend!.y);
  });
});

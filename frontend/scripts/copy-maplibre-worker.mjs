// Copia o worker do MapLibre 6 para /public: o bundler não empacota o worker ESM separado.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
mkdirSync(join(root, "public"), { recursive: true });
copyFileSync(join(root, "node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs"), join(root, "public/maplibre-gl-worker.mjs"));
console.log("maplibre-gl-worker.mjs copiado para public/");

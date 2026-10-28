import type { NextConfig } from "next";

// /api/* é repassado à API FastAPI pela rota src/app/api/[...path]/route.ts
// (API_INTERNAL_URL e a chave interna ficam só no servidor).
const nextConfig: NextConfig = {
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;

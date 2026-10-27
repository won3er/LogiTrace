import type { NextConfig } from "next";

// A API FastAPI é acessada pelo mesmo domínio (/api/*): sem CORS no navegador e sem expor a URL interna.
const API_URL = process.env.LOGITRACE_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  // relatórios PDF e exportações grandes podem levar mais que o tempo padrão do proxy
  experimental: { proxyTimeout: 300_000, proxyClientMaxBodySize: "12mb" },
};

export default nextConfig;

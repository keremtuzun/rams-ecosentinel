import type { NextConfig } from "next";
const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  outputFileTracingIncludes: {
    "/api/*": [
      "./public/evidence/catalog.json",
      "./public/evidence/jobs/*/score.tif",
    ],
    "/health": ["./public/evidence/catalog.json"],
  },
};
export default config;

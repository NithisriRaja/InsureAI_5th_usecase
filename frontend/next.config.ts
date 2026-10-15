import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A stray lockfile higher up (e.g. in the home dir) would otherwise be picked as the root.
  outputFileTracingRoot: path.join(__dirname),
  turbopack: { root: path.join(__dirname) },
  // Hide the Next.js developer button ("N") that sits over the sidebar in `npm run dev`.
  devIndicators: false,
};

export default nextConfig;

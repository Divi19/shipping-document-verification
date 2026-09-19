import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@sdoc/contracts"],
};

export default nextConfig;

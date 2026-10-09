import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "SophIA — sua assistente financeira",
    short_name: "SophIA",
    description: "Sua assistente financeira pessoal e privada.",
    start_url: "/",
    display: "standalone",
    background_color: "#f4f4ef",
    theme_color: "#0d3838",
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }],
  };
}

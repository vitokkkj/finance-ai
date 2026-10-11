import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "SophIA — sua assistente financeira",
    short_name: "SophIA",
    description: "Sua assistente financeira pessoal e privada.",
    start_url: "/",
    display: "standalone",
    background_color: "#f5f3eb",
    theme_color: "#173b2c",
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }],
  };
}

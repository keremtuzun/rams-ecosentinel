import type { Metadata } from "next";
import "./styles.css";
import "maplibre-gl/dist/maplibre-gl.css";

export const metadata: Metadata = {
  title: "RAMS EcoSentinel · Doğadaki değişimi gör",
  description:
    "Bölgeni seç, uydu görüntülerini karşılaştır, doğadaki değişimi gör. FRC Team 7729 RAMs.",
  icons: { icon: "/brand/rams-7729.png", apple: "/brand/rams-7729.png" },
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}

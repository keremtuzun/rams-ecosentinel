import type { Metadata } from "next";
import "./styles.css";
import "maplibre-gl/dist/maplibre-gl.css";

export const metadata: Metadata = {
  title: "RAMS EcoSentinel · Doğadaki değişimi gör",
  description:
    "Bölgeni seç, uydu görüntülerini karşılaştır, doğadaki değişimi gör. FRC Team 7729 RAMs.",
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

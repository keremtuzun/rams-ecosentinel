export async function GET(request: Request) {
  const name = new URL(request.url).searchParams.get("q")?.trim() || "";
  if (name.length < 2 || name.length > 80)
    return Response.json({ detail: "En az iki harf yazın" }, { status: 422 });
  const destination = new URL("https://geocoding-api.open-meteo.com/v1/search");
  destination.search = new URLSearchParams({
    name,
    count: "6",
    language: "tr",
    countryCode: "TR",
  }).toString();
  try {
    const response = await fetch(destination, {
      signal: AbortSignal.timeout(10000),
      redirect: "error",
      next: { revalidate: 86400 },
    });
    if (!response.ok) throw new Error("geocoding_unavailable");
    const data = await response.json();
    return Response.json({
      places: (data.results || [])
        .filter(
          (p: { country_code: string; latitude: number; longitude: number }) =>
            p.country_code === "TR" &&
            Number.isFinite(p.latitude) &&
            Number.isFinite(p.longitude),
        )
        .map(
          (p: {
            id: number;
            name: string;
            admin1?: string;
            latitude: number;
            longitude: number;
          }) => ({
            id: p.id,
            name: p.name,
            admin1: p.admin1,
            latitude: p.latitude,
            longitude: p.longitude,
          }),
        ),
      source: "Open-Meteo / GeoNames",
    });
  } catch {
    console.error(JSON.stringify({ event: "place_search_unavailable" }));
    return Response.json(
      {
        detail:
          "Yer araması şu anda kullanılamıyor. Haritadan alan çizebilirsiniz.",
      },
      { status: 503 },
    );
  }
}

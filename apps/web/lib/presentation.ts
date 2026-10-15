import type { Geometry, Job, Region, Source } from "./api";
export function regionName(id: string) {
  return (
    (
      {
        marmaris: "Marmaris",
        milas: "Milas",
        manavgat: "Manavgat",
        izmir: "İzmir",
      } as Record<string, string>
    )[id] || "Seçili alan"
  );
}
export function searchText(value: string) {
  return value
    .toLocaleLowerCase("tr-TR")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/ı/g, "i");
}
export function jobRegion(job: Job, regions: Region[]) {
  const ring = (job.request.geometry as Geometry | undefined)?.coordinates?.[0];
  if (!ring?.length) return undefined;
  const lon =
    (Math.min(...ring.map((p) => p[0])) + Math.max(...ring.map((p) => p[0]))) /
    2;
  const lat =
    (Math.min(...ring.map((p) => p[1])) + Math.max(...ring.map((p) => p[1]))) /
    2;
  return regions.find(
    (r) =>
      lon >= r.bbox[0] &&
      lon <= r.bbox[2] &&
      lat >= r.bbox[1] &&
      lat <= r.bbox[3],
  );
}
export function dateLabel(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString("tr-TR", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      });
}
export function observationDateLabel(source: Source) {
  const range = source.acquisition_range;
  return range?.length === 2 && range[0].slice(0, 10) !== range[1].slice(0, 10)
    ? `${dateLabel(range[0])} – ${dateLabel(range[1])}`
    : dateLabel(source.acquired_at);
}
export function simpleError(message: string) {
  if (
    /valid, nonempty Polygon|Invalid GeoJSON|invalid.*polygon|self.intersect/i.test(
      message,
    )
  )
    return "Alan sınırı geçersiz. Çizgiler kesişmeden yeniden çizin veya Alan çiz ile dikdörtgen seçin.";
  if (/200 vertices/i.test(message))
    return "Alan çok fazla köşe içeriyor. Daha az köşeyle yeniden çizin.";
  if (/finite longitude\/latitude/i.test(message))
    return "Alan okunamadı. Haritadan yeniden çizin.";
  if (
    /[İıi]stek|Sunucu|Analiz kotası|İşlem kaydedildi|Sonuç bulunamadı|Yer araması/.test(
      message,
    )
  )
    return message;
  if (/Insufficient jointly clear/i.test(message))
    return "Bulut, su veya eksik görüntü nedeniyle yeterli veri yok. Alanı ya da tarihleri değiştirin.";
  if (/comparable seasons/i.test(message))
    return "Aynı mevsimden iki tarih seçin (en fazla 45 gün mevsim farkı).";
  if (/Türkiye|AOI area|bounding dimensions|processing limit/i.test(message))
    return "Türkiye içinde en fazla 50 km genişliğinde bir alan seçin (0,1–2.500 km²).";
  if (/at least two years/i.test(message))
    return "İki tarihi en az 2 yıl arayla seçin.";
  if (/must not overlap/i.test(message))
    return "Tarih aralıkları çakışıyor. Sonraki dönemin başlangıcını önceki dönemin sonundan sonraya alın.";
  if (/limited to 62 days/i.test(message))
    return "Her görüntü arama aralığı en fazla 62 gün olabilir.";
  if (/ten years/i.test(message))
    return "İki dönem arasındaki fark en fazla 10 yıl olabilir.";
  if (/Date ranges/i.test(message))
    return "2017 veya sonrasından, bugünü aşmayan tarihler seçin. Her aralıkta başlangıç bitişten sonra olamaz.";
  if (/time limit|timed out/i.test(message))
    return "İşlem süre sınırını aştı. Daha küçük bir alan veya başka tarihler seçin.";
  if (/No acceptable|No suitable|No scenes/i.test(message))
    return "Bu tarihlerde uygun uydu görüntüsü yok. Tarihleri değiştirip tekrar deneyin.";
  if (/outside analysis grid/i.test(message))
    return "Seçili alanın içine dokunun.";
  if (/FIRMS_MAP_KEY|thermal.*unavailable/i.test(message))
    return "Yangın gözlemleri şu anda kullanılamıyor.";
  if (/backend|inference.*require/i.test(message))
    return "Yeni analiz şu anda kullanılamıyor. Hazır sonuçları açabilirsiniz.";
  if (/Failed to fetch|unavailable|offline|fetch failed/i.test(message))
    return "Bağlantı kurulamadı. Biraz sonra tekrar deneyin.";
  return "İşlem tamamlanamadı. Seçiminizi kontrol edip tekrar deneyin.";
}
export const terms: Record<string, { label: string; meaning: string }> = {
  ndvi: {
    label: "Yeşillik",
    meaning: "NDVI · Bitki örtüsünün ne kadar yeşil göründüğü.",
  },
  ndmi: {
    label: "Bitki nemi",
    meaning: "NDMI · Bitki örtüsündeki nemin uydu göstergesi.",
  },
  nbr: {
    label: "Yanık izi göstergesi",
    meaning:
      "NBR · Yanık veya örtü değişimiyle ilişkili gösterge; tek başına yangın kanıtı değildir.",
  },
};

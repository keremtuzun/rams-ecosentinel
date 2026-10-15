"use client";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  API,
  api,
  rectangle,
  type Geometry,
  type Job,
  type Region,
} from "../lib/api";
import {
  dateLabel,
  observationDateLabel,
  jobRegion,
  regionName,
  searchText,
  simpleError,
  terms,
} from "../lib/presentation";
import Walkthrough, { TOUR_KEY } from "../components/Walkthrough";
import { geometryError } from "../lib/geometry";
import {
  comparisonWindows,
  comparisonDateError,
  shiftYear,
} from "../lib/dates";
const ResearchMap = dynamic(() => import("../components/ResearchMap"), {
  ssr: false,
  loading: () => <div className="map-placeholder">Harita yükleniyor…</div>,
});
const INITIAL = rectangle([28.22, 36.98, 28.35, 37.1]);
const number = (value: number, digits = 1) =>
  value.toLocaleString("tr-TR", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
const statusLabel: Record<string, string> = {
  queued: "Sırada",
  running: "İşleniyor",
  succeeded: "Hazır",
  failed: "Tamamlanamadı",
};
export default function Workspace() {
  const [regions, setRegions] = useState<Region[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [job, setJob] = useState<Job | null>(null);
  const [geometry, setGeometry] = useState<Geometry>(INITIAL),
    [selected, setSelected] = useState("marmaris");
  const [dates, setDates] = useState({
    before_start: "2020-06-01",
    before_end: "2020-06-30",
    after_start: "2022-06-01",
    after_end: "2022-06-30",
  });
  const [ready, setReady] = useState(false),
    [analysisAvailable, setAnalysisAvailable] = useState(false),
    [offline, setOffline] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [newAnalysis, setNewAnalysis] = useState(false),
    [search, setSearch] = useState("");
  const [draw, setDraw] = useState(false),
    [drawMode, setDrawMode] = useState<"polygon" | "rectangle">("rectangle");
  const [showChange, setShowChange] = useState(true),
    [showSource, setShowSource] = useState(true),
    [opacity, setOpacity] = useState(0.65);
  const [compare, setCompare] = useState(50),
    [inspection, setInspection] = useState("");
  const [fireData, setFireData] = useState<GeoJSON.FeatureCollection | null>(
    null,
  );
  const [catalog, setCatalog] = useState<{
    before: { id: string; acquired_at: string }[];
    after: { id: string; acquired_at: string }[];
  } | null>(null);
  const [tour, setTour] = useState(false);
  const [places, setPlaces] = useState<
    {
      id: number;
      name: string;
      admin1?: string;
      latitude: number;
      longitude: number;
    }[]
  >([]);
  const [locationName, setLocationName] = useState("");
  const selectionVersion = useRef(0);
  const active = busy || (!!job && ["queued", "running"].includes(job.status));
  const report = job?.report;
  const selectedName =
    selected === "custom" && locationName ? locationName : regionName(selected);
  function chooseDate(kind: "before" | "after", value: string) {
    setDates((previous) =>
      comparisonWindows(
        kind === "before" ? value : previous.before_end,
        kind === "after" ? value : previous.after_end,
      ),
    );
  }
  async function searchPlaces() {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ places: typeof places }>(
        `/api/places?q=${encodeURIComponent(search)}`,
      );
      setPlaces(result.places);
      if (!result.places.length)
        setNotice("Yer bulunamadı. Haritadan alan çizebilirsiniz.");
    } catch (e) {
      setError(simpleError((e as Error).message));
    } finally {
      setBusy(false);
    }
  }
  function choosePlace(place: (typeof places)[number]) {
    selectionVersion.current++;
    const lat = 0.0225,
      lon = 0.0225 / Math.cos((place.latitude * Math.PI) / 180);
    setGeometry(
      rectangle([
        place.longitude - lon,
        place.latitude - lat,
        place.longitude + lon,
        place.latitude + lat,
      ]),
    );
    setSelected("custom");
    setLocationName(place.name);
    setJob(null);
    setInspection("");
    setFireData(null);
    setNewAnalysis(true);
    setSearch("");
    setPlaces([]);
    setNotice("Yaklaşık 5 × 5 km seçildi. İstersen alanı haritada değiştir.");
  }
  function applyJob(next: Job, allRegions: Region[]) {
    setJob(next);
    setLocationName(
      typeof next.request.display_name === "string"
        ? next.request.display_name
        : "",
    );
    setSelected(jobRegion(next, allRegions)?.id || "custom");
    if (next.report?.geometry) setGeometry(next.report.geometry);
    else if (next.request.geometry)
      setGeometry(next.request.geometry as Geometry);
    if (next.request.before_start)
      setDates({
        before_start: String(next.request.before_start),
        before_end: String(next.request.before_end),
        after_start: String(next.request.after_start),
        after_end: String(next.request.after_end),
      });
    setDraw(false);
    setNewAnalysis(false);
    setCatalog(null);
    setInspection("");
    setFireData(null);
    setCompare(50);
  }
  useEffect(() => {
    let mounted = true;
    const health = api<{ analysis_available?: boolean }>("/health")
      .then((h) => {
        if (mounted) setAnalysisAvailable(h.analysis_available !== false);
      })
      .catch(() => {
        if (mounted) setOffline(true);
      });
    const content = Promise.all([
      api<Region[]>("/api/regions"),
      api<Job[]>("/api/jobs"),
    ])
      .then(async ([r, list]) => {
        if (!mounted) return;
        setRegions(r);
        setJobs(list);
        const completed =
          list.find((j) => ["queued", "running"].includes(j.status)) ||
          list
            .filter((j) => j.status === "succeeded")
            .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
        if (completed) {
          const next = await api<Job>(`/api/jobs/${completed.id}`);
          if (mounted) applyJob(next, r);
        }
      })
      .catch((e) => {
        if (mounted) setError(simpleError(e.message));
      });
    Promise.all([health, content]).finally(() => {
      if (mounted) setReady(true);
    });
    return () => {
      mounted = false;
    };
  }, []);
  useEffect(() => {
    if (!ready) return;
    try {
      setTour(localStorage.getItem(TOUR_KEY) !== "done");
    } catch {
      setTour(true);
    }
  }, [ready]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let mounted = true;
    const timer = setInterval(
      () =>
        api<Job>(`/api/jobs/${job.id}`)
          .then((next) => {
            if (!mounted) return;
            setJob(next);
            if (next.status === "failed")
              setError(simpleError(next.error || "Analysis failed"));
            if (["failed", "succeeded"].includes(next.status))
              api<Job[]>("/api/jobs")
                .then((list) => {
                  if (mounted) setJobs(list);
                })
                .catch(() => {});
          })
          .catch((e) => {
            if (mounted) setError(simpleError(e.message));
          }),
      2000,
    );
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [job]);
  async function selectJob(id: string) {
    const version = ++selectionVersion.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next = await api<Job>(`/api/jobs/${id}`);
      if (version === selectionVersion.current) {
        applyJob(next, regions);
        if (window.matchMedia("(max-width: 720px)").matches)
          requestAnimationFrame(() =>
            document.querySelector(".main-workspace")?.scrollIntoView({
              block: "start",
              behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
                .matches
                ? "instant"
                : "smooth",
            }),
          );
      }
    } catch (e) {
      if (version === selectionVersion.current)
        setError(simpleError((e as Error).message));
    } finally {
      if (version === selectionVersion.current) setBusy(false);
    }
  }
  async function submit(region?: Region) {
    if (!analysisAvailable || active) return;
    if (!region && draw) {
      setError("Önce haritadaki alan çizimini bitirin veya Vazgeç’e dokunun.");
      return;
    }
    const footprint = region ? rectangle(region.bbox) : geometry;
    const boundaryError = geometryError(footprint);
    if (boundaryError) {
      setError(boundaryError);
      return;
    }
    if (!region) {
      const dateError = comparisonDateError(dates);
      if (dateError) {
        setError(dateError);
        return;
      }
    }
    selectionVersion.current++;
    setError("");
    setNotice("");
    setBusy(true);
    setInspection("");
    setFireData(null);
    setJob(null);
    const windows = region
      ? {
          before_start: region.before[0],
          before_end: region.before[1],
          after_start: region.after[0],
          after_end: region.after[1],
        }
      : dates;
    if (region) {
      setSelected(region.id);
      setGeometry(footprint);
      setDates(windows);
    }
    try {
      const created = await api<Job>("/api/jobs", {
        geometry: footprint,
        ...windows,
        module: "habitat",
        display_name: region ? regionName(region.id) : selectedName,
      });
      setJob(created);
      setJobs(await api<Job[]>("/api/jobs"));
    } catch (e) {
      setError(simpleError((e as Error).message));
    } finally {
      setBusy(false);
    }
  }
  function chooseRegion(region: Region) {
    const completed = jobs.find(
      (j) =>
        j.status === "succeeded" && jobRegion(j, regions)?.id === region.id,
    );
    if (completed) {
      void selectJob(completed.id);
      return;
    }
    if (analysisAvailable) {
      void submit(region);
      return;
    }
    selectionVersion.current++;
    setSelected(region.id);
    setGeometry(rectangle(region.bbox));
    setJob(null);
    setInspection("");
    setFireData(null);
    setError("");
    setBusy(false);
    setNotice(
      `${regionName(region.id)} için hazır sonuç yok. Yeni analiz şu anda kullanılamıyor.`,
    );
  }
  async function discover() {
    if (draw) {
      setError("Önce haritadaki alan çizimini bitirin veya Vazgeç’e dokunun.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      setCatalog(
        await api("/api/scenes", { geometry, ...dates, module: "habitat" }),
      );
    } catch (e) {
      setError(simpleError((e as Error).message));
    } finally {
      setBusy(false);
    }
  }
  async function observeFires() {
    setBusy(true);
    setError("");
    const ring = geometry.coordinates[0];
    const bbox = [
      Math.min(...ring.map((p) => p[0])),
      Math.min(...ring.map((p) => p[1])),
      Math.max(...ring.map((p) => p[0])),
      Math.max(...ring.map((p) => p[1])),
    ];
    try {
      setFireData(
        await api<GeoJSON.FeatureCollection>("/api/fire-observations", {
          bbox,
          days: 1,
        }),
      );
    } catch (e) {
      setError(simpleError((e as Error).message));
    } finally {
      setBusy(false);
    }
  }
  const onPoint = useCallback(
    async (lon: number, lat: number) => {
      if (!job?.report) return;
      const version = selectionVersion.current;
      try {
        const pixel = await api<{ score: number | null }>(
          `/api/jobs/${job.id}/inspect?longitude=${lon}&latitude=${lat}`,
        );
        if (version !== selectionVersion.current) return;
        setInspection(
          pixel.score === null
            ? "Bu nokta değerlendirilemedi (bulut, su veya alan dışında)."
            : `Bu noktada model puanı: ${number(pixel.score, 3)}. Yüksek değer daha çok inceleme gerektirir; kesin olasılık değildir.`,
        );
      } catch (e) {
        if (version === selectionVersion.current)
          setInspection(simpleError((e as Error).message));
      }
    },
    [job],
  );
  async function downloadExport(
    event: React.MouseEvent<HTMLAnchorElement>,
    format: string,
  ) {
    event.preventDefault();
    const href = event.currentTarget.href;
    try {
      const response = await fetch(href);
      if (!response.ok) throw new Error("Export unavailable");
      const content = await response.blob();
      const filename =
        response.headers
          .get("content-disposition")
          ?.match(/filename="?([^";]+)"?/)?.[1] || `analiz.${format}`;
      const url = URL.createObjectURL(content);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setError("Dosya indirilemedi. Tekrar deneyin.");
    }
  }
  const visibleRegions = [...regions]
    .sort(
      (a, b) =>
        Number(
          jobs.some(
            (j) =>
              j.status === "succeeded" && jobRegion(j, regions)?.id === b.id,
          ),
        ) -
        Number(
          jobs.some(
            (j) =>
              j.status === "succeeded" && jobRegion(j, regions)?.id === a.id,
          ),
        ),
    )
    .filter((r) =>
      searchText(regionName(r.id) + " " + r.id).includes(searchText(search)),
    );
  return (
    <>
      <div id="app-shell">
        <header className="topbar">
          <a className="brand" href="/" aria-label="RAMS EcoSentinel ana sayfa">
            <span className="brand-mark">R</span>
            <span>
              RAMS <b>EcoSentinel</b>
              <small>DOĞADAKİ DEĞİŞİMİ GÖR</small>
            </span>
          </a>
          <div className="header-meta">
            <span className="status-dot" data-offline={offline} />
            {offline
              ? "Bağlantı yok"
              : !ready
                ? "Bağlanıyor…"
                : analysisAvailable
                  ? "Analiz açık"
                  : "Hazır sonuçlar"}
          </div>
          <button className="help-button" onClick={() => setTour(true)}>
            ⓘ Rehber
          </button>
        </header>
        <div className="workspace">
          <aside className="sidebar">
            <section data-guide="regions" className="region-section">
              <span className="step-label">01 / BÖLGE</span>
              <h1>Nereye bakalım?</h1>
              <p className="intro">Bölgeye dokun, sonucu gör.</p>
              <label className="sr-only" htmlFor="region-search">
                Bölge ara
              </label>
              <input
                className="region-search"
                id="region-search"
                placeholder="Bölge ara…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {analysisAvailable && search.trim().length >= 2 && (
                <>
                  <button
                    className="secondary full"
                    disabled={active}
                    onClick={searchPlaces}
                  >
                    Haritada ara
                  </button>
                  <div className="place-results">
                    {places.map((place) => (
                      <button key={place.id} onClick={() => choosePlace(place)}>
                        {place.name}
                        <small>{place.admin1}</small>
                      </button>
                    ))}
                  </div>
                  {places.length > 0 && (
                    <small className="hint">
                      Yerler: Open-Meteo / GeoNames
                    </small>
                  )}
                </>
              )}
              <div className="region-list">
                {visibleRegions.map((r) => {
                  const completed = jobs.find(
                    (j) =>
                      j.status === "succeeded" &&
                      jobRegion(j, regions)?.id === r.id,
                  );
                  return (
                    <button
                      key={r.id}
                      className={
                        selected === r.id
                          ? "region-card selected"
                          : "region-card"
                      }
                      aria-label={`${regionName(r.id)} · ${completed ? "Sonucu aç" : analysisAvailable ? "Analiz et" : "Hazır sonuç yok"}`}
                      aria-pressed={selected === r.id}
                      disabled={active}
                      onClick={() => chooseRegion(r)}
                    >
                      <span className="region-symbol" aria-hidden="true">
                        {completed ? "◩" : "⌖"}
                      </span>
                      <span>
                        <strong>{regionName(r.id)}</strong>
                        <small>
                          {completed
                            ? "Sonucu aç"
                            : analysisAvailable
                              ? "Analiz et"
                              : "Hazır sonuç yok"}
                        </small>
                      </span>
                      <span className="region-arrow" aria-hidden="true">
                        ↗
                      </span>
                    </button>
                  );
                })}
              </div>
              {!ready && <p className="hint">Bölgeler yükleniyor…</p>}
              {ready && !visibleRegions.length && (
                <p className="hint">Bölge bulunamadı.</p>
              )}
            </section>
            {notice && (
              <p className="notice" role="status">
                {notice}
              </p>
            )}
            <details
              className="new-analysis"
              open={newAnalysis}
              onToggle={(e) => {
                const opened = e.currentTarget.open;
                setNewAnalysis(opened);
                if (opened && dates.after_end && comparisonDateError(dates))
                  setDates(
                    comparisonWindows(
                      shiftYear(dates.after_end, -2),
                      dates.after_end,
                    ),
                  );
              }}
            >
              <summary className={analysisAvailable ? "analysis-entry" : ""}>
                ＋ Yeni analiz yap
              </summary>
              {newAnalysis &&
                (!analysisAvailable ? (
                  <p className="hint">
                    Yeni analiz sunucusu bağlı değil. Yukarıdan hazır bir sonuç
                    açabilirsiniz.
                  </p>
                ) : (
                  <div className="analysis-form">
                    <p className="hint">
                      {selectedName} · Tarihleri seçip başlat.
                    </p>
                    <div className="draw-buttons">
                      <button
                        aria-pressed={draw && drawMode === "rectangle"}
                        onClick={() => {
                          setDrawMode("rectangle");
                          setDraw(!draw || drawMode !== "rectangle");
                        }}
                      >
                        ▱ Alan çiz
                      </button>
                      <button
                        aria-pressed={draw && drawMode === "polygon"}
                        onClick={() => {
                          setDrawMode("polygon");
                          setDraw(!draw || drawMode !== "polygon");
                        }}
                      >
                        ◇ Serbest çiz
                      </button>
                    </div>
                    <p className="hint">
                      Türkiye geneli · En fazla 50 km genişlikte alan.
                    </p>
                    <label className="single-date">
                      Önceki tarih
                      <input
                        type="date"
                        aria-label="Önceki tarih"
                        min="2017-01-01"
                        value={dates.before_end}
                        onChange={(e) => chooseDate("before", e.target.value)}
                      />
                    </label>
                    <label className="single-date">
                      Sonraki tarih
                      <input
                        type="date"
                        aria-label="Sonraki tarih"
                        min="2017-01-01"
                        value={dates.after_end}
                        onChange={(e) => chooseDate("after", e.target.value)}
                      />
                    </label>
                    <p className="hint">
                      En fazla 30 gün geriye bakılır; aralıklar çakışmaz. Aynı
                      mevsimden, en az 2 yıl arayla seç.
                    </p>
                    <details className="small-details">
                      <summary>Tam tarih aralığı</summary>
                      <fieldset>
                        <legend>Önceki dönem</legend>
                        <div className="date-inputs">
                          <input
                            type="date"
                            aria-label="Önceki dönem başlangıcı"
                            value={dates.before_start}
                            onChange={(e) =>
                              setDates({
                                ...dates,
                                before_start: e.target.value,
                              })
                            }
                          />
                          <input
                            type="date"
                            aria-label="Önceki dönem sonu"
                            value={dates.before_end}
                            onChange={(e) =>
                              setDates({ ...dates, before_end: e.target.value })
                            }
                          />
                        </div>
                      </fieldset>
                      <fieldset>
                        <legend>Sonraki dönem</legend>
                        <div className="date-inputs">
                          <input
                            type="date"
                            aria-label="Sonraki dönem başlangıcı"
                            value={dates.after_start}
                            onChange={(e) =>
                              setDates({
                                ...dates,
                                after_start: e.target.value,
                              })
                            }
                          />
                          <input
                            type="date"
                            aria-label="Sonraki dönem sonu"
                            value={dates.after_end}
                            onChange={(e) =>
                              setDates({ ...dates, after_end: e.target.value })
                            }
                          />
                        </div>
                      </fieldset>
                      <p className="hint">
                        Aynı mevsimi seç. Her dönem en fazla 62 gün.
                      </p>
                    </details>
                    <button
                      className="primary full"
                      disabled={active}
                      onClick={() => submit()}
                    >
                      {active ? "İşleniyor…" : "Analizi başlat →"}
                    </button>
                    <details className="small-details">
                      <summary>Görüntüleri önceden kontrol et</summary>
                      <button
                        className="secondary full"
                        onClick={discover}
                        disabled={active}
                      >
                        Görüntü ara
                      </button>
                      {catalog && (
                        <p className="hint" role="status">
                          Önce: {catalog.before.length} · Sonra:{" "}
                          {catalog.after.length} görüntü
                        </p>
                      )}
                    </details>
                  </div>
                ))}
            </details>
            {jobs.length > 0 && (
              <details className="history">
                <summary>Geçmiş sonuçlar</summary>
                <div className="job-list">
                  {jobs.slice(0, 8).map((j) => (
                    <button
                      key={j.id}
                      disabled={active}
                      onClick={() => selectJob(j.id)}
                    >
                      <span>
                        {typeof j.request.display_name === "string"
                          ? j.request.display_name
                          : regionName(jobRegion(j, regions)?.id || "custom")}
                        <small>
                          {j.request.before_end && j.request.after_end
                            ? `${dateLabel(String(j.request.before_end))} → ${dateLabel(String(j.request.after_end))}`
                            : dateLabel(j.created_at)}
                        </small>
                      </span>
                      <span>{statusLabel[j.status] || "Bilinmiyor"}</span>
                    </button>
                  ))}
                </div>
              </details>
            )}
            <footer className="team-credit">
              FRC Team 7729 RAMs<span>FIRST BIOCORE 2027</span>
            </footer>
          </aside>
          <main className="main-workspace" aria-busy={active}>
            <div className="workspace-toolbar">
              <div>
                <span className="step-label">02 / SONUÇ</span>
                <h2>
                  {report ? `${selectedName} · Orman değişimi` : selectedName}
                </h2>
              </div>
              {report && (
                <span className="date-pill">
                  {report.source_observations
                    .map((s) => new Date(s.acquired_at).getUTCFullYear())
                    .join(" → ")}
                </span>
              )}
            </div>
            {error && (
              <div className="error" role="alert">
                {error}
                <button aria-label="Uyarıyı kapat" onClick={() => setError("")}>
                  ×
                </button>
              </div>
            )}
            {active && (
              <p className="execution-state" role="status">
                {busy && report
                  ? "Sonuç açılıyor…"
                  : job?.status === "running"
                    ? job?.stage === "before"
                      ? "Önceki uydu görüntüsü alınıyor…"
                      : job?.stage === "after"
                        ? "Sonraki uydu görüntüsü alınıyor…"
                        : "Model değişimi inceliyor…"
                    : "Analiz sırada…"}
              </p>
            )}
            {report && (
              <section className="summary-strip" aria-label="Analiz özeti">
                <div>
                  <span>İncelenecek alan</span>
                  <strong>
                    {number(report.mapped_candidate_area_ha, 2)}{" "}
                    <small>ha</small>
                  </strong>
                  <small>Hektar · 1 ha = 10.000 m²</small>
                </div>
                <div>
                  <span>Şüpheli değişim</span>
                  <strong>
                    {report.candidate_polygons} <small>alan</small>
                  </strong>
                  <small>Kesin kayıp değil</small>
                </div>
                <div>
                  <span>Görüntü açıklığı</span>
                  <strong>%{number(report.clear_fraction * 100)}</strong>
                  <small>İki tarihte de kullanılabilen alan</small>
                </div>
              </section>
            )}
            <section className="map-section" data-guide="map">
              <ResearchMap
                geometry={geometry}
                job={job}
                draw={draw}
                drawMode={drawMode}
                onCancelDraw={() => setDraw(false)}
                onGeometry={(g) => {
                  setError("");
                  selectionVersion.current++;
                  setGeometry(g);
                  setDraw(false);
                  setSelected("custom");
                  setLocationName("");
                  setJob(null);
                  setCatalog(null);
                  setInspection("");
                  setFireData(null);
                }}
                onPoint={onPoint}
                onObservation={(p) =>
                  setInspection(
                    `Uydu sıcaklık gözlemi · ${dateLabel(String(p.acquired_at))}. Kesin yangın bildirimi değildir.`,
                  )
                }
                opacity={opacity}
                showChange={showChange}
                showSource={showSource}
                fireData={fireData}
              />
              <details className="layer-panel">
                <summary>☷ Harita görünümü</summary>
                <label>
                  <input
                    type="checkbox"
                    checked={showSource}
                    onChange={(e) => setShowSource(e.target.checked)}
                  />
                  Uydu görüntüsü
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={showChange}
                    onChange={(e) => setShowChange(e.target.checked)}
                  />
                  Değişen alanlar
                </label>
                <label htmlFor="opacity">Turuncu alanların görünürlüğü</label>
                <input
                  id="opacity"
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={opacity}
                  onChange={(e) => setOpacity(Number(e.target.value))}
                />
                {analysisAvailable && (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={observeFires}
                  >
                    Son 24 saat: sıcaklık gözlemleri
                  </button>
                )}
              </details>
            </section>
            {report ? (
              <>
                <p className="inspection" aria-live="polite">
                  {inspection || "Bir noktayı incelemek için haritaya dokun."}
                </p>
                <section className="paper comparison" data-guide="comparison">
                  <div className="paper-heading">
                    <h3>Önce / Sonra</h3>
                    <span>Çubuğu kaydır ↔</span>
                  </div>
                  <div className="comparison-images">
                    <img
                      src={`${API}/api/jobs/${job!.id}/files/after.png`}
                      alt="Sonraki tarihteki uydu görüntüsü"
                    />
                    <img
                      className="before-image"
                      style={{ clipPath: `inset(0 ${100 - compare}% 0 0)` }}
                      src={`${API}/api/jobs/${job!.id}/files/before.png`}
                      alt="Önceki tarihteki uydu görüntüsü"
                    />
                    <div
                      className="comparison-divider"
                      style={{ left: `${compare}%` }}
                    />
                    <span className="image-date earlier">
                      Önce ·{" "}
                      {observationDateLabel(report.source_observations[0])}
                    </span>
                    <span className="image-date later">
                      Sonra ·{" "}
                      {observationDateLabel(report.source_observations[1])}
                    </span>
                  </div>
                  <label className="sr-only" htmlFor="comparison">
                    Önce ve sonra karşılaştırması
                  </label>
                  <input
                    id="comparison"
                    type="range"
                    min="0"
                    max="100"
                    value={compare}
                    onChange={(e) => setCompare(Number(e.target.value))}
                  />
                </section>
                <section className="export-bar" data-guide="exports">
                  <div>
                    <strong>Sonucu yanında götür</strong>
                    <small>Deneysel analiz · Yerinde kontrol gerekir</small>
                  </div>
                  <a
                    className="primary"
                    href={`${API}/api/jobs/${job!.id}/export/pdf`}
                    onClick={(e) => downloadExport(e, "pdf")}
                  >
                    ↓ Raporu indir (PDF)
                  </a>
                </section>
                <details className="result-details">
                  <summary>Ayrıntılar ve dosyalar</summary>
                  <p className="hint">
                    Turuncu alanlar, modelin orman örtüsü kaybına benzettiği
                    yerler. Nedenini tek başına belirleyemez.
                  </p>
                  <table className="indicator-table">
                    <thead>
                      <tr>
                        <th>Gösterge</th>
                        <th>Önce</th>
                        <th>Sonra</th>
                        <th>Fark</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(report.indices).map(([name, v]) => (
                        <tr key={name}>
                          <td>
                            <strong>
                              {terms[name]?.label || name.toUpperCase()}
                            </strong>
                            <small>
                              {terms[name]?.meaning ||
                                "Uydu ölçümünden hesaplanan gösterge."}
                            </small>
                          </td>
                          <td>{number(v.before_mean, 3)}</td>
                          <td>{number(v.after_mean, 3)}</td>
                          <td>
                            {v.delta_mean > 0 ? "+" : ""}
                            {number(v.delta_mean, 3)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="hint">
                    Bu göstergeler tek başına zarar veya yangın kanıtı değildir.
                  </p>
                  {report.uncertainty?.status === "available" && (
                    <p className="hint">
                      <strong>Model tutarlılığı:</strong> İki ayrı eğitim
                      arasındaki ortalama puan farkı{" "}
                      {report.uncertainty
                        .mean_disagreement_on_eligible_pixels === null
                        ? "hesaplanamadı"
                        : number(
                            report.uncertainty
                              .mean_disagreement_on_eligible_pixels,
                            3,
                          )}
                      . Düşük fark, modellerin birbirine daha yakın düşündüğünü
                      gösterir; kesinlik değildir.
                    </p>
                  )}
                  <div className="export-row">
                    {["csv", "geojson", "json"].map((format) => (
                      <a
                        key={format}
                        href={`${API}/api/jobs/${job!.id}/export/${format}`}
                        onClick={(e) => downloadExport(e, format)}
                      >
                        {format === "csv"
                          ? "Tablo (CSV)"
                          : format === "geojson"
                            ? "Harita alanları (GeoJSON)"
                            : "Ham rapor (JSON)"}
                      </a>
                    ))}
                    <a href={`${API}/api/jobs/${job!.id}/files/score.tif`}>
                      Puan haritası (GeoTIFF)
                    </a>
                    {report.uncertainty?.status === "available" && (
                      <a
                        href={`${API}/api/jobs/${job!.id}/files/uncertainty.tif`}
                      >
                        Model farkı (GeoTIFF)
                      </a>
                    )}
                  </div>
                  <p className="hint">
                    GeoJSON: harita sınırları. GeoTIFF: konumu kayıtlı görüntü.
                    CSV: elektronik tablo.
                  </p>
                  <p className="hint">
                    Uydu: Copernicus Sentinel-2 · Her piksel 30 × 30 m. Bulut ve
                    gölge bazı alanları gizleyebilir. Puanlar kesin olasılık
                    değildir. Yangın tahmini bu sürümde yok.
                  </p>
                  <dl className="provenance">
                    <dt>Görüntü tarihleri</dt>
                    <dd>
                      {report.source_observations.map((s) => (
                        <span key={s.scene_id}>
                          {observationDateLabel(s)} · {s.scene_id}
                          <br />
                        </span>
                      ))}
                    </dd>
                    <dt>Model sürümü</dt>
                    <dd>{report.model_version}</dd>
                    <dt>Analiz tarihi</dt>
                    <dd>{dateLabel(report.generated_at)}</dd>
                  </dl>
                </details>
              </>
            ) : (
              !active && (
                <section className="empty-assessment">
                  <h3>
                    {notice
                      ? "Bu bölgenin sonucu henüz yok"
                      : "Bir bölge seçerek başla"}
                  </h3>
                  <p>
                    {analysisAvailable
                      ? "Tarihleri seçip Analizi başlat’a dokun."
                      : "“Sonucu aç” yazan bir bölgeyi seç."}
                  </p>
                </section>
              )
            )}
          </main>
        </div>
      </div>
      {tour && (
        <Walkthrough
          onClose={() => {
            setTour(false);
            document
              .querySelector('[data-guide="regions"]')
              ?.scrollIntoView({ block: "start", behavior: "instant" });
          }}
        />
      )}
    </>
  );
}

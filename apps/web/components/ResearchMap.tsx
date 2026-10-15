"use client";
import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import { type GeoJSONSource, type Map as MapType } from "maplibre-gl";
import { API, type Geometry, type Job } from "../lib/api";
import { geometryError } from "../lib/geometry";

type Props = {
  geometry: Geometry;
  job: Job | null;
  draw: boolean;
  drawMode: "polygon" | "rectangle";
  onGeometry: (g: Geometry) => void;
  onCancelDraw: () => void;
  onPoint: (lon: number, lat: number) => void;
  onObservation: (properties: Record<string, unknown>) => void;
  opacity: number;
  showChange: boolean;
  showSource: boolean;
  fireData: GeoJSON.FeatureCollection | null;
};
export default function ResearchMap(props: Props) {
  const container = useRef<HTMLDivElement>(null),
    map = useRef<MapType | null>(null);
  const current = useRef(props),
    points = useRef<number[][]>([]),
    finished = useRef(false);
  const [ready, setReady] = useState(false),
    [pointCount, setPointCount] = useState(0),
    [drawError, setDrawError] = useState(""),
    [cursor, setCursor] = useState("Haritaya dokun, noktayı incele"),
    [mapError, setMapError] = useState("");
  function updateDrawing() {
    setPointCount(points.current.length);
    setDrawError("");
    (map.current?.getSource("drawing") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: [
        ...(points.current.length >= 2
          ? [
              {
                type: "Feature" as const,
                properties: {},
                geometry: {
                  type: "LineString" as const,
                  coordinates: points.current,
                },
              },
            ]
          : []),
        ...points.current.map((coordinates) => ({
          type: "Feature" as const,
          properties: {},
          geometry: { type: "Point" as const, coordinates },
        })),
      ],
    });
  }
  function complete(geometry: Geometry) {
    const error = geometryError(geometry);
    if (error) {
      setDrawError(error);
      return;
    }
    finished.current = true;
    points.current = [];
    updateDrawing();
    current.current.onGeometry(geometry);
  }
  function finishPolygon() {
    if (finished.current || !points.current.length) return;
    complete({
      type: "Polygon",
      coordinates: [[...points.current, points.current[0]]],
    });
  }
  useEffect(() => {
    current.current = props;
  }, [props]);
  useEffect(() => {
    if (!container.current) return;
    setReady(false);
    maplibregl.setWorkerUrl("/vendor/maplibre/maplibre-gl-worker.mjs");
    const m = new maplibregl.Map({
      container: container.current,
      center: [28.2, 37.15],
      zoom: 9.4,
      locale: {
        "Map.Title": "Harita",
        "NavigationControl.ZoomIn": "Yakınlaştır",
        "NavigationControl.ZoomOut": "Uzaklaştır",
        "AttributionControl.ToggleAttribution": "Kaynakları göster",
        "CooperativeGesturesHandler.MobileHelpText":
          "Haritayı iki parmakla hareket ettir",
      },
      style: {
        version: 8,
        sources: {
          imagery: {
            type: "raster",
            tiles: [
              "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            ],
            tileSize: 256,
            attribution:
              "Harita © Esri, Maxar, Earthstar Geographics. Analiz: Copernicus Sentinel-2.",
          },
        },
        layers: [{ id: "basemap", type: "raster", source: "imagery" }],
      },
    });
    map.current = m;
    m.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right",
    );
    // Interaction layers need the style, not the external raster tile network.
    // Waiting for map.load loses early drawing input on slow/offline basemaps.
    m.once("style.load", () => {
      m.addSource("aoi", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      m.addLayer({
        id: "aoi-fill",
        type: "fill",
        source: "aoi",
        paint: { "fill-color": "#ffd600", "fill-opacity": 0.04 },
      });
      m.addLayer({
        id: "aoi-outline",
        type: "line",
        source: "aoi",
        paint: {
          "line-color": "#ffd600",
          "line-width": 2,
          "line-dasharray": [3, 2],
        },
      });
      m.addSource("drawing", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      m.addLayer({
        id: "drawing-line",
        type: "line",
        source: "drawing",
        paint: { "line-color": "#ffffff", "line-width": 3 },
        filter: ["==", ["geometry-type"], "LineString"],
      });
      m.addLayer({
        id: "drawing-vertices",
        type: "circle",
        source: "drawing",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-color": "#080800",
          "circle-radius": 5,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
      m.addSource("change", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      m.addLayer({
        id: "change-fill",
        type: "fill",
        source: "change",
        paint: { "fill-color": "#d77436", "fill-opacity": 0.65 },
      });
      m.addLayer({
        id: "change-line",
        type: "line",
        source: "change",
        paint: { "line-color": "#ffe0a0", "line-width": 0.7 },
      });
      m.addSource("fires", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      m.addLayer({
        id: "fires-points",
        type: "circle",
        source: "fires",
        paint: {
          "circle-radius": 5,
          "circle-color": "#ff655b",
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 1,
        },
      });
      setReady(true);
    });
    m.on("error", (event) => {
      if (event.error?.message?.includes("WebGL"))
        setMapError(
          "Harita bu cihazda açılamıyor. Görüntüleri karşılaştırabilir ve raporu indirebilirsiniz.",
        );
    });
    m.on("mousemove", (e) =>
      setCursor(
        `${e.lngLat.lat.toFixed(5)}° K  ·  ${e.lngLat.lng.toFixed(5)}° D`,
      ),
    );
    m.on("click", (e) => {
      if (current.current.draw) {
        // The second click in a double click must not add another vertex.
        if (finished.current || e.originalEvent.detail > 1) return;
        const last = points.current.at(-1);
        if (last && m.project(last as [number, number]).dist(e.point) <= 3)
          return;
        if (
          current.current.drawMode === "polygon" &&
          points.current.length >= 3 &&
          m.project(points.current[0] as [number, number]).dist(e.point) <= 10
        ) {
          finishPolygon();
          return;
        }
        if (points.current.length >= 199) {
          setDrawError("En fazla 199 köşe seçin. Alanı bitir’e dokunun.");
          return;
        }
        points.current.push([e.lngLat.lng, e.lngLat.lat]);
        updateDrawing();
        if (
          current.current.drawMode === "rectangle" &&
          points.current.length === 2
        ) {
          const [a, b] = points.current;
          const rectangle: Geometry = {
            type: "Polygon",
            coordinates: [
              [
                [Math.min(a[0], b[0]), Math.min(a[1], b[1])],
                [Math.max(a[0], b[0]), Math.min(a[1], b[1])],
                [Math.max(a[0], b[0]), Math.max(a[1], b[1])],
                [Math.min(a[0], b[0]), Math.max(a[1], b[1])],
                [Math.min(a[0], b[0]), Math.min(a[1], b[1])],
              ],
            ],
          };
          // A zero-width rectangle is editable by picking its second corner again.
          if (a[0] === b[0] || a[1] === b[1]) {
            points.current.pop();
            updateDrawing();
            setDrawError("İkinci köşeyi çaprazdan seçin.");
          } else complete(rectangle);
        }
      } else {
        const observations = m.getLayer("fires-points")
          ? m.queryRenderedFeatures(e.point, { layers: ["fires-points"] })
          : [];
        if (observations.length)
          current.current.onObservation(observations[0].properties || {});
        else current.current.onPoint(e.lngLat.lng, e.lngLat.lat);
      }
    });
    m.on("dblclick", (e) => {
      if (
        current.current.draw &&
        current.current.drawMode === "polygon" &&
        !finished.current
      ) {
        e.preventDefault();
        finishPolygon();
      }
    });
    return () => {
      m.remove();
      map.current = null;
    };
  }, []);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !m.getSource("aoi")) return;
    (m.getSource("aoi") as GeoJSONSource).setData({
      type: "Feature",
      properties: {},
      geometry: props.geometry,
    });
    const c = props.geometry.coordinates[0];
    const bounds = c.reduce(
      (b, p) => b.extend(p as [number, number]),
      new maplibregl.LngLatBounds(
        c[0] as [number, number],
        c[0] as [number, number],
      ),
    );
    m.fitBounds(bounds, { padding: 75, maxZoom: 12, duration: 500 });
  }, [props.geometry, ready]);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !m.getSource("drawing")) return;
    points.current = [];
    finished.current = false;
    setPointCount(0);
    setDrawError("");
    (m.getSource("drawing") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: [],
    });
    m.getCanvas().style.cursor = props.draw ? "crosshair" : "";
    if (props.draw) m.doubleClickZoom.disable();
    else m.doubleClickZoom.enable();
  }, [props.draw, props.drawMode, ready]);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !m.getSource("change")) return;
    (m.getSource("change") as GeoJSONSource).setData(
      props.job?.report
        ? `${API}/api/jobs/${props.job.id}/files/change.geojson`
        : { type: "FeatureCollection", features: [] },
    );
    if (m.getLayer("source-imagery")) m.removeLayer("source-imagery");
    if (m.getSource("source-image")) m.removeSource("source-image");
    if (props.job?.report) {
      const b = props.job.report.bounds;
      const corners = props.job.report.corners || [
        [b[0], b[3]],
        [b[2], b[3]],
        [b[2], b[1]],
        [b[0], b[1]],
      ];
      m.addSource("source-image", {
        type: "image",
        url: `${API}/api/jobs/${props.job.id}/files/after.png`,
        coordinates: corners as [
          [number, number],
          [number, number],
          [number, number],
          [number, number],
        ],
      });
      m.addLayer(
        {
          id: "source-imagery",
          type: "raster",
          source: "source-image",
          paint: { "raster-opacity": 1 },
        },
        "aoi-fill",
      );
    }
  }, [props.job, ready]);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !m.getLayer("change-fill")) return;
    m.setPaintProperty("change-fill", "fill-opacity", props.opacity);
    for (const id of ["change-fill", "change-line"])
      m.setLayoutProperty(
        id,
        "visibility",
        props.showChange ? "visible" : "none",
      );
    if (m.getLayer("source-imagery"))
      m.setLayoutProperty(
        "source-imagery",
        "visibility",
        props.showSource ? "visible" : "none",
      );
  }, [props.opacity, props.showChange, props.showSource, props.job, ready]);
  useEffect(() => {
    if (ready)
      (map.current?.getSource("fires") as GeoJSONSource)?.setData(
        props.fireData || { type: "FeatureCollection", features: [] },
      );
  }, [props.fireData, ready]);
  return (
    <div className="map-wrap">
      <div ref={container} className="map" aria-label="Etkileşimli harita" />
      <div className="map-coordinate">{cursor}</div>
      {mapError && <div className="map-message">{mapError}</div>}
      <div className="map-caption">
        <span className="key-swatch" />
        İncelenecek alanlar
        <span className="key-line" />
        Bölge sınırı
      </div>
      {props.draw && (
        <div className="draw-hint">
          <p role="status">
            {props.drawMode === "rectangle"
              ? "Alanın iki karşı köşesine dokun"
              : `Köşeleri seç · ${pointCount} köşe`}
          </p>
          {drawError && <p role="alert">{drawError}</p>}
          <div className="draw-actions">
            {props.drawMode === "polygon" && (
              <button
                className="primary"
                disabled={pointCount < 3}
                onClick={finishPolygon}
              >
                Alanı bitir
              </button>
            )}
            <button
              disabled={!pointCount}
              onClick={() => {
                points.current.pop();
                updateDrawing();
              }}
            >
              Geri al
            </button>
            <button onClick={props.onCancelDraw}>Vazgeç</button>
          </div>
        </div>
      )}
    </div>
  );
}

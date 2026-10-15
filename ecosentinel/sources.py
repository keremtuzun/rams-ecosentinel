"""Bounded source connectors. Remote URLs are provider-owned, never user input."""

import csv
import io
import os
import time
import logging
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from shapely.geometry import shape

from ecosentinel.common import (
    ARTIFACTS,
    DataUnavailable,
    TransientDataUnavailable,
    sha256,
    utcnow,
    write_json,
)

EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
CDSE_STAC = "https://stac.dataspace.copernicus.eu/v1"
HANSEN_VERSION = "GFC-2025-v1.13"
HANSEN_BASE = f"https://storage.googleapis.com/earthenginepartners-hansen/{HANSEN_VERSION}"
RASTER_HOSTS = {
    "sentinel-cogs.s3.us-west-2.amazonaws.com",
    "storage.googleapis.com",
    "esa-worldcover.s3.eu-central-1.amazonaws.com",
}


def provider_url(url):
    p = urlparse(url)
    if p.scheme != "https" or p.hostname not in RASTER_HOSTS or p.username or p.password or p.port:
        raise DataUnavailable("Untrusted raster asset URL")
    if p.query or p.fragment:
        raise DataUnavailable("Signed or parameterized raster assets are not accepted by this connector")
    return url


def request_json(method, url, **kwargs):
    for attempt in range(3):
        try:
            response = httpx.request(method, url, timeout=45, follow_redirects=False, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            if attempt == 2:
                raise TransientDataUnavailable(
                    "Satellite catalogue unavailable after three bounded attempts"
                ) from None
    raise TransientDataUnavailable("Satellite catalogue unavailable")


def search_sentinel(geometry, start, end, cloud=20, catalog="earth-search"):
    if catalog not in {"earth-search", "copernicus"}:
        raise ValueError("Unknown catalogue")
    base = EARTH_SEARCH if catalog == "earth-search" else CDSE_STAC
    payload = {
        "collections": ["sentinel-2-l2a"],
        "intersects": geometry,
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": 100,
        "query": {"eo:cloud_cover": {"lte": cloud}},
    }
    features = request_json("POST", base + "/search", json=payload).get("features", [])
    # Pagination intentionally bounded: narrow the time/AOI if >100 items. No unlimited catalogue traversal.
    features = [f for f in features if f["properties"].get("eo:cloud_cover", 100) <= cloud]
    unique = {f["id"]: f for f in features}
    return sorted(unique.values(), key=lambda f: f["properties"]["datetime"], reverse=True)


def covering_scenes(geometry, start, end):
    aoi = shape(geometry)
    return [f for f in search_sentinel(geometry, start, end) if shape(f["geometry"]).covers(aoi)]


def covering_observations(geometry, start, end):
    """Cover the requested area with real tiles acquired within at most five days."""
    aoi = shape(geometry)
    features = search_sentinel(geometry, start, end)
    result, seen = [], set()
    for day in sorted({f["properties"]["datetime"][:10] for f in features}, reverse=True):
        earliest = (date.fromisoformat(day) - timedelta(days=4)).isoformat()
        same_day = [f for f in features if f["properties"]["datetime"][:10] == day]
        nearby = [f for f in features if earliest <= f["properties"]["datetime"][:10] <= day]
        for pool in [same_day, nearby]:
            remaining, chosen = aoi, []
            pool = pool.copy()
            while not remaining.is_empty and pool and len(chosen) < 8:
                singles = [f for f in pool if shape(f["geometry"]).covers(remaining)]
                item = (
                    singles[0]
                    if singles
                    else max(pool, key=lambda f: shape(f["geometry"]).intersection(remaining).area)
                )
                footprint = shape(item["geometry"])
                if not footprint.intersects(remaining) or footprint.intersection(remaining).area == 0:
                    break
                chosen.append(item)
                remaining = remaining.difference(footprint)
                pool.remove(item)
            identity = tuple(f["id"] for f in chosen)
            if remaining.is_empty and identity not in seen:
                result.append(chosen)
                seen.add(identity)
    return sorted(result, key=lambda group: max(f["properties"]["datetime"] for f in group), reverse=True)


def hansen_url(layer, lon, lat):
    if layer not in {"lossyear", "treecover2000", "datamask"}:
        raise ValueError("Unsupported Hansen layer")
    north = int((lat // 10 + 1) * 10)
    west = int(lon // 10 * 10)
    tile = f"{abs(north):02d}{'N' if north >= 0 else 'S'}_{abs(west):03d}{'E' if west >= 0 else 'W'}"
    return f"{HANSEN_BASE}/Hansen_{HANSEN_VERSION}_{layer}_{tile}.tif"


def worldcover_url(lon, lat):
    """2021 v200 context only. Do not subtract different annual algorithm versions."""
    south, west = int(lat // 3 * 3), int(lon // 3 * 3)
    tile = f"N{south:02d}E{west:03d}"
    return f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"


def parse_firms(content, bbox=None, source="VIIRS_SNPP_NRT"):
    features = []
    for row in csv.DictReader(io.StringIO(content)):
        try:
            lon, lat = float(row["longitude"]), float(row["latitude"])
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError()
            if bbox and not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                continue
            stamp = str(row["acq_time"]).zfill(4)
            acquisition = datetime.strptime(f"{row['acq_date']} {stamp}", "%Y-%m-%d %H%M").replace(
                tzinfo=timezone.utc
            )
        except (ValueError, KeyError, TypeError):
            raise DataUnavailable("Malformed FIRMS observation") from None
        sensor = row.get("instrument") or ("MODIS" if source.startswith("MODIS") else "VIIRS")
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "source": source,
                    "acquired_at": acquisition.isoformat(),
                    "confidence": row.get("confidence"),
                    "frp_mw": row.get("frp"),
                    "sensor": sensor,
                    "scan_km": row.get("scan"),
                    "confidence_interpretation": "MODIS detection confidence (0–100)"
                    if sensor == "MODIS"
                    else "VIIRS source confidence category",
                    "track_km": row.get("track"),
                    "meaning": "observed thermal anomaly",
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "limitations": "Thermal anomalies are observations, may not be wildfires, and are not burned polygons.",
    }


def fetch_firms(bbox, days=3, start=None, source="VIIRS_SNPP_NRT"):
    # httpx INFO logging includes full request URLs, which contain the FIRMS MAP_KEY.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        if days == 1 and start is None:
            return fetch_public_modis(bbox)
        raise DataUnavailable("FIRMS_MAP_KEY is required; no fire observations were substituted")
    if source not in {"VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT", "VIIRS_SNPP_SP", "MODIS_SP"}:
        raise ValueError("Unsupported FIRMS product")
    if not 1 <= days <= 10:
        raise ValueError("FIRMS requests are limited to ten days")
    extent = ",".join(str(float(v)) for v in bbox)
    suffix = f"/{date.fromisoformat(str(start))}" if start else ""
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{extent}/{days}{suffix}"
    try:
        response = httpx.get(url, timeout=45)
        response.raise_for_status()
        if not response.text.startswith("latitude,longitude"):
            raise DataUnavailable("FIRMS returned an error or unsupported response")
        return parse_firms(response.text, bbox, source)
    except httpx.HTTPError:
        # Never surface the credential-bearing request URL or upstream exception.
        raise DataUnavailable(
            "FIRMS retrieval failed; check credentials, product and service availability"
        ) from None


def fetch_public_modis(bbox):
    """Official public rolling 24-hour MODIS NRT feed; never a science-quality training archive."""
    url = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Global_24h.csv"
    directory = ARTIFACTS / "sources" / "firms"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "MODIS_C6_1_Global_24h.csv"
    if not path.exists() or time.time() - path.stat().st_mtime > 3600:
        content = bytearray()
        try:
            with httpx.stream("GET", url, timeout=45, follow_redirects=False) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 10_000_000:
                        raise DataUnavailable("FIRMS feed exceeds the 10 MB acquisition limit")
        except httpx.HTTPError:
            raise DataUnavailable("Public NASA MODIS feed unavailable; no observations substituted") from None
        text = content.decode("utf-8")
        global_observations = parse_firms(text, source="MODIS_C6_1_NRT_PUBLIC_24H")
        if not global_observations["features"]:
            raise DataUnavailable("Public FIRMS feed has no verifiable timestamps")
        latest = max(
            datetime.fromisoformat(f["properties"]["acquired_at"]) for f in global_observations["features"]
        )
        if (datetime.now(timezone.utc) - latest).total_seconds() > 48 * 3600:
            raise DataUnavailable("Public FIRMS feed is stale (latest observation older than 48 hours)")
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
        write_json(
            directory / "public_feed.json",
            {
                "source_url": url,
                "retrieved_at": utcnow(),
                "sha256": sha256(path),
                "quality": "NRT",
                "coverage": "rolling global 24-hour feed",
            },
        )
    from ecosentinel.common import read_json

    if read_json(directory / "public_feed.json")["sha256"] != sha256(path):
        raise DataUnavailable("Cached FIRMS feed checksum mismatch")
    result = parse_firms(path.read_text(encoding="utf-8"), bbox, "MODIS_C6_1_NRT_PUBLIC_24H")
    result.update(
        {
            "window": "rolling 24 hours",
            "quality": "NRT; not science-quality historical training labels",
            "source_url": url,
            "raw_feed_sha256": sha256(path),
            "note": "No detections in an AOI does not establish absence of wildfire",
        }
    )
    return result


def retrieve_era5_land(request, target):
    """Explicit reanalysis acquisition for retrospective research, never prospective availability proof."""
    if not os.environ.get("CDSAPI_KEY"):
        raise DataUnavailable("CDSAPI_KEY and accepted CDS dataset terms are required")
    import cdsapi

    cdsapi.Client(
        url=os.environ.get("CDSAPI_URL", "https://cds.climate.copernicus.eu/api"),
        key=os.environ["CDSAPI_KEY"],
    ).retrieve("reanalysis-era5-land", request, str(target))
    return {
        "source": "ERA5-Land",
        "target": str(target),
        "availability": "retrospective reanalysis",
        "prospective_eligible": False,
    }

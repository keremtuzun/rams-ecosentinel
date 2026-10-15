import math
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from scipy.ndimage import binary_dilation

from ecosentinel.common import PREPROCESSING, DataUnavailable, read_json, sha256, utcnow, write_json
from ecosentinel.sources import covering_observations, provider_url


@dataclass
class Grid:
    crs: str
    transform: Affine
    width: int
    height: int

    def metadata(self):
        return {
            "crs": self.crs,
            "transform": list(self.transform)[:6],
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_metadata(cls, meta):
        return cls(meta["crs"], Affine(*meta["transform"]), meta["width"], meta["height"])

    def bounds(self):
        west, north = self.transform * (0, 0)
        east, south = self.transform * (self.width, self.height)
        return west, south, east, north

    def wgs84_bounds(self):
        return list(transform_bounds(self.crs, "EPSG:4326", *self.bounds(), densify_pts=21))


def make_grid(geometry, resolution=30):
    from shapely.geometry import shape

    aoi = shape(geometry)
    epsg = 32600 + int((aoi.centroid.x + 180) // 6) + 1
    crs = f"EPSG:{epsg}"
    west, south, east, north = transform_bounds("EPSG:4326", crs, *aoi.bounds, densify_pts=21)
    west, south = math.floor(west / resolution) * resolution, math.floor(south / resolution) * resolution
    east, north = math.ceil(east / resolution) * resolution, math.ceil(north / resolution) * resolution
    width, height = round((east - west) / resolution), round((north - south) / resolution)
    if width > 1670 or height > 1670:
        raise DataUnavailable("AOI exceeds the 50 km processing limit at 30 m")
    return Grid(crs, Affine(resolution, 0, west, 0, -resolution, north), width, height)


def aoi_mask(geometry, grid):
    from shapely.geometry import mapping, shape
    from shapely.ops import transform

    project = Transformer.from_crs(4326, grid.crs, always_xy=True).transform
    projected = transform(project, shape(geometry))
    return geometry_mask([mapping(projected)], (grid.height, grid.width), grid.transform, invert=True)


def joint_valid_mask(before_valid, after_valid, geometry, grid):
    area = aoi_mask(geometry, grid)
    valid = before_valid & after_valid & area
    # Padding outside a polygon is not missing satellite data. Water inside the
    # selected area still counts as unusable, preserving the 65% joint-data gate.
    if valid.sum() / max(area.sum(), 1) < 0.65:
        raise DataUnavailable("Insufficient jointly clear observations for comparison")
    return valid


def read_aligned(url, grid, categorical=False):
    provider_url(url)
    # GDAL only fetches necessary COG blocks. No complete global tile downloads.
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
        GDAL_HTTP_TIMEOUT="45",
        GDAL_HTTP_MAX_RETRY="2",
        GDAL_HTTP_RETRY_DELAY="1",
        GDAL_CACHEMAX=128,
    ):
        with rasterio.open(url) as src:
            if src.crs is None or src.count != 1:
                raise DataUnavailable("Raster is missing CRS or has unexpected bands")
            with WarpedVRT(
                src,
                crs=grid.crs,
                transform=grid.transform,
                width=grid.width,
                height=grid.height,
                resampling=Resampling.nearest if categorical else Resampling.bilinear,
                dtype="float32",
                nodata=-9999,
            ) as vrt:
                return vrt.read(1, masked=True).filled(np.nan).astype(np.float32)


def reflectance_parameters(item, asset):
    metadata = asset.get("raster:bands", [{}])[0]
    if "scale" not in metadata or "offset" not in metadata:
        raise DataUnavailable("Reflectance scaling metadata missing")
    scale, offset = float(metadata["scale"]), float(metadata["offset"])
    applied = item["properties"].get("earthsearch:boa_offset_applied")
    # Earth Search COG DN has already had BOA_ADD_OFFSET applied when this flag is true.
    # False + modern baseline is ambiguous (provider issue #66): reject instead of double subtracting.
    baseline = float(item["properties"].get("s2:processing_baseline", "0"))
    if applied is True:
        offset = 0.0
    elif baseline >= 4 and offset != 0:
        raise DataUnavailable("Ambiguous BOA offset; require provider-corrected COG metadata")
    if not 0 < scale <= 0.01:
        raise DataUnavailable("Invalid reflectance scale")
    return scale, offset


def clear_mask(scl):
    good = np.isin(scl, PREPROCESSING["valid_scl"])
    contaminated = np.isin(scl, [0, 1, 2, 3, 7, 8, 9, 10, 11]) | ~np.isfinite(scl)
    return good & ~binary_dilation(contaminated, iterations=PREPROCESSING["cloud_buffer_pixels"])


def acquire_scene(geometry, start, end, grid, directory):
    geometry = json.loads(json.dumps(geometry))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cache = directory / "scene.json"
    if cache.exists():
        meta = read_json(cache)
        if meta["grid"] != grid.metadata() or meta["query"] != {
            "start": str(start),
            "end": str(end),
            "geometry": geometry,
        }:
            raise DataUnavailable("Cache request does not match its recorded provenance")
        cache_files = ["reflectance.tif", "valid.tif"]
        if "source_index.tif" in meta["checksums"]:
            cache_files.append("source_index.tif")
        for name in cache_files:
            if sha256(directory / name) != meta["checksums"][name]:
                raise DataUnavailable("Cached raster checksum mismatch")
        with rasterio.open(directory / "reflectance.tif") as f:
            bands = f.read()
        with rasterio.open(directory / "valid.tif") as f:
            valid = f.read(1).astype(bool)
        return bands, valid, meta
    candidates = covering_observations(geometry, start, end)
    failures = []
    for observation in candidates[:5]:
        try:
            area_mask = aoi_mask(geometry, grid)
            bands = np.zeros((6, grid.height, grid.width), np.float32)
            valid = np.zeros((grid.height, grid.width), bool)
            water = np.zeros_like(valid)
            classified = np.zeros_like(valid)
            source_index = np.zeros((grid.height, grid.width), np.uint8)
            sources = []
            for item in observation:
                if any(key not in item["assets"] for key in PREPROCESSING["bands"] + ["scl"]):
                    raise DataUnavailable("Required spectral bands missing")
                scl = read_aligned(item["assets"]["scl"]["href"], grid, True)
                first = area_mask & np.isfinite(scl) & ~classified
                water[first] = scl[first] == 6
                classified |= area_mask & np.isfinite(scl)
                tile_valid = clear_mask(scl) & area_mask
                tile_bands, scaling = [], {}
                for key in PREPROCESSING["bands"]:
                    asset = item["assets"][key]
                    scale, offset = reflectance_parameters(item, asset)
                    reflectance = read_aligned(asset["href"], grid) * scale + offset
                    tile_valid &= np.isfinite(reflectance) & (reflectance >= -0.1) & (reflectance <= 1.2)
                    tile_bands.append(reflectance)
                    scaling[key] = {
                        "effective_scale": scale,
                        "effective_offset": offset,
                        "href": asset["href"],
                    }
                take = tile_valid & ~valid
                bands[:, take] = np.stack(tile_bands)[:, take]
                valid |= take
                water[take] = False
                source_index[take] = len(sources) + 1
                sources.append(
                    {
                        "scene_id": item["id"],
                        "acquired_at": item["properties"]["datetime"],
                        "scaling": scaling,
                        "scl_href": item["assets"]["scl"]["href"],
                        "footprint": item["geometry"],
                        "used_pixels": int(take.sum()),
                    }
                )
            nonwater = area_mask & ~water
            bands[:, ~valid] = 0
            if valid.sum() / max(nonwater.sum(), 1) < 0.8:
                raise DataUnavailable("Less than 80 percent clear AOI land pixels")
            write_raster(directory / "reflectance.tif", bands, grid, descriptions=PREPROCESSING["bands"])
            write_raster(directory / "valid.tif", valid.astype(np.uint8)[None], grid, nodata=0)
            write_raster(directory / "source_index.tif", source_index[None], grid, nodata=0)
            used_sources = [s for s in sources if s["used_pixels"] > 0]
            meta = {
                "source": "Copernicus Sentinel-2 L2A via Element 84 Earth Search COG mirror",
                "scene_id": ", ".join(s["scene_id"] for s in used_sources),
                "acquired_at": max(s["acquired_at"] for s in used_sources),
                "acquisition_range": [
                    min(s["acquired_at"] for s in used_sources),
                    max(s["acquired_at"] for s in used_sources),
                ],
                "mosaic": len(used_sources) > 1,
                "mosaic_method": "first valid observation; acquisition span at most five calendar days",
                "observations": sources,
                "retrieved_at": utcnow(),
                "grid": grid.metadata(),
                "clear_fraction": float(valid.sum() / max(nonwater.sum(), 1)),
                "quality_denominator": "AOI pixels excluding SCL water; clouds and missing pixels remain in denominator",
                "water_fraction": float(water.sum() / max(area_mask.sum(), 1)),
                "scaling": sources[0]["scaling"]
                if len(sources) == 1
                else {s["scene_id"]: s["scaling"] for s in sources},
                "preprocessing": PREPROCESSING,
                "query": {"start": str(start), "end": str(end), "geometry": geometry},
                "checksums": {
                    name: sha256(directory / name)
                    for name in ["reflectance.tif", "valid.tif", "source_index.tif"]
                },
            }
            write_json(directory / "stac.json", observation[0] if len(observation) == 1 else observation)
            write_json(cache, meta)
            return bands, valid, meta
        except (DataUnavailable, rasterio.errors.RasterioError) as exc:
            failures.append({"scene": [item["id"] for item in observation], "reason": str(exc)[:200]})
    write_json(directory / "failed_candidates.json", failures)
    raise DataUnavailable("No acceptable covering Sentinel-2 observation; see failed_candidates.json")


def write_raster(path, bands, grid, nodata=-9999, descriptions=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="COG",
        height=grid.height,
        width=grid.width,
        count=bands.shape[0],
        dtype=str(bands.dtype),
        crs=grid.crs,
        transform=grid.transform,
        nodata=nodata,
        compress="DEFLATE",
        blocksize=128,
    ) as dst:
        dst.write(bands)
        if descriptions:
            dst.descriptions = tuple(descriptions)


def indices(bands):
    red, nir, swir1, swir2 = bands[2], bands[3], bands[4], bands[5]

    def ratio(a, b):
        return np.divide(a - b, a + b, out=np.zeros_like(a), where=np.abs(a + b) > 1e-6)

    return {"ndvi": ratio(nir, red), "ndmi": ratio(nir, swir1), "nbr": ratio(nir, swir2)}


def rgb_png(path, bands, valid):
    rgb = np.clip(bands[[2, 1, 0]] / 0.3, 0, 1) ** (1 / 1.5)
    pixels = (np.moveaxis(rgb, 0, -1) * 255).astype(np.uint8)
    Image.fromarray(np.dstack([pixels, valid.astype(np.uint8) * 255])).save(path)

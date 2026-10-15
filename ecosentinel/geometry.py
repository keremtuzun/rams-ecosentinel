import math
from calendar import monthrange
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field, model_validator
from pyproj import Geod
from rasterio.warp import transform_bounds
from shapely.geometry import shape


def validate_geometry(geometry):
    try:
        polygon = shape(geometry)
    except Exception as exc:
        raise ValueError("Invalid GeoJSON geometry") from exc
    if polygon.geom_type != "Polygon" or not polygon.is_valid or polygon.is_empty:
        raise ValueError("AOI must be a valid, nonempty Polygon")
    coordinates = geometry.get("coordinates", [])
    if sum(len(r) for r in coordinates) > 200:
        raise ValueError("AOI is limited to 200 vertices")
    if any(len(p) != 2 or not all(math.isfinite(float(v)) for v in p) for r in coordinates for p in r):
        raise ValueError("Coordinates must be finite longitude/latitude pairs")
    west, south, east, north = polygon.bounds
    if not (25 <= west < east <= 45 and 35 <= south < north <= 43):
        raise ValueError("Research scope is Türkiye: longitude 25–45, latitude 35–43")
    area, _ = Geod(ellps="WGS84").geometry_area_perimeter(polygon)
    if not 0.1 <= abs(area) / 1e6 <= 2500:
        raise ValueError("AOI area must be between 0.1 and 2500 square kilometres")
    epsg = 32600 + int((polygon.centroid.x + 180) // 6) + 1
    x1, y1, x2, y2 = transform_bounds("EPSG:4326", f"EPSG:{epsg}", west, south, east, north, densify_pts=21)
    if max(x2 - x1, y2 - y1) > 50000:
        raise ValueError("AOI bounding dimensions may not exceed 50 km")
    return polygon


class AnalysisRequest(BaseModel):
    geometry: dict
    before_start: date
    before_end: date
    after_start: date
    after_end: date
    module: str = Field(default="habitat", pattern="^(habitat|wildfire)$")

    @model_validator(mode="after")
    def validate_request(self):
        validate_geometry(self.geometry)
        for start, end in [(self.before_start, self.before_end), (self.after_start, self.after_end)]:
            if not date(2017, 1, 1) <= start <= end <= datetime.now(timezone.utc).date():
                raise ValueError("Date ranges must be ordered, in the past, and start in 2017 or later")
            if (end - start).days > 62:
                raise ValueError("Each scene-search window is limited to 62 days")
        if self.before_end >= self.after_start:
            raise ValueError("The two observation windows must not overlap")
        anniversary = date(
            self.before_end.year + 2,
            self.before_end.month,
            min(self.before_end.day, monthrange(self.before_end.year + 2, self.before_end.month)[1]),
        )
        if self.after_end < anniversary:
            raise ValueError("Comparison dates must be at least two years apart")
        if (self.after_end - self.before_start).days > 3653:
            raise ValueError("Comparison interval cannot exceed ten years")
        a, b = self.before_start.timetuple().tm_yday, self.after_start.timetuple().tm_yday
        if min(abs(a - b), 366 - abs(a - b)) > 45:
            raise ValueError("Choose comparable seasons (start dates within 45 days of year)")
        return self

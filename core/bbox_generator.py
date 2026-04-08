from dataclasses import dataclass, field
from typing import Optional, Tuple
import os
import requests
import math
from urllib.parse import quote

@dataclass
class BBox:
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    label: str = ""
    confidence: float = 1.0

    def center(self) -> Tuple[float, float]:
        return ((self.min_lat + self.max_lat) / 2,
                (self.min_lon + self.max_lon) / 2)

    def area_km2(self) -> float:
        # 1 degree lat approx 111 km
        # 1 degree lon approx 111 * cos(lat) km
        lat_dist = 111.0 * (self.max_lat - self.min_lat)
        lon_dist = 111.0 * (self.max_lon - self.min_lon) * math.cos(math.radians(self.center()[0]))
        return abs(lat_dist * lon_dist)

class BBoxGenerator:
    """
    Generates bounding boxes (bbox) from visual signals.
    """

    MAPBOX_GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"

    def __init__(self):
        self.mapbox_token = os.getenv("MAPBOX_ACCESS_TOKEN")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "GeoSignal/1.0"})

    def from_plate(self, plate_data: dict) -> BBox:
        return BBox(
            min_lat=plate_data["min_lat"],
            max_lat=plate_data["max_lat"],
            min_lon=plate_data["min_lon"],
            max_lon=plate_data["max_lon"],
            label=plate_data.get("label", "Plate Region")
        )

    def from_mapbox(self, landmark_name: str, parent_bbox: Optional[BBox] = None) -> Optional[BBox]:
        """
        Geocode landmark via Mapbox Forward Geocoding, clip to parent_bbox.
        """
        if not self.mapbox_token:
            print("⚠️ MAPBOX_ACCESS_TOKEN missing, cannot geocode landmark")
            return None

        url = self.MAPBOX_GEOCODE_URL.format(query=quote(landmark_name))
        params = {
            "access_token": self.mapbox_token,
            "country": "id",
            "limit": 1,
            "language": "id"
        }

        if parent_bbox:
            params["bbox"] = f"{parent_bbox.min_lon},{parent_bbox.min_lat},{parent_bbox.max_lon},{parent_bbox.max_lat}"

        try:
            response = self.session.get(url, params=params, timeout=8)
            response.raise_for_status()
            features = response.json().get("features", [])

            if not features:
                return None

            lon, lat = features[0]["geometry"]["coordinates"]
            return self.expand_bbox(lat, lon, 1.5, label=landmark_name)
        except Exception:
            return None

    def expand_bbox(self, lat: float, lon: float, radius_km: float, label: str = "") -> BBox:
        deg_lat = radius_km / 111.0
        deg_lon = radius_km / (111.0 * math.cos(math.radians(lat)))
        
        return BBox(
            min_lat=lat - deg_lat,
            max_lat=lat + deg_lat,
            min_lon=lon - deg_lon,
            max_lon=lon + deg_lon,
            label=label
        )

    def intersect(self, bbox1: BBox, bbox2: BBox) -> BBox:
        return BBox(
            min_lat=max(bbox1.min_lat, bbox2.min_lat),
            max_lat=min(bbox1.max_lat, bbox2.max_lat),
            min_lon=max(bbox1.min_lon, bbox2.min_lon),
            max_lon=min(bbox1.max_lon, bbox2.max_lon),
            label=f"Intersection of {bbox1.label} and {bbox2.label}"
        )

    def to_bbox_string(self, bbox: BBox) -> str:
        """Format: 'min_lat,min_lon,max_lat,max_lon'"""
        return f"{bbox.min_lat:.6f},{bbox.min_lon:.6f},{bbox.max_lat:.6f},{bbox.max_lon:.6f}"

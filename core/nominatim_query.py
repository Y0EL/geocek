import os
import time
import requests
from typing import List, Dict, Optional

class NominatimQuery:
    """
    Multi-source geocoder untuk jalan lokal Indonesia.

    Priority chain:
    1. OpenCage   — aggregates OSM + multiple sources, terbaik untuk Indonesia, 2500 req/hari gratis
    2. Nominatim  — OSM-based, fallback kalau OpenCage tidak ada key
    3. Overpass   — query langsung OSM ways, fallback terakhir
    """

    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
    OVERPASS_URL  = "https://overpass-api.de/api/interpreter"
    OPENCAGE_URL  = "https://api.opencagedata.com/geocode/v1/json"
    USER_AGENT    = "GeoSignal-OSINT/1.0 (research tool)"

    def __init__(self):
        self._last_nominatim_req = 0.0
        self.opencage_key = os.getenv("OPENCAGE_API_KEY", "")

    # ── Nominatim ─────────────────────────────────────────────────────────────

    def _rate_limit(self):
        """Nominatim ToS: max 1 req/sec."""
        elapsed = time.time() - self._last_nominatim_req
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)
        self._last_nominatim_req = time.time()

    def geocode_nominatim(
        self,
        query:        str,
        countrycodes: str = "id",
        limit:        int = 5,
        viewbox:      Optional[str] = None,  # "min_lon,min_lat,max_lon,max_lat"
    ) -> List[Dict]:
        self._rate_limit()
        try:
            params: Dict = {
                "q":              query,
                "format":         "json",
                "limit":          limit,
                "countrycodes":   countrycodes,
                "addressdetails": 1,
            }
            if viewbox:
                params["viewbox"] = viewbox
                params["bounded"] = 1

            r = requests.get(
                self.NOMINATIM_URL,
                params=params,
                headers={"User-Agent": self.USER_AGENT},
                timeout=12,
            )
            r.raise_for_status()

            results = []
            for item in r.json():
                addr  = item.get("address", {})
                parts = [
                    item.get("name", ""),
                    addr.get("suburb") or addr.get("neighbourhood") or "",
                    addr.get("city_district") or addr.get("county") or "",
                    addr.get("city") or addr.get("town") or "",
                    addr.get("state", ""),
                ]
                display = ", ".join(p for p in parts if p)
                results.append({
                    "lat":        float(item["lat"]),
                    "lon":        float(item["lon"]),
                    "name":       display or item.get("display_name", query),
                    "type":       "way",
                    "osm_id":     item.get("osm_id", 0),
                    "source":     "nominatim",
                    "importance": float(item.get("importance", 0)),
                    "osm_class":  item.get("class", ""),
                })

            print(f"[Nominatim] '{query}' → {len(results)} results")
            return results

        except Exception as e:
            print(f"[!] Nominatim error for '{query}': {e}")
            return []

    # ── Overpass API ──────────────────────────────────────────────────────────

    def geocode_overpass(
        self,
        street_name: str,
        city:        str = "Jakarta",
    ) -> List[Dict]:
        """
        Query Overpass API untuk OSM ways dengan nama jalan tertentu.
        Jauh lebih presisi dari Nominatim untuk road-level geocoding.
        Mendapat center coordinate dari actual road geometry.
        """
        # Bersihkan nama: hapus "Jl." / "Jalan" prefix untuk regex matching
        clean = street_name
        for prefix in ["Jalan ", "Jl. ", "Jln. ", "jalan ", "jl. "]:
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
                break

        # Overpass QL: cari way bernama X di area kota
        query = f"""
[out:json][timeout:20];
area[name="{city}"]["boundary"="administrative"]->.searchArea;
(
  way["name"~"{clean}"]["highway"](area.searchArea);
  way["name"~"[Jj]alan {clean}"]["highway"](area.searchArea);
);
out center;
"""
        try:
            r = requests.post(
                self.OVERPASS_URL,
                data={"data": query},
                timeout=25,
            )
            r.raise_for_status()
            elements = r.json().get("elements", [])

            results = []
            seen = set()
            for el in elements:
                center = el.get("center") or {}
                lat = center.get("lat") or el.get("lat")
                lon = center.get("lon") or el.get("lon")
                if not lat or not lon:
                    continue
                key = (round(lat, 3), round(lon, 3))
                if key in seen:
                    continue
                seen.add(key)
                tags = el.get("tags", {})
                name = tags.get("name") or tags.get("name:id") or street_name
                results.append({
                    "lat":        lat,
                    "lon":        lon,
                    "name":       f"{name}, {city}",
                    "type":       "way",
                    "osm_id":     el.get("id", 0),
                    "source":     "overpass",
                    "importance": 0.9,
                    "osm_class":  tags.get("highway", ""),
                })

            print(f"[Overpass]  '{street_name}' in {city} → {len(results)} segments")
            return results[:5]

        except Exception as e:
            print(f"[!] Overpass error for '{street_name}': {e}")
            return []

    # ── OpenCage ──────────────────────────────────────────────────────────────

    def geocode_opencage(
        self,
        query:   str,
        country: str = "id",
        limit:   int = 5,
        bounds:  Optional[str] = None,  # "min_lon,min_lat,max_lon,max_lat"
    ) -> List[Dict]:
        """
        OpenCage Geocoder — aggregates OSM + Wikidata + other sources.
        2500 req/hari gratis. Lebih akurat dari Nominatim solo untuk Indonesia.
        Daftar: https://opencagedata.com/
        """
        if not self.opencage_key:
            return []

        try:
            params: Dict = {
                "q":           query,
                "key":         self.opencage_key,
                "countrycode": country,
                "limit":       limit,
                "no_annotations": 1,
                "language":    "id",
            }
            if bounds:
                params["bounds"] = bounds  # "min_lon,min_lat,max_lon,max_lat"

            r = requests.get(self.OPENCAGE_URL, params=params, timeout=12)
            r.raise_for_status()

            results = []
            for item in r.json().get("results", []):
                geom       = item.get("geometry", {})
                components = item.get("components", {})
                lat = geom.get("lat")
                lon = geom.get("lng")
                if not lat or not lon:
                    continue

                # Bangun display name dari components
                parts = [
                    components.get("road") or components.get("pedestrian") or "",
                    components.get("suburb") or components.get("neighbourhood") or "",
                    components.get("city_district") or "",
                    components.get("city") or components.get("town") or "",
                    components.get("state") or "",
                ]
                display = ", ".join(p for p in parts if p)

                results.append({
                    "lat":        float(lat),
                    "lon":        float(lon),
                    "name":       display or item.get("formatted", query),
                    "type":       "way",
                    "osm_id":     item.get("annotations", {}).get("OSM", {}).get("url", "0").split("/")[-1],
                    "source":     "opencage",
                    "importance": item.get("confidence", 5) / 10.0,
                    "osm_class":  components.get("_type", ""),
                })

            print(f"[OpenCage]  '{query}' → {len(results)} results")
            return results

        except Exception as e:
            print(f"[!] OpenCage error for '{query}': {e}")
            return []

    # ── Combined search ───────────────────────────────────────────────────────

    def search_street(
        self,
        query:     str,
        bbox_str:  Optional[str] = None,  # "min_lat,min_lon,max_lat,max_lon"
        city_hint: str = "Jakarta",
    ) -> List[Dict]:
        """
        Priority chain: OpenCage → Nominatim → Overpass
        """
        # Convert bbox ke format masing-masing API
        viewbox = None   # Nominatim: "minLon,minLat,maxLon,maxLat"
        bounds  = None   # OpenCage:  "minLon,minLat,maxLon,maxLat"
        if bbox_str:
            p = bbox_str.split(",")
            if len(p) == 4:
                minlat, minlon, maxlat, maxlon = p
                viewbox = f"{minlon},{minlat},{maxlon},{maxlat}"
                bounds  = f"{minlon},{minlat},{maxlon},{maxlat}"

        # 1. OpenCage (terbaik)
        results = self.geocode_opencage(query, bounds=bounds)

        # 2. Nominatim fallback
        if not results:
            results = self.geocode_nominatim(query, viewbox=viewbox)

        # 3. Overpass fallback (query langsung ke OSM way geometry)
        if not results:
            street_part = query.split(",")[0].strip()
            results = self.geocode_overpass(street_part, city=city_hint)

        # Deduplicate ~200m grid
        seen, deduped = set(), []
        for r in results:
            key = (round(r["lat"], 3), round(r["lon"], 3))
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        return deduped

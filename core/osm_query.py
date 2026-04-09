import os
import requests
from typing import List, Dict, Optional
from urllib.parse import quote

class OSMQueryEngine:
    """
    Geocek — Mapbox-powered geocoder with multi-strategy query approach.
    Tries queries in priority order and aggregates results.
    """

    MAPBOX_GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"

    def __init__(self):
        self.mapbox_token = os.getenv("MAPBOX_ACCESS_TOKEN")
        if not self.mapbox_token:
            print("⚠️ MAPBOX_ACCESS_TOKEN missing — geocoding will fail!")

    def query_hospital(self, name_pattern: str, bbox_str: str) -> List[Dict]:
        clean_name = name_pattern.replace('.*', '').replace('^', '').replace('$', '')
        return self.geocode(clean_name, bbox_str)

    def query_road_intersection(self, bbox_str: str, highway_types: List[str], lanes: Optional[str] = None) -> List[Dict]:
        return []

    def query_multi_poi(self, poi_list: List[Dict], bbox_str: str, max_distance_m: float = 500.0) -> List[Dict]:
        if not poi_list:
            return []
        primary = poi_list[0]
        if primary["type"] == "hospital":
            return self.query_hospital(primary["name"], bbox_str)
        return []

    def search_proximity_cluster(self, poi_a: str, poi_b: str, bbox_str: str, radius_m: float = 200.0) -> List[Dict]:
        """
        Pencarian kluster: Cari POI A dan POI B, kembalikan titik A yang memiliki B di dekatnya.
        Sangat berguna untuk kasus "Comet" dekat "Kantor Pos".
        """
        results_a = self.geocode(poi_a, bbox_str)
        results_b = self.geocode(poi_b, bbox_str)
        
        if not results_a or not results_b:
            return []
            
        clusters = []
        for ra in results_a:
            for rb in results_b:
                dist = self._haversine(ra["lat"], ra["lon"], rb["lat"], rb["lon"])
                if dist <= radius_m:
                    ra["is_cluster"] = True
                    ra["cluster_with"] = rb["name"]
                    ra["cluster_dist"] = round(dist, 1)
                    clusters.append(ra)
                    break
        
        print(f"[Proximity] Found {len(clusters)} clusters for '{poi_a}' near '{poi_b}'")
        return clusters

    def _haversine(self, lat1, lon1, lat2, lon2) -> float:
        import math
        R = 6371000  # meter
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def search_all(self, query_groups: Dict[str, List[str]], bbox_str: str) -> List[Dict]:
        """
        Enhanced multi-strategy search. Accepts a dict of priority groups:
        {
          "street": ["Jl. Pluit Selatan, Pluit", "Jl. Pluit Selatan"],
          "landmark": ["Superindo, Pluit", "Superindo"],
          "poi": ["Bank BNI, Penjaringan", ...],
          "text": ["Transjakarta Koridor 9", ...]
        }
        Returns deduplicated results, sorted by search priority.
        """
        all_results = []
        seen_coords = set()

        priority_order = ["street", "landmark", "poi", "text"]

        for group in priority_order:
            queries = query_groups.get(group, [])
            group_results = []

            for query in queries:
                if not query or len(query.strip()) < 3:
                    continue
                results = self.geocode(query, bbox_str)
                for r in results:
                    # Deduplicate by rounded coordinate (within ~100m)
                    coord_key = (round(r["lat"], 3), round(r["lon"], 3))
                    if coord_key not in seen_coords:
                        seen_coords.add(coord_key)
                        r["query_group"] = group
                        r["query_used"] = query
                        group_results.append(r)

            all_results.extend(group_results)

            # Untuk street group: kalau query paling spesifik (index 0) sudah return hasil,
            # skip group lain tapi tetap ambil semua hasil dari street queries
            if group_results and group == "street":
                break  # Ada street match — skip landmark/poi/text

        return all_results

    def geocode(self, query: str, bbox_str: str = None, proximity_latlon: tuple = None) -> list:
        """Geocode query using Mapbox Forward Geocoding API."""
        if not self.mapbox_token:
            print("[!] No MAPBOX_ACCESS_TOKEN, cannot geocode")
            return []

        try:
            print(f"[*] Mapbox geocoding: '{query}'")
            url = self.MAPBOX_GEOCODE_URL.format(query=quote(query))
            params = {
                "access_token": self.mapbox_token,
                "country": "id",
                "limit": 5,
                "language": "id",
                "types": "address,poi,place,locality,neighborhood"
            }

            # Apply bbox constraint if provided (min_lat,min_lon,max_lat,max_lon)
            if bbox_str:
                parts = bbox_str.split(",")
                if len(parts) == 4:
                    min_lat, min_lon, max_lat, max_lon = map(float, parts)
                    params["bbox"] = f"{min_lon},{min_lat},{max_lon},{max_lat}"

            # Apply proximity bias (Mapbox proximity=lon,lat biases results toward this point)
            if proximity_latlon:
                params["proximity"] = f"{proximity_latlon[1]},{proximity_latlon[0]}"

            r = requests.get(url, params=params, timeout=8)
            r.raise_for_status()
            features = r.json().get("features", [])

            results = []
            for f in features:
                lon, lat = f["geometry"]["coordinates"]
                results.append({
                    "lat": lat,
                    "lon": lon,
                    "name": f.get("place_name", f.get("text", query)),
                    "text": f.get("text", ""),
                    "type": "node",
                    "osm_id": 0,
                    "source": "mapbox"
                })

            print(f"[✓] Mapbox returned {len(results)} results for '{query}'")
            return results

        except Exception as e:
            print(f"[!] Mapbox geocoding failed for '{query}': {e}")
            return []

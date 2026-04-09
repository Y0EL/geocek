import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import os

@dataclass
class SignalBundle:
    plate_bbox: Optional[Dict] = None
    landmark_queries: List[str] = field(default_factory=list)
    street_queries: List[str] = field(default_factory=list)
    poi_queries: List[str] = field(default_factory=list)
    text_queries: List[str] = field(default_factory=list)
    area_context: Dict = field(default_factory=dict)
    road_constraints: Dict = field(default_factory=dict)
    infrastructure: Dict = field(default_factory=dict)
    signal_weights: Dict = field(default_factory=dict)
    confidence_initial: float = 0.0
    building_number: Optional[str] = None
    commercial_slogan: Optional[str] = None
    proximity_indicators: List[str] = field(default_factory=list)

class SignalParser:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.plate_map = self._load_data("plate_regions.json")
        self.hospital_aliases = self._load_data("hospital_aliases.json")

    def _load_data(self, filename: str) -> Dict:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), self.data_dir, filename)
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def parse(self, input_data: Dict) -> SignalBundle:
        geo = input_data.get("geo_signals", {})
        bundle = SignalBundle()

        # 1. Plate Prefix → BBox
        plate_prefix = geo.get("plate_prefix")
        if plate_prefix and plate_prefix in self.plate_map:
            bundle.plate_bbox = self.plate_map[plate_prefix]

        # 2. Street name queries (highest priority — very precise)
        street_name = geo.get("street_name")
        cross_street = geo.get("cross_street")
        junction_name = geo.get("junction_name")
        area_name = geo.get("area_name", "")
        city_district = geo.get("city_district", "")
        province = geo.get("province", "")

        if street_name:
            # Expand "Jl." → "Jalan" untuk akurasi Mapbox lebih baik
            full_name = street_name
            if street_name.lower().startswith("jl."):
                full_name = "Jalan" + street_name[3:]
            elif street_name.lower().startswith("jln."):
                full_name = "Jalan" + street_name[4:]

            # Urutkan dari paling spesifik (dengan konteks) ke paling umum
            if city_district and province:
                bundle.street_queries.append(f"{full_name}, {city_district}, {province}")
            if area_name and province:
                bundle.street_queries.append(f"{full_name}, {area_name}, {province}")
            if city_district:
                bundle.street_queries.append(f"{full_name}, {city_district}")
            if area_name:
                bundle.street_queries.append(f"{full_name}, {area_name}")
            # Province-only fallback (when city_district & area_name both null)
            if province and not city_district and not area_name:
                bundle.street_queries.append(f"{full_name}, {province}")
            bundle.street_queries.append(full_name)
            if full_name != street_name:
                bundle.street_queries.append(street_name)  # fallback ke original
        if cross_street:
            bundle.street_queries.append(cross_street)
        if junction_name:
            bundle.street_queries.append(junction_name)

        # 3. Landmark queries
        landmark_sign = geo.get("landmark_sign")
        if landmark_sign:
            bundle.landmark_queries = self.normalize_landmark(landmark_sign)
            if area_name:
                bundle.landmark_queries.append(f"{landmark_sign}, {area_name}")

        # 4. POI queries (all visible POIs)
        poi_list = geo.get("poi_list", [])
        for poi in poi_list:
            if poi and poi not in bundle.landmark_queries:
                bundle.poi_queries.append(poi)
                if area_name:
                    bundle.poi_queries.append(f"{poi}, {area_name}")

        # 5. Text queries (OCR visible texts)
        visible_texts = geo.get("visible_texts", [])
        for text in visible_texts:
            if text and len(text) > 3 and text not in bundle.street_queries:
                # Filter teks yang kemungkinan bukan nama lokasi (angka, simbol, dll)
                if not text.startswith("[REFLEKSI]") and not text.isdigit():
                    bundle.text_queries.append(text)

        # 5b. Teks refleksi cermin — bisa berisi nama jalan sisi berlawanan
        reflection_texts = geo.get("reflection_texts", [])
        for rt in reflection_texts:
            if rt and len(rt) > 3:
                clean_rt = rt.replace("[REFLEKSI]", "").strip()
                if clean_rt and clean_rt not in bundle.street_queries:
                    bundle.text_queries.insert(0, clean_rt)  # prioritaskan

        # 5c. RT/RW/Kelurahan sign — SANGAT spesifik, jadikan landmark query
        rw_rt_sign = geo.get("rw_rt_sign")
        if rw_rt_sign:
            bundle.landmark_queries.insert(0, rw_rt_sign)

        # 6. Waterway as landmark (very specific)
        waterway_name = geo.get("waterway_name")
        if waterway_name:
            bundle.landmark_queries.append(waterway_name)

        # 7. Transjakarta corridor (extremely specific)
        transjakarta_corridor = geo.get("transjakarta_corridor")
        transjakarta_halte = geo.get("transjakarta_halte")
        if transjakarta_halte:
            bundle.poi_queries.insert(0, f"Halte Transjakarta {transjakarta_halte}")
        elif transjakarta_corridor:
            bundle.poi_queries.insert(0, f"Transjakarta Koridor {transjakarta_corridor}")

        bundle.area_context = {
            "area_name": area_name,
            "city_district": city_district,
            "province": province,
            "waterway_name": waterway_name,
        }

        # 8b. Building number & slogans
        bundle.building_number = geo.get("building_number")
        bundle.commercial_slogan = geo.get("commercial_slogan")
        bundle.proximity_indicators = geo.get("proximity_indicators", [])

        # 8c. Enhanced POI queries with building number & slogan
        if bundle.building_number:
            for poi in bundle.poi_queries[:2]: # only first 2 for brevity
                if area_name:
                    bundle.poi_queries.append(f"{poi} {bundle.building_number}, {area_name}")
                bundle.poi_queries.append(f"{poi} {bundle.building_number}")
        
        if bundle.commercial_slogan:
            bundle.poi_queries.append(bundle.commercial_slogan)
            if area_name:
                bundle.poi_queries.append(f"{bundle.commercial_slogan}, {area_name}")

        # 9. Road constraints
        bundle.road_constraints = self.build_road_filter(
            geo.get("road_type"),
            geo.get("road_lanes")
        )

        # 10. Infrastructure flags (all of them)
        bundle.infrastructure = {
            "median": geo.get("median_present", False),
            "median_type": geo.get("median_type"),
            "traffic_light": geo.get("traffic_light_present", False),
            "sidewalk": geo.get("sidewalk_present", False),
            "infrastructure_type": geo.get("infrastructure_type"),
            "water_body": geo.get("water_body_visible", False),
            "camera_heading": geo.get("camera_heading"),
            "shadow_direction": geo.get("shadow_direction"),
            "time_of_day": geo.get("time_of_day"),
            "commercial_density": geo.get("commercial_density"),
            "area_type": geo.get("area_type"),
            "transjakarta_corridor": transjakarta_corridor,
            "building_number": bundle.building_number,
            "commercial_slogan": bundle.commercial_slogan,
            "proximity_indicators": bundle.proximity_indicators
        }

        # 11. Weights — more signals = higher confidence
        bundle.signal_weights = self.calculate_weights(geo)

        # 12. Initial confidence
        if bundle.signal_weights:
            bundle.confidence_initial = sum(bundle.signal_weights.values()) / len(bundle.signal_weights)

        return bundle

    def normalize_landmark(self, raw_text: str) -> List[str]:
        queries = [raw_text]
        if raw_text in self.hospital_aliases:
            queries.extend(self.hospital_aliases[raw_text])
        elif "RS " in raw_text:
            alt = raw_text.replace("RS ", "Rumah Sakit ")
            queries.append(alt)
        return list(dict.fromkeys(queries))  # deduplicate preserving order

    def build_road_filter(self, road_type: Optional[str], lanes: Optional[int]) -> Dict:
        ROAD_TYPE_MAP = {
            "arteri_primer": ["primary", "trunk"],
            "arteri_sekunder": ["secondary"],
            "tol": ["motorway"],
            "lingkungan": ["residential", "tertiary"]
        }
        return {
            "highway": ROAD_TYPE_MAP.get(road_type, ["primary"]),
            "lanes": str(lanes) if lanes else None
        }

    def calculate_weights(self, geo: Dict) -> Dict:
        weights = {}

        # Tier 1: Highly precise location signals
        if geo.get("street_name"):
            weights["street"] = 0.95
        if geo.get("cross_street"):
            weights["cross_street"] = 0.90
        if geo.get("junction_name"):
            weights["junction"] = 0.88
        if geo.get("transjakarta_halte"):
            weights["transjakarta_halte"] = 0.85
        elif geo.get("transjakarta_corridor"):
            weights["transjakarta_corridor"] = 0.80
        if geo.get("waterway_name"):
            weights["waterway"] = 0.75

        # Tier 2: Area / region signals
        if geo.get("plate_prefix"):
            weights["plate"] = 0.90
        if geo.get("landmark_sign"):
            weights["landmark"] = 0.85
        if geo.get("area_name"):
            weights["area"] = 0.70
        if geo.get("city_district"):
            weights["district"] = 0.65

        # Tier 3: Infrastructure signals
        if geo.get("infrastructure_type") and geo.get("infrastructure_type") != "normal_road":
            weights["infrastructure"] = 0.60
        if geo.get("water_body_visible"):
            weights["water_body"] = 0.55
        if geo.get("road_type"):
            weights["road"] = 0.45
        if geo.get("median_present"):
            weights["median"] = 0.30
        if geo.get("traffic_light_present"):
            weights["traffic_light"] = 0.20
        if geo.get("sidewalk_present"):
            weights["sidewalk"] = 0.15

        # Tier 4: Contextual signals
        if geo.get("visible_texts"):
            weights["ocr_texts"] = 0.50
        if geo.get("poi_list"):
            weights["poi"] = 0.40

        # Tier 5: Sinyal baru (field 12-17)
        if geo.get("rw_rt_sign"):
            weights["rw_rt_sign"] = 0.95      # sangat spesifik — langsung ke kelurahan
        if geo.get("pln_pole_code"):
            weights["pln_pole_code"] = 0.85   # unik per cluster distribusi
        if geo.get("reflection_texts"):
            weights["reflection"] = 0.70       # sisi jalan yang tidak terlihat langsung
        if geo.get("gps_from_metadata"):
            weights["gps_metadata"] = 1.0      # GPS dari EXIF = ground truth
        if geo.get("road_marking_color"):
            weights["road_marking"] = 0.40     # kuning=nasional, putih=kota
        if geo.get("manhole_brand"):
            weights["manhole"] = 0.55          # PAM Jaya hanya Jakarta, PDAM per kota
        if geo.get("vegetation_species"):
            weights["vegetation_species"] = 0.35
        if geo.get("shadow_length_ratio"):
            weights["shadow_ratio"] = 0.30     # estimasi lintang dari bayangan
        
        # Tier 6: High-precision details
        if geo.get("building_number"):
            weights["building_number"] = 0.85
        if geo.get("commercial_slogan"):
            weights["slogan"] = 0.60
        if geo.get("proximity_indicators"):
            weights["proximity"] = 0.80

        return weights

import math
from typing import Dict, List, Any
from .signal_parser import SignalBundle

class ConfidenceScorer:
    """
    Geocek — Calculates confidence score for each candidate location.
    Score 0.0 to 1.0.
    """

    def score_candidate(self,
                        candidate: Dict,
                        signal_bundle: SignalBundle,
                        query_results: Dict[str, List],
                        weight_overrides: Dict[str, float] = None) -> float:
        """
        Computes weighted sum of matching signals:
        score = Σ (signal_weight[i] × match_score[i]) / Σ signal_weight[i]

        weight_overrides: dict dari multicheck CP2 adjustedWeights (field → multiplier)
        """
        weights = dict(signal_bundle.signal_weights)

        # Terapkan multicheck weight overrides
        if weight_overrides:
            for field, mult in weight_overrides.items():
                # Map field name ke signal key yang dipakai scorer
                if field in ("street_name",) and "street" in weights:
                    weights["street"] = weights["street"] * mult
                elif field in ("landmark_sign",) and "landmark" in weights:
                    weights["landmark"] = weights["landmark"] * mult
                elif field in ("plate_prefix",) and "plate" in weights:
                    weights["plate"] = weights["plate"] * mult
        total_weight = sum(weights.values())
        weighted_score = 0.0

        if total_weight == 0:
            return 0.0

        # Plate prefix match region
        if "plate" in weights:
            if signal_bundle.plate_bbox:
                pb = signal_bundle.plate_bbox
                if pb["min_lat"] <= candidate["lat"] <= pb["max_lat"] and \
                   pb["min_lon"] <= candidate["lon"] <= pb["max_lon"]:
                    weighted_score += weights["plate"] * 1.0

        # Landmark match and distance
        if "landmark" in weights:
            landmark_match = False
            # Check if candidate name matches any landmark queries
            for q in signal_bundle.landmark_queries:
                if q.lower() in candidate.get("name", "").lower():
                    landmark_match = True
                    break
            
            if landmark_match:
                weighted_score += weights["landmark"] * 1.0
            else:
                # Proximity decay (if other landmarks exist nearby)
                max_prox = 0.0
                for lm in query_results.get("hospitals", []):
                    dist = self._haversine_distance(candidate["lat"], candidate["lon"], lm["lat"], lm["lon"])
                    max_prox = max(max_prox, self.distance_decay(dist))
                weighted_score += weights["landmark"] * max_prox

        # Road type match
        if "road" in weights:
            # Check if road type matches
            if candidate.get("highway") in signal_bundle.road_constraints.get("highway", []):
                weighted_score += weights["road"] * 1.0

        # Street name match — candidate name contains any street query
        # Ini penting untuk Nominatim results yang punya nama jalan di display_name
        street_weight = weights.get("street", 0.85)
        if street_weight > 0 and signal_bundle.street_queries:
            cand_name_lower = candidate.get("name", "").lower()
            for sq in signal_bundle.street_queries:
                # Ambil bagian pertama query (nama jalan saja, tanpa ", Pasar Minggu")
                street_part = sq.split(",")[0].lower().strip()
                if street_part and street_part in cand_name_lower:
                    weighted_score += street_weight * 1.0
                    break

        # District/province match — kasih partial credit untuk area yang benar
        area_ctx = signal_bundle.area_context
        cand_name_lower = candidate.get("name", "").lower()
        area_signals = [
            area_ctx.get("city_district", ""),
            area_ctx.get("area_name", ""),
            area_ctx.get("province", ""),
        ]
        area_matches = sum(1 for a in area_signals if a and a.lower() in cand_name_lower)
        if area_matches > 0:
            # Partial credit: 0.1 per area match, max 0.3
            weighted_score += min(0.3, area_matches * 0.1) * total_weight

        # ── [NEW] Phase 4 Enhancements ─────────────────────────────────────────
        
        # 1. Building number match
        if "building_number" in weights and signal_bundle.building_number:
            num = signal_bundle.building_number.lower()
            if num in candidate.get("name", "").lower():
                weighted_score += weights["building_number"] * 1.0
        
        # 2. Proximity cluster match
        if "proximity" in weights and candidate.get("is_cluster"):
            weighted_score += weights["proximity"] * 1.0
            
        # 3. Slogan match
        if "slogan" in weights and signal_bundle.commercial_slogan:
            slogan = signal_bundle.commercial_slogan.lower()
            if slogan in candidate.get("name", "").lower():
                weighted_score += weights["slogan"] * 1.0

        return min(1.0, weighted_score / total_weight)

    def distance_decay(self, distance_m: float, max_m: float = 500.0) -> float:
        """
        Exponential score decay with distance.
        """
        if distance_m >= max_m:
            return 0.0
        lam = 5.0 / max_m
        return math.exp(-lam * distance_m)

    def classify_confidence(self, score: float) -> str:
        if score > 0.80:
            return "HIGH — lokasi sangat probable"
        elif score > 0.60:
            return "MEDIUM — lokasi probable, perlu verifikasi"
        elif score > 0.40:
            return "LOW — perlu konfirmasi tambahan"
        else:
            return "VERY LOW — sinyal tidak cukup"

    def estimate_radius(self, score: float) -> int:
        if score > 0.80:
            return 200
        elif score > 0.60:
            return 500
        elif score > 0.40:
            return 1500
        else:
            return 5000

    def _haversine_distance(self, lat1, lon1, lat2, lon2) -> float:
        R = 6371000  # meter
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        
        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

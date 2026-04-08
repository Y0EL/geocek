from typing import List, Dict, Any

class ConstraintFilter:
    """
    Intersection rules for finding the most probable location.
    """

    def apply_constraints(self, list1: List[Dict], list2: List[Dict], max_dist_m: float = 500.0) -> List[Dict]:
        """Intersect two sets of candidates based on spatial proximity."""
        intersections = []
        for c1 in list1:
            for c2 in list2:
                dist = self._haversine_distance(c1["lat"], c1["lon"], c2["lat"], c2["lon"])
                if dist < max_dist_m:
                    intersections.append({
                        **c1,
                        "matched_with": c2,
                        "match_distance": dist
                    })
        return intersections

    def _haversine_distance(self, lat1, lon1, lat2, lon2) -> float:
        import math
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

import os
import json
from typing import List, Dict, Any
from dataclasses import dataclass
from .signal_parser import SignalBundle

@dataclass
class ScoredCandidate:
    lat: float
    lon: float
    name: str
    confidence_score: float
    confidence_label: str
    radius_m: int
    matched_signals: List[str]
    osm_id: int
    osm_type: str
    ai_reasoning: str = ""

class OutputBuilder:
    """
    Generates reports and visualizations for geolocation candidates.
    """

    def to_geojson(self, candidates: List[ScoredCandidate]) -> Dict:
        features = []
        for cand in candidates:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [cand.lon, cand.lat]
                },
                "properties": {
                    "name": cand.name,
                    "confidence_score": round(cand.confidence_score, 2),
                    "confidence_label": cand.confidence_label,
                    "radius_m": cand.radius_m,
                    "matched_signals": cand.matched_signals,
                    "ai_reasoning": cand.ai_reasoning
                }
            })
        return {
            "type": "FeatureCollection",
            "features": features
        }

    def to_report(self, candidates: List[ScoredCandidate],
                  signal_bundle: SignalBundle, duration: float) -> str:
        report = []
        report.append("══════════════════════════════════════════════")
        report.append("🛰️  GEOCEK — HASIL ANALISIS LOKASI")
        report.append("══════════════════════════════════════════════")
        report.append(f"Input Signals   : {len(signal_bundle.signal_weights)} sinyal terdeteksi")
        report.append(f"Processing Time : {duration:.2f} detik")
        report.append(f"Candidates Found: {len(candidates)}")
        report.append("")

        for i, cand in enumerate(candidates, 1):
            report.append(f"┌─ KANDIDAT #{i} (CONFIDENCE: {cand.confidence_label} — {round(cand.confidence_score, 2)})")
            report.append(f"│  Koordinat    : {cand.lat}, {cand.lon}")
            report.append(f"│  Area         : {cand.name}")
            if cand.ai_reasoning:
                report.append(f"│  AI Reasoning : {cand.ai_reasoning}")
            report.append(f"│  Radius Error : ~{cand.radius_m} meter")
            report.append(f"│  Signal Match : {' | '.join(cand.matched_signals)}")
            report.append(f"│  Maps Verify  : https://osm.org/?mlat={cand.lat}&mlon={cand.lon}")
            report.append(f"└──────────────────────────────────────────")
            report.append("")

        return "\n".join(report)

    def to_mapbox_map(self, candidates: List[ScoredCandidate], output_path: str) -> str:
        """Generate a pure Mapbox GL JS interactive map (no Leaflet/Folium)."""
        mapbox_token = os.getenv("MAPBOX_ACCESS_TOKEN", "")

        center_lat = candidates[0].lat if candidates else -6.2088
        center_lon = candidates[0].lon if candidates else 106.8456

        # Build GeoJSON for circle layers (uncertainty radius)
        features_json = []
        for cand in candidates:
            features_json.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [cand.lon, cand.lat]},
                "properties": {
                    "name": cand.name,
                    "score": round(cand.confidence_score, 2),
                    "score_pct": round(cand.confidence_score * 100),
                    "label": cand.confidence_label,
                    "radius_m": cand.radius_m,
                    "reasoning": cand.ai_reasoning[:200] if cand.ai_reasoning else "",
                    "signals": ", ".join(cand.matched_signals),
                    "gmaps_url": f"https://www.google.com/maps/search/?api=1&query={cand.lat},{cand.lon}",
                    "color": self._confidence_color(cand.confidence_score)
                }
            })

        geojson_data = json.dumps({"type": "FeatureCollection", "features": features_json})

        # Markers JS: one mapboxgl.Marker per candidate
        markers_js_parts = []
        for i, cand in enumerate(candidates):
            color = self._confidence_color(cand.confidence_score)
            rank = "#1" if i == 0 else f"#{i+1}"
            reasoning_escaped = (cand.ai_reasoning[:150].replace("`", "'").replace("\n", " ") + "...") if cand.ai_reasoning else ""
            popup_html = (
                f"<div style='font-family:Public Sans,sans-serif;padding:12px;min-width:240px;'>"
                f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:8px;'>"
                f"<span style='background:{color};color:white;border-radius:50%;width:28px;height:28px;"
                f"display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:12px;'>{rank}</span>"
                f"<span style='font-weight:700;font-size:13px;'>{cand.name[:40]}</span></div>"
                f"<p style='margin:0 0 4px;font-size:13px;'><b style='color:{color};'>{round(cand.confidence_score*100)}%</b> — {cand.confidence_label}</p>"
                f"<p style='margin:0 0 4px;font-size:11px;color:#666;font-family:monospace;'>{cand.lat:.6f}, {cand.lon:.6f}</p>"
                f"<p style='margin:0 0 8px;font-size:11px;color:#888;'>{reasoning_escaped}</p>"
                f"<a href='https://www.google.com/maps/search/?api=1&query={cand.lat},{cand.lon}' "
                f"target='_blank' style='font-size:11px;color:#D97757;text-decoration:none;font-weight:600;'>Open in Google Maps ↗</a>"
                f"</div>"
            )
            markers_js_parts.append(
                f"new mapboxgl.Marker({{color:'{color}',scale:{1.2 if i == 0 else 0.9}}})"
                f".setLngLat([{cand.lon},{cand.lat}])"
                f".setPopup(new mapboxgl.Popup({{maxWidth:'320px',offset:25}}).setHTML(`{popup_html}`))"
                f".addTo(map);"
            )

        markers_js = "\n    ".join(markers_js_parts)

        html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.css" rel="stylesheet">
  <script src="https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ width: 100%; height: 100vh; overflow: hidden; }}
    #map {{ width: 100%; height: 100%; }}
    .mapboxgl-popup-content {{ border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.18); padding: 0; }}
  </style>
</head>
<body>
<div id="map"></div>
<script>
  mapboxgl.accessToken = '{mapbox_token}';

  const map = new mapboxgl.Map({{
    container: 'map',
    style: 'mapbox://styles/mapbox/satellite-streets-v12',
    center: [{center_lon}, {center_lat}],
    zoom: 17,
    pitch: 30,
    bearing: 0
  }});

  map.addControl(new mapboxgl.NavigationControl(), 'top-right');
  map.addControl(new mapboxgl.ScaleControl({{ maxWidth: 100, unit: 'metric' }}), 'bottom-left');
  map.addControl(new mapboxgl.FullscreenControl(), 'top-right');

  const geojsonData = {geojson_data};

  map.on('load', function() {{
    // Add uncertainty radius circles
    map.addSource('candidates', {{
      type: 'geojson',
      data: geojsonData
    }});

    map.addLayer({{
      id: 'radius-fill',
      type: 'circle',
      source: 'candidates',
      paint: {{
        'circle-radius': [
          'interpolate', ['linear'], ['zoom'],
          10, ['/', ['get', 'radius_m'], 100],
          15, ['/', ['get', 'radius_m'], 20],
          18, ['/', ['get', 'radius_m'], 5]
        ],
        'circle-color': ['get', 'color'],
        'circle-opacity': 0.12,
        'circle-stroke-width': 1.5,
        'circle-stroke-color': ['get', 'color'],
        'circle-stroke-opacity': 0.5
      }}
    }});

    // Add markers
    {markers_js}

    // Auto-open popup for top candidate
    if (geojsonData.features.length > 0) {{
      const first = geojsonData.features[0];
      // Fly smoothly to top candidate
      map.flyTo({{
        center: first.geometry.coordinates,
        zoom: 17,
        speed: 1.2
      }});
    }}
  }});
</script>
</body>
</html>"""

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        return output_path

    def _confidence_color(self, score: float) -> str:
        if score > 0.80: return "#22c55e"   # green
        if score > 0.60: return "#3b82f6"   # blue
        if score > 0.40: return "#f97316"   # orange
        return "#ef4444"                     # red

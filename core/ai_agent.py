import os
import json
import random
import config
import requests

from typing import Dict, List, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

class GeolocationAIAgent:
    def __init__(self, api_key: str):
        self.llm = ChatOpenAI(
            api_key=api_key,
            model="gpt-4o-mini",  # using a fast/cheap model to avoid high costs, can be gpt-4o
            temperature=0
        )

    def _get_surrounding_roads(self, lat: float, lon: float, radius: int = 150) -> List[Dict]:
        """Fetch high-precision road data using Mapbox Search & Tilequery API."""
        mapbox_token = os.getenv("MAPBOX_ACCESS_TOKEN")
        if not mapbox_token:
            print("⚠️ MAPBOX_ACCESS_TOKEN missing, cannot use Mapbox for reasoning!")
            return {"roads": [], "traffic_signals": []}

        # 1. Mapbox Reverse Geocoding (Fetch the primary road name at POI)
        rev_url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json"
        rev_params = {"access_token": mapbox_token, "types": "address,poi", "limit": 1}
        
        road_results = []
        try:
            r = requests.get(rev_url, params=rev_params, timeout=5)
            if r.status_code == 200:
                data = r.json()
                for feature in data.get('features', []):
                    road_results.append({
                        "name": feature.get('text', 'Main Road'),
                        "lat": feature['geometry']['coordinates'][1],
                        "lon": feature['geometry']['coordinates'][0],
                        "type": "primary_address"
                    })
        except: pass

        # 2. Mapbox Tilequery (Fetch nearby road infrastructure)
        # Layers searched: road (linestring)
        tile_url = f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/tilequery/{lon},{lat}.json"
        tile_params = {
            "access_token": mapbox_token,
            "radius": radius,
            "limit": 10,
            "layers": "road"
        }
        
        try:
            r = requests.get(tile_url, params=tile_params, timeout=5)
            if r.status_code == 200:
                data = r.json()
                for feature in data.get('features', []):
                    props = feature.get('properties', {})
                    road_results.append({
                        "name": props.get('name', 'Unnamed Road'),
                        "class": props.get('class', 'unknown'),
                        "oneway": props.get('oneway', 'unknown'),
                        "lat": feature['geometry']['coordinates'][1] if feature['geometry']['type'] == 'Point' else lat,
                        "lon": feature['geometry']['coordinates'][0] if feature['geometry']['type'] == 'Point' else lon,
                        "type": "road_segment"
                    })
        except Exception as e:
            print(f"⚠️ Mapbox Tilequery failed: {e}")

        return {"roads": road_results, "traffic_signals": []}



    def generate_not_found_joke(self, geo_signals: Dict) -> str:
        """
        Generate pesan lucu dalam Bahasa Indonesia ketika lokasi tidak bisa ditemukan.
        Disesuaikan dengan sinyal kecil yang berhasil diekstrak.
        """
        # Kumpulkan clue yang ada (meski minim) untuk bahan roasting
        clues = []
        if geo_signals.get("time_of_day"):      clues.append(f"waktu: {geo_signals['time_of_day']}")
        if geo_signals.get("weather"):          clues.append(f"cuaca: {geo_signals['weather']}")
        if geo_signals.get("area_type"):        clues.append(f"area: {geo_signals['area_type']}")
        if geo_signals.get("vegetation_type"):  clues.append(f"vegetasi: {geo_signals['vegetation_type']}")
        if geo_signals.get("road_lanes"):       clues.append(f"{geo_signals['road_lanes']} lajur")
        if geo_signals.get("visible_texts"):    clues.append(f"teks terlihat: {geo_signals['visible_texts'][:2]}")

        clue_str = ", ".join(clues) if clues else "hampir tidak ada clue sama sekali"

        prompt = f"""Kamu adalah asisten geolokasi yang humoris dan santai seperti teman ngobrol, bicara seperti anak muda Indonesia gaul.
Lokasi dari gambar yang diupload tidak berhasil ditemukan sama sekali.

Clue yang berhasil diekstrak (sangat minim): {clue_str}

Tulis SATU kalimat lucu dan relatable dalam Bahasa Indonesia (gaya santai/gaul, boleh pakai "wkwk", "anjir", "bro", dll).
Intinya: bercanda bahwa gambarnya terlalu misterius / tidak ada clue / mungkin diambil di tempat yang sangat personal.
Contoh gaya: "hmm ini ngambil di dapur kamu sendiri ya? soalnya gak nemu nih wkwkwk"

Jangan lebih dari 2 kalimat. Langsung output teksnya saja, tanpa tanda kutip."""

        try:
            response = self.llm.invoke([
                SystemMessage(content="Kamu adalah asisten geolokasi yang humoris. Balas singkat dan lucu dalam bahasa Indonesia gaul."),
                HumanMessage(content=prompt)
            ])
            return response.content.strip().strip('"').strip("'")
        except Exception:
            return "Wah bro, gambar ini terlalu misterius buat gue... mungkin ini diambil di dimensi lain? wkwkwk 🤷"

    def estimate_location_from_signals(self, geo_signals: Dict, full_data: Dict) -> List[Dict]:
        """
        Fallback ketika semua geocoder gagal: minta AI gunakan world knowledge untuk
        estimasi koordinat GPS langsung dari sinyal visual yang sudah diekstrak.
        """
        sig_summary = {k: v for k, v in geo_signals.items() if v not in (None, "", [], False)}

        prompt = f"""Kamu adalah Pakar Geolokasi OSINT tingkat militer, spesialis geografi Indonesia dan intelijen visual jalan.

Semua API geocoding mengembalikan nol hasil. Kamu harus gunakan pengetahuan internalmu tentang jalan, kelurahan, dan tata kota Indonesia untuk memperkirakan koordinat GPS.

SINYAL VISUAL YANG DIEKSTRAK:
{json.dumps(sig_summary, indent=2, ensure_ascii=False)}

DATA ANALISIS LENGKAP:
- Provinsi: {full_data.get('3_geolocation_signals', {}).get('province', geo_signals.get('province', 'tidak diketahui'))}
- Kota: {full_data.get('3_geolocation_signals', {}).get('city', geo_signals.get('city_district', 'tidak diketahui'))}
- Kecamatan: {full_data.get('3_geolocation_signals', {}).get('district_kecamatan', '')}
- Nama Jalan: {geo_signals.get('street_name', 'tidak diketahui')}
- Tipe Jalan: {geo_signals.get('road_type')}, {geo_signals.get('road_lanes')} lajur, {geo_signals.get('road_lanes_direction')} per arah
- Median: {geo_signals.get('median_present')}, Trotoar: {geo_signals.get('sidewalk_present')}
- Arah Kamera: {geo_signals.get('camera_heading')}, Arah Bayangan: {geo_signals.get('shadow_direction')}, Waktu: {geo_signals.get('time_of_day')}
- Tipe Area: {geo_signals.get('area_type')}, Kepadatan Komersial: {geo_signals.get('commercial_density')}
- Teks Terlihat: {geo_signals.get('visible_texts', [])}
- POI: {geo_signals.get('poi_list', [])}
- Tanda RT/RW: {geo_signals.get('rw_rt_sign')}
- Kode Tiang PLN: {geo_signals.get('pln_pole_code')}
- Teks Refleksi Cermin: {geo_signals.get('reflection_texts', [])}
- Marka Jalan: {geo_signals.get('road_marking_color')}
- Merek Gorong-gorong: {geo_signals.get('manhole_brand')}
- Spesies Vegetasi: {geo_signals.get('vegetation_species', [])}
- Reasoning AI Vision: {full_data.get('11_agent_reasoning', '')}

TUGASMU:
1. Gunakan pengetahuanmu tentang jalan/area ini untuk mengidentifikasi lokasi paling mungkin
2. Berikan 1-3 kandidat koordinat GPS dengan skor kepercayaan
3. Spesifik — gunakan pengetahuanmu tentang tata letak jalan Jakarta/Indonesia
4. Tulis reasoning dalam Bahasa Indonesia

Kembalikan HANYA array JSON valid (tanpa markdown, tanpa teks tambahan):
[
  {{
    "lat": -6.263100,
    "lon": 106.830800,
    "name": "Jl. Siaga Raya, Pejaten Barat, Pasar Minggu, Jakarta Selatan",
    "confidence": 0.80,
    "source": "ai_world_knowledge",
    "reasoning": "Jl. Siaga Raya adalah jalan kolektor yang dikenal di area Pejaten Barat/Pasar Minggu, Jakarta Selatan. Jalan ini membentang utara-selatan. Karakter residensial dan vegetasi urban sparse sesuai dengan area ini."
  }}
]"""

        try:
            response = self.llm.invoke([
                SystemMessage(content="You are a JSON-only geospatial intelligence agent. Output only valid JSON arrays."),
                HumanMessage(content=prompt)
            ])
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
            elif content.startswith("```"):
                content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]

            raw = json.loads(content.strip())
            results = []
            for item in raw:
                if "lat" in item and "lon" in item:
                    results.append({
                        "lat":        float(item["lat"]),
                        "lon":        float(item["lon"]),
                        "name":       item.get("name", "AI Estimated Location"),
                        "type":       "way",
                        "osm_id":     0,
                        "source":     "ai_world_knowledge",
                        "importance": float(item.get("confidence", 0.6)),
                        "ai_reasoning": item.get("reasoning", ""),
                    })
            print(f"[AI Estimate] World-knowledge fallback → {len(results)} candidates")
            return results
        except Exception as e:
            print(f"[!] AI estimate_location_from_signals failed: {e}")
            return []

    def refine_candidate(self, candidate: Dict, signals: Dict) -> Dict:
        """
        Gunakan LLM untuk mempersempit koordinat POI ke titik jalan/persimpangan
        yang paling cocok dengan sinyal visual.
        """
        poi_lat, poi_lon = candidate["lat"], candidate["lon"]
        surrounding_data = self._get_surrounding_roads(poi_lat, poi_lon)

        # Ringkas sinyal kunci untuk prompt yang lebih efisien
        key_signals = {k: v for k, v in signals.items()
                       if k in ("street_name","cross_street","junction_name","road_type",
                                "road_lanes","median_present","traffic_light_present",
                                "camera_heading","area_type","rw_rt_sign","pln_pole_code",
                                "reflection_texts","road_marking_color","manhole_brand",
                                "visible_texts","poi_list") and v not in (None, "", [], False)}

        prompt = f"""Kamu adalah Agen Geolokasi OSINT expert untuk Indonesia.
Kandidat lokasi ditemukan: "{candidate['name']}" di koordinat ({poi_lat}, {poi_lon}).
Namun foto diambil dari jalan di dekat lokasi ini, BUKAN dari dalam bangunan.

Sinyal visual dari foto:
{json.dumps(key_signals, indent=2, ensure_ascii=False)}

Data Mapbox Streets dalam radius 150m dari koordinat tersebut:
{json.dumps(surrounding_data, indent=2, ensure_ascii=False)}

TUGASMU:
Analisis data jalan dan temukan koordinat paling logis yang PALING COCOK dengan sinyal visual.
- Jika sinyal menunjukkan "traffic_light_present=true" → cari node traffic signal terdekat
- Jika ada "cross_street" atau "junction_name" → prioritaskan titik perpotongan
- Jika "road_lanes" spesifik → pastikan segmen jalan sesuai jumlah lajur
- Jika ada "rw_rt_sign" atau "pln_pole_code" → itu sinyal sangat spesifik, jadikan referensi utama

Balas HANYA dengan JSON valid berisi 'lat', 'lon', 'name', dan 'reasoning' dalam Bahasa Indonesia.
Contoh:
{{
  "lat": -6.126500,
  "lon": 106.793000,
  "name": "Simpang Jl. Pluit Raya",
  "reasoning": "Sinyal visual menunjukkan lampu merah pada jalan 4 lajur. Dipilih koordinat node traffic signal tepat di Jl. Pluit Raya yang sesuai dengan konfigurasi lajur dan median yang terlihat."
}}"""
        try:
            response = self.llm.invoke([
                SystemMessage(content="You are a JSON-only geospatial analysis agent."),
                HumanMessage(content=prompt)
            ])
            
            # Parse JSON from response
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:-3]
            elif content.startswith("```"):
                content = content[3:-3]
                
            refined_data = json.loads(content)
            
            # Update the candidate with the refined road coordinates
            refined_candidate = candidate.copy()
            refined_candidate["lat"] = refined_data["lat"]
            refined_candidate["lon"] = refined_data["lon"]
            refined_candidate["name"] = f"{refined_data['name']} (Near {candidate['name']})"
            refined_candidate["ai_reasoning"] = refined_data["reasoning"]
            return refined_candidate
            
        except Exception as e:
            print(f"AI Agent failed to refine coordinate: {e}")
            return candidate

import os
import json
import base64
import uuid
import subprocess
from flask import Flask, render_template, request, jsonify, send_file, url_for, redirect, session
from dotenv import load_dotenv

from core.ai_agent import GeolocationAIAgent
from layers.gatekeeper import GatekeeperLayer
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16 MB limit

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

VISION_MODEL = "gpt-4o"

def encode_image(image_path):
    """Encode gambar ke base64. Konversi RGBA→RGB otomatis agar kompatibel JPEG."""
    from PIL import Image
    import io
    img = Image.open(image_path)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# FASE 3: Image Metadata Extractor
# ─────────────────────────────────────────────────────────────────────────────
def extract_image_metadata(image_path: str) -> dict:
    """
    Ekstrak metadata tersembunyi dari gambar: EXIF, PNG chunks, software info.
    Berguna untuk screenshot yang masih menyimpan info device/app.
    """
    meta = {}
    try:
        from PIL import Image
        img = Image.open(image_path)
        info = img.info
        meta["format"] = img.format
        meta["size"]   = f"{img.size[0]}x{img.size[1]}"

        # ── PNG tEXt/iTXt chunks ──────────────────────────────────────────────
        if img.format == "PNG":
            for key in ["Software", "Comment", "Author", "Description",
                        "Creation Time", "Source", "copyright", "Title"]:
                if key in info:
                    meta[key.lower().replace(" ", "_")] = str(info[key])

        # ── JPEG EXIF via Pillow ──────────────────────────────────────────────
        try:
            exif_raw = img._getexif()  # type: ignore
            if exif_raw:
                TAG_MAP = {271: "device_make", 272: "device_model",
                           305: "software",    306: "datetime",
                           36867: "datetime_original"}
                for tag_id, name in TAG_MAP.items():
                    if tag_id in exif_raw:
                        meta[name] = str(exif_raw[tag_id])

                # GPS (tag 34853)
                gps_raw = exif_raw.get(34853)
                if gps_raw:
                    def _dms(dms):
                        return dms[0][0]/dms[0][1] + dms[1][0]/dms[1][1]/60 + dms[2][0]/dms[2][1]/3600
                    try:
                        lat = _dms(gps_raw[2]) * (-1 if gps_raw[1] == b'S' else 1)
                        lon = _dms(gps_raw[4]) * (-1 if gps_raw[3] == b'W' else 1)
                        meta["gps_lat"] = round(lat, 6)
                        meta["gps_lon"] = round(lon, 6)
                        print(f"[Metadata] GPS ditemukan: {lat:.6f}, {lon:.6f}")
                    except Exception:
                        pass
        except Exception:
            pass

        # ── piexif fallback (lebih lengkap) ───────────────────────────────────
        try:
            import piexif
            if "exif" in info:
                ed = piexif.load(info["exif"])
                ifd0 = ed.get("0th", {})
                def _str(v):
                    return v.decode("utf-8", errors="ignore").strip("\x00") if isinstance(v, bytes) else str(v)
                for tag, field in [(piexif.ImageIFD.Software,    "software"),
                                   (piexif.ImageIFD.Make,        "device_make"),
                                   (piexif.ImageIFD.Model,       "device_model"),
                                   (piexif.ImageIFD.DateTime,    "datetime")]:
                    if tag in ifd0 and not meta.get(field):
                        meta[field] = _str(ifd0[tag])
                gps = ed.get("GPS", {})
                if gps and "gps_lat" not in meta:
                    try:
                        def _dms2(d): return d[0][0]/d[0][1] + d[1][0]/d[1][1]/60 + d[2][0]/d[2][1]/3600
                        lat = _dms2(gps[piexif.GPSIFD.GPSLatitude])
                        lon = _dms2(gps[piexif.GPSIFD.GPSLongitude])
                        if gps.get(piexif.GPSIFD.GPSLatitudeRef) == b'S': lat = -lat
                        if gps.get(piexif.GPSIFD.GPSLongitudeRef) == b'W': lon = -lon
                        meta["gps_lat"] = round(lat, 6)
                        meta["gps_lon"] = round(lon, 6)
                        print(f"[Metadata] GPS (piexif): {lat:.6f}, {lon:.6f}")
                    except Exception:
                        pass
        except ImportError:
            pass

        if meta.get("software"):
            print(f"[Metadata] Software: {meta['software']}")
        if meta.get("device_model"):
            print(f"[Metadata] Device: {meta.get('device_make','')} {meta['device_model']}")

    except Exception as e:
        print(f"[Metadata] Error: {e}")
    return meta


# ─────────────────────────────────────────────────────────────────────────────
# FASE 2: Multi-Zone Crop Analysis
# ─────────────────────────────────────────────────────────────────────────────
def analyze_zones(image_path: str, api_key: str) -> dict:
    """
    Crop gambar ke 6 zona, analisis tiap zona dengan GPT-4o untuk detail kecil
    yang terlewat di main pass (kode PLN, refleksi cermin, RT/RW, marka jalan).
    """
    import io
    from PIL import Image

    try:
        img = Image.open(image_path)
        w, h = img.size
    except Exception as e:
        print(f"[MultiZone] Gagal buka gambar: {e}")
        return {}

    # Definisi zona + instruksi fokus
    zone_defs = {
        "kiri_atas":    (img.crop((0,    0,    w//2, h//3)),
                         "FOKUS: papan nama bangunan di latar belakang, billboard/baliho jauh, teks arah, landmark nun jauh"),
        "kanan_atas":   (img.crop((w//2, 0,    w,    h//3)),
                         "FOKUS: langit, kabel listrik, tiang utility dengan kode, teks jauh di bangunan"),
        "kiri_tengah":  (img.crop((0,    h//3, w//2, 2*h//3)),
                         "FOKUS: kode tiang PLN (contoh: JKT-041-A), spanduk, refleksi di kaca toko/jendela, papan RT/RW/Kelurahan"),
        "kanan_tengah": (img.crop((w//2, h//3, w,    2*h//3)),
                         "FOKUS: cermin spion kendaraan (cari teks di refleksi!), plat nomor, stiker kendaraan, teks pada badan kendaraan"),
        "kiri_bawah":   (img.crop((0,    2*h//3, w//2, h)),
                         "FOKUS: warna marka jalan (KUNING=jalan nasional, PUTIH=jalan kota), tutup gorong-gorong (cari logo: PAM JAYA/PDAM/PGN), bayangan objek"),
        "kanan_bawah":  (img.crop((w//2, 2*h//3, w,   h)),
                         "FOKUS: nomor rumah, tanaman/pohon (identifikasi spesies: angsana/glodogan/palem raja/bambu), kondisi trotoar, genangan air"),
    }

    llm = ChatOpenAI(model=VISION_MODEL, api_key=api_key, max_tokens=600)
    findings = {}

    for zone_name, (zone_img, focus) in zone_defs.items():
        # Skip zona yang terlalu kecil
        if zone_img.size[0] < 50 or zone_img.size[1] < 50:
            continue
        buf = io.BytesIO()
        if zone_img.mode in ("RGBA", "P", "LA"):
            zone_img = zone_img.convert("RGB")
        zone_img.save(buf, format="JPEG", quality=88)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        try:
            resp = llm.invoke([
                SystemMessage(content=f"""Kamu adalah analis OSINT Indonesia yang sedang menganalisis SATU BAGIAN dari gambar jalan.
{focus}
Tulis semua temuanmu dalam Bahasa Indonesia. Output HANYA JSON valid ini (null jika tidak terlihat):
{{
  "teks_ditemukan": [],
  "kode_tiang_pln": null,
  "plat_kendaraan": [],
  "teks_refleksi_cermin": [],
  "merek_gorong_gorong": null,
  "warna_marka_jalan": null,
  "jenis_lampu_jalan": null,
  "estimasi_rasio_bayangan": null,
  "papan_rt_rw_kelurahan": null,
  "spesies_vegetasi": [],
  "sinyal_tambahan": null
}}"""),
                HumanMessage(content=[
                    {"type": "text", "text": f"Analisis zona '{zone_name}' ini:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ])
            ])
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"): raw = raw[4:]
            import re
            raw = re.sub(r',\s*([\]}])', r'\1', raw)
            findings[zone_name] = json.loads(raw.strip())
            print(f"[Zone {zone_name}] OK → {list(k for k,v in findings[zone_name].items() if v)}")
        except Exception as e:
            print(f"[Zone {zone_name}] Error: {e}")
            findings[zone_name] = {}

    return findings


def merge_zone_findings(signals_json: dict, zone_findings: dict) -> dict:
    """Merge temuan zone analysis ke signals_json utama."""
    if not zone_findings:
        return signals_json

    geo = signals_json.setdefault("geo_signals", {})
    signals_json["zone_analysis"] = zone_findings

    all_texts        = list(geo.get("visible_texts", []))
    reflection_texts = []
    pln_codes        = []
    plates_found     = []
    rw_rt_signs      = []
    manhole_brands   = []
    road_colors      = []
    shadow_ratios    = []
    veg_species      = []

    for zname, f in zone_findings.items():
        for t in f.get("teks_ditemukan", []):
            if t and t not in all_texts: all_texts.append(t)
        if f.get("kode_tiang_pln"):     pln_codes.append(f["kode_tiang_pln"])
        for p in f.get("plat_kendaraan", []):
            if p and p not in plates_found: plates_found.append(p)
        for r in f.get("teks_refleksi_cermin", []):
            if r and r not in reflection_texts: reflection_texts.append(r)
        if f.get("papan_rt_rw_kelurahan"): rw_rt_signs.append(f["papan_rt_rw_kelurahan"])
        if f.get("merek_gorong_gorong"):   manhole_brands.append(f["merek_gorong_gorong"])
        if f.get("warna_marka_jalan"):     road_colors.append(f["warna_marka_jalan"])
        try:
            r = f.get("estimasi_rasio_bayangan")
            if r: shadow_ratios.append(float(r))
        except Exception: pass
        for v in f.get("spesies_vegetasi", []):
            if v and v not in veg_species: veg_species.append(v)

    # Tulis ke geo_signals
    if all_texts:        geo["visible_texts"]    = all_texts
    if pln_codes:        geo["pln_pole_code"]    = pln_codes[0]
    if plates_found and not geo.get("plate_prefix"):
        geo["plate_text_zone"] = plates_found[0]
    if reflection_texts:
        geo["reflection_texts"] = reflection_texts
        print(f"[Zone] Refleksi ditemukan: {reflection_texts}")
    if rw_rt_signs:
        geo["rw_rt_sign"] = rw_rt_signs[0]
        print(f"[Zone] RT/RW/Kelurahan: {rw_rt_signs[0]}")
    if manhole_brands:   geo["manhole_brand"]       = manhole_brands[0]
    if road_colors:      geo["road_marking_color"]  = road_colors[0]
    if shadow_ratios:    geo["shadow_length_ratio"] = round(sum(shadow_ratios)/len(shadow_ratios), 2)
    if veg_species:      geo["vegetation_species"]  = veg_species

    return signals_json


# ─────────────────────────────────────────────────────────────────────────────
# FASE 1: Main Vision Extraction (prompt diperluas + Bahasa Indonesia)
# ─────────────────────────────────────────────────────────────────────────────
def extract_signals_from_image(image_path, api_key):
    """Main LLM Vision pass — 17 seksi sinyal + reasoning Bahasa Indonesia."""
    base64_image = encode_image(image_path)
    llm = ChatOpenAI(model=VISION_MODEL, api_key=api_key, max_tokens=5000)

    prompt = """Kamu adalah Analis OSINT Militer tingkat tinggi, spesialis geografi Indonesia, infrastruktur urban, dan geolokasi.
MISI: Ekstrak SEMUA sinyal geospasial yang BENAR-BENAR TERLIHAT dalam gambar ini. Jangan mengarang — jika tidak terlihat, isi null.

ATURAN KRITIS — NOLAH TOLERANSI:
1. OCR RAMBU JALAN: Baca teks rambu huruf demi huruf. "Jl." = singkatan "Jalan". Waspadai: i/l, a/e, g/q, n/m, S/5. JANGAN menebak.
2. POI/BISNIS: HANYA isi poi_list dari teks fisik yang bisa dibaca langsung. DILARANG menambah nama dari asumsi.
3. INFERENSI WILAYAH: Gunakan pengetahuan jalan Indonesia — "Siaga Raya/Pejaten/Pasar Minggu/Mampang" → Jakarta Selatan. "Sudirman/Thamrin/Gatot Subroto" → Jakarta Pusat/Selatan. "Daan Mogot/Cengkareng/Pluit" → Jakarta Barat/Utara. "Margonda/Depok/Citayam/Bogor" → Jawa Barat. Jika jalan dikenali → isi province/city/district.
4. PLAT KENDARAAN: B/BE=DKI Jakarta/Banten, D=Bandung, L=Surabaya, F=Bogor, Z=Tasikmalaya, A=Banten, AB=Yogya, AD=Solo, N=Malang, S=Bojonegoro, W=Sidoarjo, H=Semarang, K=Pati, R=Banyumas, M=Madura, P=Besuki.
5. KALI/KANAL: Saluran air dekat jalan Jakarta = sinyal KUAT. Sebutkan namanya jika ada papan.
6. TRANSJAKARTA: Nomor koridor di papan = sinyal SANGAT SPESIFIK. Isi HANYA jika papan fisik terlihat jelas.
7. REFLEKSI CERMIN: Periksa cermin spion kendaraan, kaca toko, genangan air — sering memperlihatkan sisi jalan yang tidak terlihat langsung (papan nama, bangunan di belakang kamera).
8. KODE TIANG PLN: Tiang listrik di Indonesia sering punya kode area (misal: JKT-041-A, BDG-002). Kode ini unik per kelurahan.
9. MARKA JALAN: Warna marka KUNING = jalan nasional (Bina Marga). Warna PUTIH = jalan kota/provinsi. Ini penting untuk klasifikasi jalan.
10. VEGETASI: Identifikasi spesies pohon — Angsana (merah besar) = jalan protokol DKI lama. Glodogan Tiang = trotoar DKI modern. Palem Raja = boulevard/kantor pemerintah. Ini mempersempit area.
11. PAPAN RT/RW/KELURAHAN: Papan kecil "RW 07 Kel. Pejaten Barat" adalah sinyal lokasi SANGAT SPESIFIK — baca teks lengkapnya.
12. BAYANGAN: Estimasi rasio bayangan (panjang_bayangan / tinggi_objek) dari benda yang terlihat. Kombinasi dengan waktu → perkiraan lintang.
13. Output HANYA JSON valid. Tanpa markdown, tanpa teks tambahan.
14. REASONING WAJIB dalam Bahasa Indonesia — jelaskan semua clue yang kamu temukan.

OUTPUT STRUKTUR JSON INI PERSIS (isi semua field, null jika tidak terlihat):

{
  "1_media_metadata": {
    "quality": "high/medium/low",
    "composition": "street_level/aerial/dashcam/cctv",
    "image_type": "photo/screenshot/map"
  },
  "2_temporal_and_environmental": {
    "time_of_day": "morning/midday/afternoon/evening/night",
    "weather": "clear/cloudy/overcast/rainy",
    "lighting": "harsh_sun/soft/overcast/artificial",
    "shadow_direction": "N/NE/E/SE/S/SW/W/NW or null",
    "camera_heading": "N/NE/E/SE/S/SW/W/NW or null"
  },
  "3_geolocation_signals": {
    "country": "Indonesia",
    "province": "",
    "city": "",
    "district_kecamatan": "",
    "subdistrict_kelurahan": "",
    "primary_street_name": "",
    "secondary_street_name": "",
    "junction_name": "",
    "confidence_signals": [{"name": "Rambu Jalan", "value": "teks persis", "confidence": 0.95}]
  },
  "4_road_infrastructure": {
    "surface": "asphalt/concrete/paving_block",
    "total_lanes": 0,
    "lanes_per_direction": 0,
    "median_present": false,
    "median_type": "concrete_barrier/painted_line/garden/guardrail or null",
    "road_markings": [],
    "road_marking_color": "kuning/putih/null",
    "road_condition": "good/fair/poor",
    "sidewalk_present": false,
    "sidewalk_type": "paving_block/concrete/dirt or null",
    "overhead_cables": false,
    "utility_poles": "concrete/wooden/steel or null",
    "drainage_type": "open_ditch/covered/none"
  },
  "5_primary_subject": {
    "vehicle_type": "motorcycle/car/bus/truck or null",
    "vehicle_brand": null,
    "plate_text": null,
    "plate_prefix": null,
    "plate_region": null
  },
  "6_infrastructure_special": {
    "type": "bridge/flyover/underpass/tunnel/normal_road",
    "water_body_visible": false,
    "water_body_name": null,
    "water_body_type": "river/canal/lake/sea or null"
  },
  "7_points_of_interest": {
    "visible_business_names": [],
    "visible_bank_names": [],
    "visible_chain_stores": [],
    "healthcare_facilities": [],
    "religious_buildings": [],
    "government_buildings": [],
    "educational_institutions": [],
    "transit_facilities": []
  },
  "8_area_classification": {
    "area_type": "residential/commercial/industrial/mixed/government",
    "commercial_density": "low/medium/high",
    "building_density": "low/medium/high",
    "vegetation_density": "low/medium/high",
    "vegetation_type": "urban_sparse/tropical_dense/park/none"
  },
  "9_signage_and_ocr": {
    "all_detected_texts": [],
    "street_signs": [],
    "business_signs": [],
    "government_signs": [],
    "transit_signs": [],
    "warning_signs": []
  },
  "10_transit_indicators": {
    "transjakarta_visible": false,
    "transjakarta_corridor": null,
    "transjakarta_halte_name": null,
    "bus_stop_visible": false,
    "rail_track_visible": false,
    "toll_road_indicator": false
  },
  "11_agent_reasoning": "WAJIB BAHASA INDONESIA: Jelaskan detail semua clue lokasi yang ditemukan, mengapa lokasi ini diidentifikasi demikian, dan tingkat keyakinannya.",
  "12_reflections_and_hidden": {
    "mirror_reflection_detected": false,
    "mirror_reflection_texts": [],
    "window_glass_reflection": false,
    "window_reflection_texts": [],
    "puddle_reflection": false,
    "puddle_reflection_info": null,
    "hidden_texts_in_reflection": []
  },
  "13_infrastructure_codes": {
    "pln_pole_code": null,
    "street_light_type": "cobra_head_led/bulat_sodium/modern_led/lama or null",
    "manhole_cover_brand": "PAM_JAYA/PDAM/PGN/PLN/other or null",
    "utility_box_brand": null,
    "road_marking_color": "kuning/putih/null"
  },
  "14_vegetation_detail": {
    "dominant_species": null,
    "species_list": [],
    "planting_pattern": "formal_boulevard/informal/sparse/none",
    "grass_condition": "maintained/overgrown/none"
  },
  "15_signage_deep": {
    "billboard_texts": [],
    "rw_rt_kelurahan_sign": null,
    "property_for_sale_texts": [],
    "government_board_text": null,
    "banner_texts": [],
    "direction_sign_texts": []
  },
  "16_sun_shadow_analysis": {
    "shadow_visible": false,
    "shadow_reference_object": null,
    "shadow_length_ratio": null,
    "sun_directly_visible": false,
    "estimated_sun_elevation": null
  },
  "17_traffic_and_flow": {
    "traffic_direction_vs_camera": "toward/away/parallel/mixed or null",
    "is_one_way": false,
    "vehicle_density": "empty/light/moderate/heavy",
    "dominant_vehicle_type": "motorcycle/car/mixed or null",
    "ojol_visible": false
  },
  "geo_signals": {
    "plate_prefix": null,
    "plate_region": null,
    "street_name": null,
    "cross_street": null,
    "junction_name": null,
    "area_name": null,
    "city_district": null,
    "province": null,
    "landmark_sign": null,
    "landmark_type": null,
    "water_body_visible": false,
    "waterway_name": null,
    "waterway_type": null,
    "road_type": "arteri_primer/arteri_sekunder/kolektor/lokal",
    "road_lanes": 0,
    "road_lanes_direction": 0,
    "median_present": false,
    "median_type": null,
    "traffic_light_present": false,
    "sidewalk_present": false,
    "infrastructure_type": "normal_road/bridge/flyover",
    "camera_heading": null,
    "shadow_direction": null,
    "time_of_day": null,
    "visible_texts": [],
    "poi_list": [],
    "transjakarta_corridor": null,
    "transjakarta_halte": null,
    "bus_stop_visible": false,
    "vegetation_type": null,
    "commercial_density": "low/medium/high",
    "area_type": "residential/commercial/industrial/mixed",
    "pln_pole_code": null,
    "road_marking_color": null,
    "manhole_brand": null,
    "reflection_texts": [],
    "rw_rt_sign": null,
    "vegetation_species": [],
    "shadow_length_ratio": null,
    "traffic_direction": null
  }
}
"""
    try:
        import re
        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=[
                {"type": "text", "text": "Lakukan ekstraksi OSINT presisi tinggi pada gambar ini. Output hanya JSON."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ])
        ])
        content = response.content.strip()
        if content.startswith("```json"): content = content[7:]
        elif content.startswith("```"):   content = content[3:]
        if content.endswith("```"):       content = content[:-3]
        content = re.sub(r',\s*([\]}])', r'\1', content)
        return json.loads(content.strip())
    except Exception as e:
        print(f"[Vision] Error: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'image' not in request.files:
        return "No image uploaded", 400
        
    file = request.files['image']
    if file.filename == '':
        return "No image selected", 400
        
    if file:
        filename = f"upload_{uuid.uuid4().hex}.jpg"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key: return "Missing API KEY", 500
            
        # 1. Gatekeeper
        hive_secret = os.environ.get("HIVE_SECRET_KEY")
        gatekeeper = GatekeeperLayer(api_key=hive_secret)
        if gatekeeper.is_ai_generated(filepath):
            return render_template('rejected.html')

        # 2a. Metadata extraction (sebelum Vision agar bisa inject ke signals)
        img_meta = extract_image_metadata(filepath)
        if img_meta.get("gps_lat") and img_meta.get("gps_lon"):
            print(f"[!] GPS dari metadata: {img_meta['gps_lat']}, {img_meta['gps_lon']}")

        # 2b. Vision API Extraction (main pass — 17 seksi)
        signals_json = extract_signals_from_image(filepath, api_key)
        if not signals_json: return "Vision Extraction Failed", 500

        # Simpan metadata gambar ke signals
        signals_json["image_metadata"] = img_meta

        # 2c. Inject GPS metadata langsung ke geo_signals jika ada
        _geo = signals_json.setdefault("geo_signals", {})
        if img_meta.get("gps_lat") and not _geo.get("gps_from_metadata"):
            _geo["gps_from_metadata"] = {
                "lat": img_meta["gps_lat"],
                "lon": img_meta["gps_lon"],
                "source": "exif"
            }

        # 2d. Multi-zone crop analysis (second GPT-4o pass per zona)
        print("[*] Menjalankan multi-zone crop analysis...")
        zone_findings = analyze_zones(filepath, api_key)
        signals_json  = merge_zone_findings(signals_json, zone_findings)

        # 2e. Propagate section-3 city/district → geo_signals
        _sig3 = signals_json.get("3_geolocation_signals", {})
        if not _geo.get("city_district") and _sig3.get("city"):
            _geo["city_district"] = _sig3["city"]
        if not _geo.get("province") and _sig3.get("province"):
            _geo["province"] = _sig3["province"]
        if not _geo.get("area_name") and _sig3.get("district_kecamatan"):
            _geo["area_name"] = _sig3["district_kecamatan"]

        # 2f. Propagate field baru dari seksi 12-17 ke geo_signals
        sec12 = signals_json.get("12_reflections_and_hidden", {})
        sec13 = signals_json.get("13_infrastructure_codes", {})
        sec14 = signals_json.get("14_vegetation_detail", {})
        sec15 = signals_json.get("15_signage_deep", {})
        sec16 = signals_json.get("16_sun_shadow_analysis", {})
        sec17 = signals_json.get("17_traffic_and_flow", {})

        if not _geo.get("reflection_texts"):
            rt = (sec12.get("mirror_reflection_texts", []) +
                  sec12.get("window_reflection_texts", []) +
                  sec12.get("hidden_texts_in_reflection", []))
            if rt: _geo["reflection_texts"] = rt
        if not _geo.get("pln_pole_code") and sec13.get("pln_pole_code"):
            _geo["pln_pole_code"] = sec13["pln_pole_code"]
        if not _geo.get("road_marking_color") and sec13.get("road_marking_color"):
            _geo["road_marking_color"] = sec13["road_marking_color"]
        if not _geo.get("manhole_brand") and sec13.get("manhole_cover_brand"):
            _geo["manhole_brand"] = sec13["manhole_cover_brand"]
        if not _geo.get("vegetation_species") and sec14.get("species_list"):
            _geo["vegetation_species"] = sec14["species_list"]
        if not _geo.get("rw_rt_sign") and sec15.get("rw_rt_kelurahan_sign"):
            _geo["rw_rt_sign"] = sec15["rw_rt_kelurahan_sign"]
        if not _geo.get("shadow_length_ratio") and sec16.get("shadow_length_ratio"):
            _geo["shadow_length_ratio"] = sec16["shadow_length_ratio"]
        if not _geo.get("traffic_direction") and sec17.get("traffic_direction_vs_camera"):
            _geo["traffic_direction"] = sec17["traffic_direction_vs_camera"]

        print("[*] Extracted JSON:")
        print(json.dumps(signals_json, indent=2))

        # 3. Save signals JSON (tambah image_path untuk CP1 re-runs)
        json_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{filename}.json")
        signals_json["image_path"] = os.path.abspath(filepath)
        with open(json_path, 'w') as f:
            json.dump(signals_json, f, indent=2)

        # 3b. Multicheck — anti-hallucination validation sebelum main pipeline
        output_dir = 'output'
        multicheck_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "multicheck")
        json_path_abs      = os.path.abspath(json_path)
        verified_json_path = json_path_abs.replace(".json", "_verified.json")
        mc_recommendation = "PROCEED"

        import shutil

        # Pilih runtime: bun lebih cepat, fallback ke local tsx binary
        _bun = shutil.which("bun")
        # Windows pakai .cmd, Unix pakai tanpa ekstensi
        _tsx_cmd = os.path.join(multicheck_dir, "node_modules", ".bin", "tsx.cmd")
        _tsx_sh  = os.path.join(multicheck_dir, "node_modules", ".bin", "tsx")
        _tsx_bin = _tsx_cmd if os.path.exists(_tsx_cmd) else (_tsx_sh if os.path.exists(_tsx_sh) else None)

        if _bun:
            _mc_cmd = ["bun", "run", "src/index.ts", json_path_abs, verified_json_path]
        elif _tsx_bin:
            _mc_cmd = [_tsx_bin, "src/index.ts", json_path_abs, verified_json_path]
        else:
            _mc_cmd = None

        if _mc_cmd and os.path.isdir(multicheck_dir):
            # Pass env vars ke subprocess (termasuk yang sudah di-load dari .env)
            _mc_env = {
                **os.environ,
                "OPENAI_API_KEY":      os.getenv("OPENAI_API_KEY", ""),
                "MAPBOX_ACCESS_TOKEN": os.getenv("MAPBOX_ACCESS_TOKEN", ""),
            }
            mc_result = subprocess.run(
                _mc_cmd,
                cwd=multicheck_dir,
                capture_output=True,
                text=True,
                timeout=120,
                env=_mc_env,
            )
            if mc_result.returncode in (0, 2) and os.path.exists(verified_json_path):
                with open(verified_json_path) as _f:
                    _mc = json.load(_f)
                mc_info = _mc.get("multicheck", {}).get("cp4", {})
                mc_recommendation = mc_info.get("recommendation", "PROCEED")
                print(f"[Multicheck] Risk={mc_info.get('hallucinationRisk','?')} "
                      f"Score={mc_info.get('hallucinationScore','?')} "
                      f"Rec={mc_recommendation}")
                if mc_recommendation != "REJECT":
                    json_path_abs = verified_json_path  # pakai verified signals
            else:
                print(f"[Multicheck] Failed (rc={mc_result.returncode}), using raw signals")
                if mc_result.stderr:
                    print(f"[Multicheck STDERR] {mc_result.stderr[:800]}")
        else:
            print("[Multicheck] tsx binary not found — jalankan 'npm install' di folder multicheck/")

        subprocess.run(["python", "main.py", "-i", json_path_abs, "-f", "all", "-v"], check=True)

        # 4a. Cek apakah pipeline bail-out (not_found)
        not_found_path = os.path.join(output_dir, "not_found.json")
        if os.path.exists(not_found_path):
            with open(not_found_path, encoding="utf-8") as _nf:
                nf_data = json.load(_nf)
            # Hapus file agar tidak ke-carry ke request berikutnya
            os.remove(not_found_path)
            session["not_found"] = nf_data
            return redirect("/not-found")

        # 4. Persistence
        session['last_signals'] = signals_json
        geojson_path = os.path.join(output_dir, "result.geojson")
        if os.path.exists(geojson_path):
            with open(geojson_path, 'r') as f:
                gj = json.load(f)
                session['candidates'] = [feat['properties'] for feat in gj.get('features', [])]
                for i, feat in enumerate(gj.get('features', [])):
                    session['candidates'][i].update({
                        'lat': feat['geometry']['coordinates'][1],
                        'lon': feat['geometry']['coordinates'][0]
                    })
        else:
            session['candidates'] = []
        
        return redirect('/result')

@app.route('/not-found')
def not_found():
    nf = session.get("not_found", {
        "joke": "Waduh bro, gambarnya terlalu misterius buat gue wkwkwk 🤷",
        "reason": "unknown"
    })
    return render_template('not_found.html', joke=nf.get("joke", ""), reason=nf.get("reason", ""))

@app.route('/result')
def result():
    signals = session.get('last_signals', {})
    candidates = session.get('candidates', [])
    geo_signals = signals.get('geo_signals', {})
    return render_template('result.html', signals_json=signals, geo_signals=geo_signals, candidates=candidates)

@app.route('/map-data')
def map_data():
    map_path = os.path.join(os.getcwd(), 'output', 'result_map.html')
    if os.path.exists(map_path):
        return send_file(map_path)
    return "Map not found", 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)

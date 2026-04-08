# 🛰️ GeoSignal — OSINT Visual Signal-to-Coordinate Engine

GeoSignal is a specialized tool for open-source intelligence (OSINT) research, designed to geolocate images based on visual cues such as license plates, road signage, infrastructure, and road layouts.

It employs a **Constraint-Intersection Geolocation** methodology, utilizing public OpenStreetMap (OSM) data via the Overpass API and Nominatim.

## 🌟 Features
- **No Paid APIs**: Uses 100% free OpenStreetMap-based services.
- **Plate Prefix Mapping**: Automatically narrows search areas based on regional license plate prefixes (currently focusing on Indonesia).
- **Landmark Normalization**: Handles fuzzy mentions of POIs (Point of Interest) like hospitals, malls, etc.
- **Road Infrastructure Logic**: Filters by road classification, lane count, and presence of medians.
- **Confidence Scoring**: Weighted scoring system to estimate location probability.
- **Multi-Output Format**: Generates text reports, GeoJSON data, and interactive Folium maps.

## 🛠️ Installation
1. Ensure you have Python 3.11+ installed.
2. Clone this repository or download the files.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## 🚀 Usage
Generate geolocation candidates from an analysis JSON file:
```bash
python main.py -i tests/sample_input.json -f all -v
```

### Options:
- `-i, --input`: Path to your visual metadata JSON file.
- `-f, --format`: Choose output between `report`, `geojson`, `map`, or `all`.
- `-o, --output-dir`: Where to save results (default: `output/`).
- `-v, --verbose`: Enable detailed processing logs.

## 🔍 Methodology
1. **Signal Extraction**: Visual cues are parsed into a `SignalBundle`.
2. **Area Refinement**: The search begins with a wide bounding box based on the license plate region, then refines via Nominatim geocoding of landmarks.
3. **Overpass Query**: Searches for matching nodes and ways (hospitals, roads) within the refined bounding box.
4. **Constraint Filtering**: Intersects candidates that meet multiple criteria (e.g., a hospital within 500m of a 4-lane primary road).
5. **Scoring & Estimation**: Assigns a confidence score and estimates a radius error based on signal matches and spatial proximity.

## ⚠️ Credits & Respect
This tool relies on the hard work of the OpenStreetMap community. Please respect the usage policies of the public APIs:
- **Nominatim**: Max 1 request per second.
- **Overpass API**: Use public instances sparingly.

---
*Created as part of the Geocek internal toolsuite for OSINT research.*

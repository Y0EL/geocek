import { env, CONFIG } from "../config.js";
import { withRetry } from "../utils/retry.js";

const MAPBOX_BASE = "https://api.mapbox.com";

export interface MapboxFeature {
  name:      string;
  lat:       number;
  lon:       number;
  placeType: string[];
}

// Forward geocoding — query → daftar kandidat lokasi
// bboxStr format: "minLat,minLon,maxLat,maxLon" (sama dengan Python)
export async function forwardGeocode(
  query:    string,
  bboxStr?: string,
  limit:    number = CONFIG.CP2_MAPBOX_STREET_LIMIT,
): Promise<MapboxFeature[]> {
  return withRetry(async () => {
    const params = new URLSearchParams({
      access_token: env.MAPBOX_ACCESS_TOKEN,
      country:      "id",
      limit:        String(limit),
      language:     "id",
      types:        "address,poi,place,locality,neighborhood",
    });

    if (bboxStr) {
      const parts = bboxStr.split(",").map(Number);
      // Python format: minLat,minLon,maxLat,maxLon
      // Mapbox format: minLon,minLat,maxLon,maxLat
      params.set("bbox", `${parts[1]},${parts[0]},${parts[3]},${parts[2]}`);
    }

    const url = `${MAPBOX_BASE}/geocoding/v5/mapbox.places/${encodeURIComponent(query)}.json?${params}`;
    const res  = await fetch(url, { signal: AbortSignal.timeout(8_000) });

    if (!res.ok) throw new Error(`Mapbox geocoding HTTP ${res.status}`);
    const data = await res.json() as { features: unknown[] };

    return (data.features as Record<string, unknown>[]).map(f => ({
      name:      String(f["place_name"] ?? f["text"] ?? ""),
      lat:       (f["geometry"] as { coordinates: number[] }).coordinates[1],
      lon:       (f["geometry"] as { coordinates: number[] }).coordinates[0],
      placeType: (f["place_type"] as string[]) ?? [],
    }));
  }, CONFIG.RETRY_MAX_ATTEMPTS, CONFIG.RETRY_BASE_DELAY_MS);
}

export interface TilequeryRoad {
  name:   string;
  klass:  string;  // "primary", "secondary", dll
  oneway: string;
}

export interface TilequeryPOI {
  name:     string;
  category: string;
}

// Tilequery untuk road segments dalam radius tertentu
export async function tilequeryRoads(
  lat:    number,
  lon:    number,
  radius: number = CONFIG.CP3_REVERIFY_RADIUS_M,
): Promise<TilequeryRoad[]> {
  return withRetry(async () => {
    const params = new URLSearchParams({
      access_token: env.MAPBOX_ACCESS_TOKEN,
      radius:       String(radius),
      limit:        "10",
      layers:       "road",
    });
    const url = `${MAPBOX_BASE}/v4/mapbox.mapbox-streets-v8/tilequery/${lon},${lat}.json?${params}`;
    const res  = await fetch(url, { signal: AbortSignal.timeout(8_000) });

    if (!res.ok) throw new Error(`Mapbox tilequery (roads) HTTP ${res.status}`);
    const data = await res.json() as { features: unknown[] };

    return (data.features as Record<string, unknown>[]).map(f => {
      const props = f["properties"] as Record<string, string>;
      return {
        name:   props["name"] ?? props["name_en"] ?? "",
        klass:  props["class"] ?? "",
        oneway: props["oneway"] ?? "false",
      };
    }).filter(r => r.name !== "");
  }, CONFIG.RETRY_MAX_ATTEMPTS, CONFIG.RETRY_BASE_DELAY_MS);
}

// Tilequery untuk POI dalam radius tertentu
export async function tilequeryPOIs(
  lat:    number,
  lon:    number,
  radius: number = CONFIG.CP3_REVERIFY_RADIUS_M,
): Promise<TilequeryPOI[]> {
  return withRetry(async () => {
    const params = new URLSearchParams({
      access_token: env.MAPBOX_ACCESS_TOKEN,
      radius:       String(radius),
      limit:        "10",
      layers:       "poi_label",
    });
    const url = `${MAPBOX_BASE}/v4/mapbox.mapbox-streets-v8/tilequery/${lon},${lat}.json?${params}`;
    const res  = await fetch(url, { signal: AbortSignal.timeout(8_000) });

    if (!res.ok) throw new Error(`Mapbox tilequery (POIs) HTTP ${res.status}`);
    const data = await res.json() as { features: unknown[] };

    return (data.features as Record<string, unknown>[]).map(f => {
      const props = f["properties"] as Record<string, string>;
      return {
        name:     props["name"] ?? props["name_en"] ?? "",
        category: props["maki"] ?? props["category_en"] ?? "",
      };
    }).filter(p => p.name !== "");
  }, CONFIG.RETRY_MAX_ATTEMPTS, CONFIG.RETRY_BASE_DELAY_MS);
}

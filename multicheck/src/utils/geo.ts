// Utilitas geo: haversine distance, bbox containment, normalization

const EARTH_RADIUS_M = 6_371_000;

// Haversine distance dalam meter antara dua koordinat
export function haversineM(
  lat1: number, lon1: number,
  lat2: number, lon2: number,
): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat  = toRad(lat2 - lat1);
  const dLon  = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return EARTH_RADIUS_M * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// Cek apakah koordinat ada di dalam bbox
// bboxStr format Python: "minLat,minLon,maxLat,maxLon"
export function bboxContains(
  bboxStr:   string,
  lat:       number,
  lon:       number,
  toleranceDeg: number = 0,
): boolean {
  const [minLat, minLon, maxLat, maxLon] = bboxStr.split(",").map(Number);
  return (
    lat >= minLat - toleranceDeg &&
    lat <= maxLat + toleranceDeg &&
    lon >= minLon - toleranceDeg &&
    lon <= maxLon + toleranceDeg
  );
}

// Normalisasi string untuk fuzzy comparison (lowercase, hilangkan spasi ekstra)
export function normalize(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9\s]/g, "").replace(/\s+/g, " ").trim();
}

// Fuzzy match: cek apakah dua string "cukup mirip"
// Menggunakan substring matching + normalization
export function fuzzyMatch(a: string, b: string): boolean {
  const na = normalize(a);
  const nb = normalize(b);
  if (na === nb) return true;
  if (na.includes(nb) || nb.includes(na)) return true;

  // Token overlap: minimal 50% token yang sama
  const ta = new Set(na.split(" ").filter(t => t.length > 2));
  const tb = new Set(nb.split(" ").filter(t => t.length > 2));
  if (ta.size === 0 || tb.size === 0) return false;

  let overlap = 0;
  for (const t of ta) {
    if (tb.has(t)) overlap++;
  }
  const minSize = Math.min(ta.size, tb.size);
  return (overlap / minSize) >= 0.5;
}

import click
import json
import os
import time
from typing import List, Dict, Any
from core.signal_parser import SignalParser, SignalBundle
from core.bbox_generator import BBoxGenerator, BBox
from core.osm_query import OSMQueryEngine
from core.nominatim_query import NominatimQuery
from core.confidence_scorer import ConfidenceScorer
from core.output_builder import OutputBuilder, ScoredCandidate
from core.ai_agent import GeolocationAIAgent
import traceback
from dotenv import load_dotenv

load_dotenv()


@click.command()
@click.option('--input', '-i', required=True, type=click.Path(exists=True),
              help='Path ke file JSON metadata visual')
@click.option('--format', '-f',
              type=click.Choice(['geojson', 'report', 'map', 'all']),
              default='all', help='Format output')
@click.option('--output-dir', '-o', default='output/',
              help='Direktori output')
@click.option('--verbose', '-v', is_flag=True,
              help='Tampilkan detail proses')
def main(input, format, output_dir, verbose):
    """
    GeoSignal — OSINT Visual Signal to Coordinate Engine
    """
    start_time = time.time()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        # 1. Load JSON input
        with open(input, 'r') as f:
            input_data = json.load(f)

        if verbose: click.echo(f"[*] Processing case: {input_data.get('case_id', 'Unknown')}")

        # 2. Parse Signals — gunakan verifiedGeoSignals dari multicheck jika ada
        multicheck_data = input_data.get("multicheck", {})
        verified_signals = multicheck_data.get("verifiedGeoSignals")
        mc_weight_overrides = multicheck_data.get("cp2", {}).get("adjustedWeights", {})
        mc_candidate_mults  = multicheck_data.get("candidateMultipliers", {})
        mc_recommendation   = multicheck_data.get("cp4", {}).get("recommendation", "PROCEED")

        if verified_signals:
            # Ganti geo_signals dengan verified version dari multicheck
            input_data = {**input_data, "geo_signals": verified_signals}
            if verbose:
                click.echo(f"[Multicheck] Using verified signals (rec={mc_recommendation})")

        parser = SignalParser()
        bundle = parser.parse(input_data)
        if verbose:
            click.echo(f"[*] Parsed {len(bundle.signal_weights)} weighted signals")
            click.echo(f"    Street queries  : {bundle.street_queries[:3]}")
            click.echo(f"    Landmark queries: {bundle.landmark_queries[:3]}")
            click.echo(f"    POI queries     : {bundle.poi_queries[:3]}")

        # 3. Generate BBox from plate prefix
        bbox_gen = BBoxGenerator()
        if bundle.plate_bbox:
            bbox = bbox_gen.from_plate(bundle.plate_bbox)
        else:
            bbox = BBox(-11.0, 6.0, 95.0, 141.0, "Indonesia Fallback")

        if verbose: click.echo(f"[*] Initial BBox: {bbox.label} (Area: {bbox.area_km2():.2f} km²)")

        # 4. Refine BBox — try street name first, then landmark, then area name
        refine_queries = (
            bundle.street_queries[:1]
            + bundle.landmark_queries[:1]
            + ([bundle.area_context.get("area_name")] if bundle.area_context.get("area_name") else [])
        )
        for rq in refine_queries:
            if not rq:
                continue
            refined = bbox_gen.from_mapbox(rq, bbox)
            if refined:
                bbox = refined
                if verbose: click.echo(f"[*] Refined BBox via Mapbox: '{rq}' → {bbox.label}")
                break

        # 5. Multi-strategy Mapbox search
        query_engine = OSMQueryEngine()
        bbox_str = bbox_gen.to_bbox_string(bbox)

        # Compute proximity center from BBox (for Mapbox proximity bias)
        bbox_center = bbox.center()

        # Build prioritized query groups
        query_groups = {
            "street": bundle.street_queries,
            "landmark": bundle.landmark_queries,
            "poi": bundle.poi_queries,
            "text": bundle.text_queries,
        }

        if verbose: click.echo(f"[*] Running multi-strategy search (Nominatim + Mapbox)...")

        nominatim = NominatimQuery()
        candidates = []

        # ── Street queries: Nominatim/Photon dulu (jauh lebih akurat untuk jalan Indonesia)
        if bundle.street_queries:
            seen_coords = set()
            for q in bundle.street_queries:
                if not q or len(q.strip()) < 3:
                    continue
                city_hint = bundle.area_context.get("city_district") or bundle.area_context.get("area_name") or "Jakarta"
                results = nominatim.search_street(q, bbox_str, city_hint=city_hint)
                for r in results:
                    key = (round(r["lat"], 3), round(r["lon"], 3))
                    if key not in seen_coords:
                        seen_coords.add(key)
                        r["query_group"] = "street"
                        r["query_used"]  = q
                        candidates.append(r)
                if candidates:
                    if verbose: click.echo(f"[✓] Nominatim street hit: '{q}' → {len(candidates)} candidates")
                    break  # street ditemukan, stop

        # ── Landmark + POI + Text: tetap pakai Mapbox (lebih baik untuk POI)
        if not candidates or len(candidates) < 3:
            mapbox_groups = {
                "landmark": bundle.landmark_queries,
                "poi":      bundle.poi_queries,
                "text":     bundle.text_queries,
            }
            mapbox_results = query_engine.search_all(mapbox_groups, bbox_str)
            # Deduplicate vs nominatim results
            seen_coords = {(round(c["lat"], 3), round(c["lon"], 3)) for c in candidates}
            for r in mapbox_results:
                key = (round(r["lat"], 3), round(r["lon"], 3))
                if key not in seen_coords:
                    seen_coords.add(key)
                    candidates.append(r)

        # ── Fallback: area name via Nominatim
        if not candidates and bundle.area_context.get("area_name"):
            fallback_q = bundle.area_context["area_name"]
            if verbose: click.echo(f"[!] No candidates — Nominatim area fallback: '{fallback_q}'")
            candidates = nominatim.search_street(fallback_q, bbox_str)

        if verbose: click.echo(f"[*] Total candidates found: {len(candidates)}")

        # 6. Score + AI refinement
        scorer = ConfidenceScorer()
        scored_candidates = []

        openai_key = os.getenv("OPENAI_API_KEY", "")
        agent = None
        if openai_key:
            if verbose: click.echo("[*] Initializing AI Agent for coordinate refinement...")
            agent = GeolocationAIAgent(openai_key)

        # ── Early bail-out: cek apakah ada sinyal yang cukup untuk dilanjutkan ──────
        HIGH_VALUE_SIGNALS = {"street", "cross_street", "junction", "transjakarta_halte",
                               "transjakarta_corridor", "waterway", "plate", "landmark",
                               "rw_rt_sign", "pln_pole_code", "gps_metadata"}
        meaningful_signals = HIGH_VALUE_SIGNALS & set(bundle.signal_weights.keys())
        geo_signals_raw    = input_data.get("geo_signals", {})

        if not candidates and len(meaningful_signals) == 0:
            # Tidak ada kandidat DAN tidak ada sinyal bermakna → bail out sekarang
            # Jangan buang token untuk AI world-knowledge yang pasti juga gagal
            if verbose:
                click.echo("[!] Zero kandidat + zero sinyal bermakna → bail out, generate joke")
            joke_msg = agent.generate_not_found_joke(geo_signals_raw) if agent else \
                       "Waduh bro, gambar ini kayak teka-teki sphinx... gue nyerah deh wkwkwk 🤷"
            not_found = {"found": False, "joke": joke_msg,
                         "reason": "no_meaningful_signals",
                         "signals_extracted": list(bundle.signal_weights.keys())}
            with open(os.path.join(output_dir, "not_found.json"), "w", encoding="utf-8") as f:
                json.dump(not_found, f, indent=2, ensure_ascii=False)
            # Tulis geojson kosong supaya app.py tidak crash
            with open(os.path.join(output_dir, "result.geojson"), "w") as f:
                json.dump({"type": "FeatureCollection", "features": []}, f)
            click.echo(f"[Not Found] {joke_msg}")
            return  # ← stop di sini, hemat token

        # ── Last-resort fallback: AI world-knowledge estimation (ketika SEMUA geocoder gagal)
        if not candidates and agent:
            if verbose: click.echo("[!] All geocoders returned 0 — using AI world-knowledge estimation...")
            ai_estimates = agent.estimate_location_from_signals(geo_signals_raw, input_data)
            for c in ai_estimates:
                c["query_group"] = "ai_estimate"
            candidates.extend(ai_estimates)
            if verbose: click.echo(f"[AI] World-knowledge gave {len(ai_estimates)} candidate(s)")

        # ── Bail-out ke-2: AI world-knowledge juga gagal + sinyal sangat lemah ─
        if not candidates:
            if verbose: click.echo("[!] Semua fallback gagal → bail out dengan joke")
            joke_msg = agent.generate_not_found_joke(geo_signals_raw) if agent else \
                       "Bro gambar ini entah dari planet mana, gue beneran nyerah wkwkwk 🛸"
            not_found = {"found": False, "joke": joke_msg,
                         "reason": "all_geocoders_failed",
                         "signals_extracted": list(bundle.signal_weights.keys())}
            with open(os.path.join(output_dir, "not_found.json"), "w", encoding="utf-8") as f:
                json.dump(not_found, f, indent=2, ensure_ascii=False)
            with open(os.path.join(output_dir, "result.geojson"), "w") as f:
                json.dump({"type": "FeatureCollection", "features": []}, f)
            click.echo(f"[Not Found] {joke_msg}")
            return

        geo_signals = input_data.get("geo_signals", {})
        context = {"hospitals": []}

        for cand in candidates:
            # AI world-knowledge estimates are already precise — skip Mapbox tilequery refinement
            if agent and cand.get("source") != "ai_world_knowledge":
                if verbose: click.echo(f"[*] AI Agent refining: {cand.get('name', '')[:50]}")
                cand = agent.refine_candidate(cand, geo_signals)

            score = scorer.score_candidate(cand, bundle, context, weight_overrides=mc_weight_overrides)

            # Terapkan CP3 score multiplier dari multicheck jika ada
            cand_name = cand.get("name", "")
            if mc_candidate_mults:
                mult = mc_candidate_mults.get(cand_name, 1.0)
                if mult < 1.0 and verbose:
                    click.echo(f"[Multicheck] CP3 demote '{cand_name[:40]}' ×{mult}")
                score = score * mult

            # Build matched signals list
            signals = []
            if "plate" in bundle.signal_weights:
                signals.append("Plat Match")
            if "street" in bundle.signal_weights and bundle.street_queries:
                if any(sq.lower().split(",")[0] in cand.get("name", "").lower() for sq in bundle.street_queries):
                    signals.append("Street Match")
            if bundle.landmark_queries:
                if any(q.lower() in cand.get("name", "").lower() for q in bundle.landmark_queries):
                    signals.append("Landmark Match")
            if cand.get("query_group") == "poi":
                signals.append("POI Match")
            if cand.get("highway") in bundle.road_constraints.get("highway", []):
                signals.append("Road Type Match")
            if bundle.infrastructure.get("transjakarta_corridor"):
                signals.append("TransJakarta Signal")
            if bundle.infrastructure.get("water_body"):
                signals.append("Water Body Signal")

            scored_candidates.append(ScoredCandidate(
                lat=cand["lat"],
                lon=cand["lon"],
                name=cand["name"],
                confidence_score=score,
                confidence_label=scorer.classify_confidence(score),
                radius_m=scorer.estimate_radius(score),
                matched_signals=signals if signals else ["Area Match"],
                osm_id=cand.get("osm_id", 0),
                osm_type=cand.get("type", "node"),
                ai_reasoning=cand.get("ai_reasoning", "")
            ))

        # Sort and take top 5
        scored_candidates.sort(key=lambda x: x.confidence_score, reverse=True)
        top_candidates = scored_candidates[:5]

        # 7. Generate Output
        duration = time.time() - start_time
        builder = OutputBuilder()

        if format in ['all', 'report']:
            report_str = builder.to_report(top_candidates, bundle, duration)
            click.echo(report_str)
            with open(os.path.join(output_dir, "report.txt"), "w", encoding='utf-8') as f:
                f.write(report_str)

        if format in ['all', 'geojson']:
            gj = builder.to_geojson(top_candidates)
            with open(os.path.join(output_dir, "result.geojson"), "w", encoding='utf-8') as f:
                json.dump(gj, f, indent=2)

        if format in ['all', 'map']:
            map_path = os.path.join(output_dir, "result_map.html")
            builder.to_mapbox_map(top_candidates, map_path)
            if verbose: click.echo(f"[*] Mapbox map saved to: {map_path}")

    except Exception as e:
        click.echo(f"[!] Error: {e}", err=True)
        if verbose: traceback.print_exc()

if __name__ == "__main__":
    main()

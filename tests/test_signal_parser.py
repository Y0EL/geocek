import os
import json
import pytest
from core.signal_parser import SignalParser

# Mock sample data
sample_input = {
  "geo_signals": {
    "plate_prefix": "B",
    "landmark_sign": "RS Atmajaya",
    "road_type": "arteri_primer",
    "road_lanes": 4,
    "median_present": True
  }
}

def test_plate_b_maps_to_jabodetabek():
    parser = SignalParser()
    result = parser.parse(sample_input)
    assert result.plate_bbox["min_lat"] <= -5.9
    assert result.plate_bbox["max_lon"] >= 106.6
    assert "Jakarta" in result.plate_bbox.get("label", "")

def test_landmark_normalizer():
    parser = SignalParser()
    candidates = parser.normalize_landmark("RS Atmajaya")
    assert any("Atmajaya" in c for c in candidates)
    assert any("Rumah Sakit" in c for c in candidates)

def test_confidence_not_zero():
    parser = SignalParser()
    result = parser.parse(sample_input)
    assert result.confidence_initial > 0.5

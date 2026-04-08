import os
import math
import cv2
import numpy as np
from PIL import Image, ImageChops, ImageEnhance, ImageStat
import exiftool
from typing import Dict, Any


class ImageForensicsAgent:
    """
    Advanced Image Forensics Pipeline for GeoSignal.
    Extracts explicit metadata via PyExifTool and runs structural physics analysis
    via OpenCV to detect manipulation, noise levels, focus points, and aberrations.
    """

    def __init__(self, exiftool_path: str = None):
        self.exiftool_path = exiftool_path
        
    def _extract_exif_metadata(self, image_path: str) -> Dict[str, Any]:
        """Extracts deep Exif metadata including lens profiles and residual GPS."""
        try:
            with exiftool.ExifToolHelper() as et:
                metadata = et.get_metadata(image_path)
                if not metadata:
                    return {}
                data = metadata[0]
                
                # Filter useful OSINT tags
                return {
                    "datetime_original": data.get("EXIF:DateTimeOriginal", ""),
                    "gps_latitude": data.get("EXIF:GPSLatitude", None),
                    "gps_longitude": data.get("EXIF:GPSLongitude", None),
                    "camera_make": data.get("EXIF:Make", ""),
                    "camera_model": data.get("EXIF:Model", ""),
                    "focal_length": data.get("EXIF:FocalLength", ""),
                    "iso": data.get("EXIF:ISO", ""),
                    "exposure_time": data.get("EXIF:ExposureTime", ""),
                    "lens_model": data.get("EXIF:LensModel", "")
                }
        except Exception as e:
            return {"error": f"ExifTool extraction failed: {str(e)}. Proceeding with structural analysis."}

    def _compute_laplacian_variance(self, image: np.ndarray) -> float:
        """Computes the sharpness/blur level of the image using Laplacian matrix variance."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()

    def _detect_chromatic_aberration(self, image: np.ndarray) -> float:
        """
        Estimates chromatic aberration by detecting misalignment of RGB channels
        near the edges of the image (often indicates digital zoom or cheap lenses).
        """
        b, g, r = cv2.split(image)
        # Shift channels slightly
        shift_b = np.roll(b, 1, axis=1)
        shift_r = np.roll(r, -1, axis=1)
        
        diff_b = cv2.absdiff(g, shift_b)
        diff_r = cv2.absdiff(g, shift_r)
        
        # Calculate mean edge displacement intensity
        ca_score = (np.mean(diff_b) + np.mean(diff_r)) / 2.0
        return ca_score

    def _estimate_time_of_day_physics(self, image_path: str) -> Dict[str, Any]:
        """Estimates ambient lighting using PIL stats (brightness and color channels)."""
        img = Image.open(image_path).convert('RGB')
        stat = ImageStat.Stat(img)
        
        # Perceived brightness algorithm
        r, g, b = stat.mean
        brightness = math.sqrt(0.299*(r**2) + 0.587*(g**2) + 0.114*(b**2))
        
        is_night = brightness < 80
        
        return {
            "perceived_brightness": brightness,
            "lighting_assumption": "Night/Low-light" if is_night else "Day/Well-lit",
            "color_balance": {"r": r, "g": g, "b": b}
        }

    def _detect_manipulation_ela(self, image_path: str) -> float:
        """
        [BRUTAL FORENSIC] Error Level Analysis (ELA)
        Detects if parts of the image were photoshopped or patched by saving it at a known
        quality and calculating the pixel difference. High variance = manipulated.
        """
        temp_path = "tmp_ela_cache.jpg"
        original = Image.open(image_path).convert("RGB")
        original.save(temp_path, "JPEG", quality=90)
        
        saved = Image.open(temp_path)
        ela_image = ImageChops.difference(original, saved)
        
        extrema = ela_image.getextrema()
        max_diff = max([ex[1] for ex in extrema])
        if max_diff == 0: max_diff = 1
        
        scale = 255.0 / max_diff
        ela_image = ImageEnhance.Brightness(ela_image).enhance(scale)
        ela_stat = ImageStat.Stat(ela_image)
        
        os.remove(temp_path)
        return max(ela_stat.mean) # High mean indicates manipulation

    def _estimate_lighting_direction_sobel(self, image: np.ndarray) -> str:
        """
        [BRUTAL FORENSIC] Estimates dominant shadow/light direction using Sobel gradients.
        Aggregates dominant angles of edges.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        
        magnitude, angle = cv2.cartToPolar(gx, gy, angleInDegrees=True)
        # Filter weak edges
        valid_angles = angle[magnitude > np.max(magnitude)*0.2]
        
        if len(valid_angles) == 0:
            return "Diffuse (Mendung/Malam)"
            
        median_angle = np.median(valid_angles)
        if 45 < median_angle < 135: return "Light source from Top/High Noon"
        elif 135 < median_angle <= 225: return "Light source from Right (Sore/Timur)"
        elif 225 < median_angle < 315: return "Light source from Bottom (Artificial)"
        else: return "Light source from Left (Pagi/Barat)"

    def analyze(self, image_path: str) -> Dict[str, Any]:
        """Runs the FULL BRUTAL forensics pipeline on the target file."""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found at {image_path}")
            
        cv_img = cv2.imread(image_path)
        if cv_img is None:
            raise ValueError("Failed to load image via OpenCV.")
            
        blurry_threshold = 100.0
        
        blur_score = self._compute_laplacian_variance(cv_img)
        ca_score = self._detect_chromatic_aberration(cv_img)
        ela_score = self._detect_manipulation_ela(image_path)
        light_dir = self._estimate_lighting_direction_sobel(cv_img)
        
        lighting_stats = self._estimate_time_of_day_physics(image_path)
        exif_stats = self._extract_exif_metadata(image_path)
        
        return {
            "forensics_timestamp": "ACTIVE",
            "resolution": f"{cv_img.shape[1]}x{cv_img.shape[0]}",
            "exif_metadata": exif_stats,
            "structural_analysis": {
                "blur_score_laplacian": blur_score,
                "is_blurred": bool(blur_score < blurry_threshold),
                "chromatic_aberration_intensity": ca_score,
                "zoom_indicator": "High (Optically Altered)" if ca_score > 15 else "Normal",
                "manipulation_ela_score": ela_score,
                "is_likely_manipulated": ela_score > 15.0
            },
            "lighting_physics": {
                "perceived_brightness": lighting_stats["perceived_brightness"],
                "color_balance": lighting_stats["color_balance"],
                "lighting_assumption": lighting_stats["lighting_assumption"],
                "dominant_shadow_direction": light_dir
            }
        }


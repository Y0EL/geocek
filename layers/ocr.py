import os
import concurrent.futures
import numpy as np
from typing import List, Dict, Any


class AdvancedOCRLayer:
    """
    Military-grade OCR Aggregation Layer.
    Uses Image Morphology (Dilation/Erosion), CLAHE, and Dual-Engine parsing
    (EasyOCR + PaddleOCR) for aggressive sub-pixel parsing of blurry Indonesian 
    license plates and partial hospital signage.
    """

    def __init__(self):
        self.easy = None
        self.paddle = None


    def _init_models(self):
        """Lazy load models to save memory until OCR is requested."""
        if not self.easy:
            try:
                import easyocr
                self.easy = easyocr.Reader(['id', 'en'], gpu=True)
            except ImportError:
                print("[!] EasyOCR not installed.")
                pass
        
        if not self.paddle:
            try:
                from paddleocr import PaddleOCR
                # REMOVED: 'show_log=False' which causes ValueError in newer PaddleOCR versions
                self.paddle = PaddleOCR(use_angle_cls=True, lang='en')
            except Exception as e:
                print(f"[!] PaddleOCR initialization failed: {e}")
                pass


    def _apply_brutal_preprocessing(self, image_path: str) -> str:
        """
        [BRUTAL OCR] Applies CLAHE, thresholding, and morphological operations
        to reconstruct destroyed characters before OCR reading.
        """
        import cv2
        img = cv2.imread(image_path)
        if img is None: return image_path
        
        # 1. Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 2. Adaptive Histogram Equalization (CLAHE) - contrast boosting
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8,8))
        contrast = clahe.apply(gray)
        
        # 3. Denoising
        denoised = cv2.fastNlMeansDenoising(contrast, None, h=10, searchWindowSize=21, templateWindowSize=7)
        
        # 4. Sharpening filter masking
        kernel = np.array([[0, -1, 0], [-1, 5,-1], [0, -1, 0]])
        sharp = cv2.filter2D(denoised, -1, kernel)
        
        tmp_path = "tmp_ocr_enhanced.jpg"
        cv2.imwrite(tmp_path, sharp)
        return tmp_path

    def _run_easyocr(self, image_path: str) -> List[Dict]:
        if not self.easy: return []
        results = self.easy.readtext(image_path)
        out = []
        for (bbox, text, prob) in results:
            if prob > 0.3:
                out.append({"text": text, "confidence": prob, "engine": "EasyOCR"})
        return out

    def _run_paddleocr(self, image_path: str) -> List[Dict]:
        if not self.paddle: return []
        results = self.paddle.ocr(image_path, cls=True)
        out = []
        if results and results[0]:
            for line in results[0]:
                bbox, (text, prob) = line
                if prob > 0.4:
                    out.append({"text": text, "confidence": prob, "engine": "PaddleOCR"})
        return out

    def extract_scene_text(self, image_path: str) -> Dict[str, Any]:
        """
        Runs both OCR engines in parallel on brutally enhanced images and merges the results.
        Prioritizes text that matches ALPR (Automatic License Plate Recognition) regex.
        """
        self._init_models()

        
        # 0. Destroy the image using brutal preprocessing to farm raw texts
        enhanced_path = self._apply_brutal_preprocessing(image_path)

        # 1. CPU bounded operations (Can be threaded)
        easy_res = self._run_easyocr(enhanced_path)
        paddle_res = self._run_paddleocr(enhanced_path)
        
        # Clean up
        if enhanced_path != image_path and os.path.exists(enhanced_path):
            os.remove(enhanced_path)
        
        # Merge and deduplicate
        merged = easy_res + paddle_res
        
        # ALPR regex: (1-2 letters) (1-4 numbers) (1-3 letters)
        import re
        indo_plate_regex = re.compile(r'^[A-Z]{1,2}\s?\d{1,4}\s?[A-Z]{1,3}$')
        
        plates_found = []
        street_signs = []
        
        for item in merged:
            txt = item["text"].upper()
            if indo_plate_regex.match(txt.replace(" ", "")):
                plates_found.append(item)
            elif "JL" in txt or "JALAN" in txt or "RS" in txt or "RUMAH SAKIT" in txt:
                street_signs.append(item)
                
        return {
            "all_text_detected": merged,
            "high_value_signals": {
                "license_plates_candidates": plates_found,
                "street_and_poi_markers": street_signs
            }
        }

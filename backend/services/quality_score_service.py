"""Document Quality and Completeness Scoring Service for Module 14.

Computes a transparent, technical score from 0 to 100 based on:
1. Image Quality (OpenCV blur, brightness, skew) - 30%
2. OCR Confidence (Actual EasyOCR / PaddleOCR confidence values) - 30%
3. Required-Field Completeness (Proportion of applicable mandatory fields extracted) - 40%

Handles component unavailability by normalizing remaining weights without fabricated data.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from services.consistency_service import REQUIRED_FIELDS_BY_TYPE

# Configurable Default Component Weights
DEFAULT_WEIGHTS: Dict[str, float] = {
    "image_quality": 0.30,
    "ocr_confidence": 0.30,
    "field_completeness": 0.40,
}


@dataclass
class QualityScoreReport:
    """Detailed document technical quality and extraction completeness assessment."""

    overall_score: float  # 0 to 100
    category: str  # 'Good quality and completeness', 'Review recommended', 'Manual review strongly recommended'
    recommendation: str
    weights_used: Dict[str, float]

    # Component Scores (0 to 100, or None if unavailable)
    image_quality_score: Optional[float]
    ocr_confidence_score: Optional[float]
    field_completeness_score: float

    # Explanations
    missing_required_fields: List[str] = field(default_factory=list)
    score_reduction_factors: List[str] = field(default_factory=list)
    component_details: Dict[str, Any] = field(default_factory=dict)
    disclaimer: str = (
        "This is a technical document quality and extraction completeness score, "
        "not a probability of authenticity, fraud, or legal validity."
    )
    evaluated_at: str = ""


def compute_image_quality_score(
    blur_score: Optional[float],
    brightness_score: Optional[float],
    skew_angle: Optional[float],
) -> Tuple[float, List[str], Dict[str, Any]]:
    """Compute technical image quality score (0 to 100) from OpenCV metrics."""
    factors: List[str] = []
    details: Dict[str, Any] = {}

    # 1. Blur Sub-score (max 45 points)
    blur_pts = 45.0
    if blur_score is not None:
        details["blur_laplacian_variance"] = round(blur_score, 1)
        if blur_score < 40.0:
            blur_pts = max(10.0, blur_score * 0.5)
            factors.append(f"High image blur detected (variance: {blur_score:.1f} < 40).")
        elif blur_score < 80.0:
            blur_pts = 20.0 + (blur_score - 40.0) * 0.5
            factors.append(f"Moderate image softness/blur detected (variance: {blur_score:.1f}).")
        else:
            blur_pts = min(45.0, 35.0 + (blur_score - 80.0) * 0.1)
    else:
        blur_pts = 35.0

    # 2. Brightness Sub-score (max 35 points)
    bright_pts = 35.0
    if brightness_score is not None:
        details["brightness_mean"] = round(brightness_score, 1)
        if brightness_score < 60.0:
            bright_pts = max(5.0, brightness_score * 0.3)
            factors.append(f"Image is underexposed / too dark (mean: {brightness_score:.1f}).")
        elif brightness_score > 200.0:
            bright_pts = max(10.0, 35.0 - (brightness_score - 200.0) * 0.4)
            factors.append(f"Image is overexposed / washed out (mean: {brightness_score:.1f}).")
        elif brightness_score < 85.0 or brightness_score > 180.0:
            bright_pts = 28.0
            factors.append("Image brightness is sub-optimal.")
        else:
            bright_pts = 35.0
    else:
        bright_pts = 28.0

    # 3. Skew Alignment Sub-score (max 20 points)
    skew_pts = 20.0
    if skew_angle is not None:
        abs_skew = abs(skew_angle)
        details["skew_angle_degrees"] = round(skew_angle, 2)
        if abs_skew > 5.0:
            skew_pts = max(2.0, 20.0 - abs_skew * 2.0)
            factors.append(f"Significant page rotation / tilt detected ({skew_angle:+.1f}°).")
        elif abs_skew > 1.5:
            skew_pts = 14.0
            factors.append(f"Minor page skew detected ({skew_angle:+.1f}°).")
        else:
            skew_pts = 20.0
    else:
        skew_pts = 16.0

    total_img_score = round(min(100.0, max(0.0, blur_pts + bright_pts + skew_pts)), 1)
    details["blur_subscore"] = round(blur_pts, 1)
    details["brightness_subscore"] = round(bright_pts, 1)
    details["skew_subscore"] = round(skew_pts, 1)

    return total_img_score, factors, details


def calculate_document_quality_score(
    document_type: str,
    extracted_fields: Mapping[str, Any],
    quality_assessment: Optional[Any] = None,
    ocr_confidence: Optional[float] = None,
    custom_weights: Optional[Dict[str, float]] = None,
) -> QualityScoreReport:
    """Calculate the transparent Module 14 Document Quality & Completeness Score.
    
    Weights default to:
    - Image Quality: 30%
    - OCR Confidence: 30%
    - Required-Field Completeness: 40%
    
    If OCR confidence or Image Quality is unavailable, remaining weights are normalized.
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    base_weights = dict(custom_weights or DEFAULT_WEIGHTS)
    reduction_factors: List[str] = []
    comp_details: Dict[str, Any] = {}

    # 1. Required-Field Completeness (Always available)
    required_fields = REQUIRED_FIELDS_BY_TYPE.get(document_type, REQUIRED_FIELDS_BY_TYPE["Generic Document"])
    missing_fields: List[str] = []
    present_count = 0

    fields_dict = dict(extracted_fields)
    # Check aliases
    if "Certificate Number" not in fields_dict:
        for k in ["PAN Number", "Driving Licence Number", "Registration Number"]:
            if fields_dict.get(k):
                fields_dict["Certificate Number"] = fields_dict[k]
                break

    if "Citizen Name" not in fields_dict:
        for k in ["Name", "Applicant Name", "Child Name"]:
            if fields_dict.get(k):
                fields_dict["Citizen Name"] = fields_dict[k]
                break

    for req in required_fields:
        val = fields_dict.get(req)
        if val and str(val).strip():
            present_count += 1
        else:
            missing_fields.append(req)

    total_req = max(1, len(required_fields))
    completeness_score = round((present_count / total_req) * 100.0, 1)
    comp_details["field_completeness"] = {
        "required_total": total_req,
        "required_present": present_count,
        "missing_fields": missing_fields,
    }

    if missing_fields:
        reduction_factors.append(f"Missing required fields: {', '.join(missing_fields)}.")

    # 2. Image Quality Assessment
    image_score: Optional[float] = None
    if quality_assessment is not None:
        blur_val = getattr(quality_assessment, "blur_score", None)
        bright_val = getattr(quality_assessment, "brightness_score", None)
        skew_val = getattr(quality_assessment, "skew_angle", None)
        image_score, img_factors, img_det = compute_image_quality_score(blur_val, bright_val, skew_val)
        reduction_factors.extend(img_factors)
        comp_details["image_quality"] = img_det

    # 3. OCR Confidence Assessment (Use actual EasyOCR / PaddleOCR confidence if available)
    ocr_conf_score: Optional[float] = None
    if ocr_confidence is not None and ocr_confidence >= 0.0:
        # Scale to 0-100 if provided as 0.0-1.0
        scaled_conf = ocr_confidence * 100.0 if ocr_confidence <= 1.0 else ocr_confidence
        ocr_conf_score = round(min(100.0, max(0.0, scaled_conf)), 1)
        comp_details["ocr_confidence"] = {"raw_confidence": ocr_confidence, "score": ocr_conf_score}
        if ocr_conf_score < 70.0:
            reduction_factors.append(f"OCR recognition confidence is low ({ocr_conf_score:.1f}%).")

    # 4. Weight Normalization for Available Components
    available_weights: Dict[str, float] = {"field_completeness": base_weights.get("field_completeness", 0.40)}

    if image_score is not None:
        available_weights["image_quality"] = base_weights.get("image_quality", 0.30)
    if ocr_conf_score is not None:
        available_weights["ocr_confidence"] = base_weights.get("ocr_confidence", 0.30)

    total_available_weight = sum(available_weights.values())
    normalized_weights = {k: v / total_available_weight for k, v in available_weights.items()}

    # Calculate Weighted Overall Score
    weighted_sum = completeness_score * normalized_weights["field_completeness"]
    if image_score is not None:
        weighted_sum += image_score * normalized_weights["image_quality"]
    if ocr_conf_score is not None:
        weighted_sum += ocr_conf_score * normalized_weights["ocr_confidence"]

    overall_score = round(min(100.0, max(0.0, weighted_sum)), 1)

    # 5. Score Interpretation Categories & Actionable Recommendations
    if overall_score >= 85.0:
        category = "Good quality and completeness"
        recommendation = "Document details are clear and extraction is complete. Ready for verification."
    elif overall_score >= 65.0:
        category = "Review recommended"
        if missing_fields:
            recommendation = f"Review and supply missing field(s): {', '.join(missing_fields)}."
        elif image_score is not None and image_score < 65.0:
            recommendation = "Review document image; upload a clearer scan if fine details are illegible."
        else:
            recommendation = "Review highlighted fields before final approval."
    else:
        category = "Manual review strongly recommended"
        if missing_fields and (image_score is not None and image_score < 50.0):
            recommendation = "Critical fields are missing and image is degraded. Re-scan or manually input values."
        elif missing_fields:
            recommendation = f"Critical fields missing ({', '.join(missing_fields)}). Human correction required."
        else:
            recommendation = "Low extraction confidence. Verify all fields against original document."

    return QualityScoreReport(
        overall_score=overall_score,
        category=category,
        recommendation=recommendation,
        weights_used=normalized_weights,
        image_quality_score=image_score,
        ocr_confidence_score=ocr_conf_score,
        field_completeness_score=completeness_score,
        missing_required_fields=missing_fields,
        score_reduction_factors=reduction_factors,
        component_details=comp_details,
        evaluated_at=now_iso,
    )

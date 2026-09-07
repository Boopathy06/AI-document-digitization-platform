"""OpenCV image quality assessment service for Module 3."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
BLUR_THRESHOLD = 80.0
DARK_BRIGHTNESS_THRESHOLD = 70.0
BRIGHT_BRIGHTNESS_THRESHOLD = 190.0
SKEW_THRESHOLD_DEGREES = 1.0


class QualityAssessmentError(Exception):
    """Raised when an uploaded document cannot be assessed as an image."""


@dataclass(frozen=True)
class QualityAssessment:
    """Measurements and beginner-friendly quality labels for one image."""

    blur_score: float
    blur_status: str
    brightness_score: float
    brightness_status: str
    skew_angle: float | None
    rotation_status: str


def assess_image(document_path: str | Path) -> QualityAssessment:
    """Measure blur, brightness, and document skew for an image file."""
    path = Path(document_path)
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise QualityAssessmentError(
            "Image quality assessment currently supports PNG, JPG, and JPEG files."
        )

    image = cv2.imread(str(path))
    if image is None:
        raise QualityAssessmentError("Unable to open this image for quality assessment.")

    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(grayscale, cv2.CV_64F).var())
    brightness_score = float(np.mean(grayscale))
    skew_angle = estimate_skew_angle(grayscale)

    return QualityAssessment(
        blur_score=blur_score,
        blur_status="Blurry" if blur_score < BLUR_THRESHOLD else "Clear",
        brightness_score=brightness_score,
        brightness_status=brightness_label(brightness_score),
        skew_angle=skew_angle,
        rotation_status=rotation_label(skew_angle),
    )


def estimate_skew_angle(grayscale: np.ndarray) -> float | None:
    """Estimate page skew from horizontal and vertical lines using Hough lines."""
    edges = cv2.Canny(grayscale, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=max(30, grayscale.shape[1] // 5),
        maxLineGap=15,
    )
    if lines is None:
        return None

    angles: list[float] = []
    # OpenCV versions return either (N, 1, 4) or (N, 4).
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        # Treat vertical lines as their nearest horizontal equivalent.
        if angle > 45:
            angle -= 90
        elif angle < -45:
            angle += 90
        if abs(angle) <= 20:
            angles.append(angle)

    return round(float(np.median(angles)), 2) if angles else None


def brightness_label(score: float) -> str:
    if score < DARK_BRIGHTNESS_THRESHOLD:
        return "Too dark"
    if score > BRIGHT_BRIGHTNESS_THRESHOLD:
        return "Too bright"
    return "Good"


def rotation_label(angle: float | None) -> str:
    if angle is None:
        return "Could not estimate"
    if abs(angle) < SKEW_THRESHOLD_DEGREES:
        return "Straight"
    direction = "clockwise" if angle > 0 else "counter-clockwise"
    return f"Skewed {abs(angle):.2f}° {direction}"

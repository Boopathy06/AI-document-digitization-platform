"""OpenCV image enhancement service for Module 4.

Optimized for high-accuracy OCR on government documents, certificates, and ID cards.
Handles low-resolution scans, contrast lifting, sharp scaling, and rotation correction.
"""

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
TOO_DARK_THRESHOLD = 85.0
TARGET_DARK_IMAGE_BRIGHTNESS = 140.0


class ImageEnhancementError(Exception):
    """Raised when an uploaded document cannot be enhanced as an image."""


@dataclass(frozen=True)
class EnhancementResult:
    """Details of an enhanced document image."""

    output_path: Path
    actions: tuple[str, ...]


def enhance_image(
    document_path: str | Path,
    output_folder: str | Path,
    skew_angle: float | None = None,
) -> EnhancementResult:
    """Create an OCR-ready enhanced copy with optimal sharpness, contrast, and resolution."""
    source_path = Path(document_path)
    if source_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ImageEnhancementError(
            "Image enhancement currently supports PNG, JPG, and JPEG files."
        )

    image = cv2.imread(str(source_path))
    if image is None:
        raise ImageEnhancementError("Unable to open this image for enhancement.")

    height, width = image.shape[:2]
    actions: list[str] = []

    # 1. Convert to grayscale
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    original_brightness = float(grayscale.mean())

    # 2. Intelligent Rescaling for Low-Resolution Documents:
    # Full-page government documents at < 1200px have font sizes of only 5-8px.
    # High-quality Lanczos-4 upscaling brings small text into the optimal EasyOCR size range.
    if width < 1200 or height < 1500:
        scale = max(2.0, min(3.0, 1800.0 / max(width, height)))
        new_w = int(width * scale)
        new_h = int(height * scale)
        enhanced = cv2.resize(grayscale, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        actions.append(f"Super-resolution upscaled {scale:.1f}x (INTER_LANCZOS4)")
    else:
        enhanced = grayscale.copy()
        actions.append("Native high resolution preserved")

    # 3. Controlled Denoising (Preserve Thin Letter Strokes)
    # Heavy fastNlMeans denoise destroys fine lines in low-res scans.
    # Bilateral filter preserves sharp character edges while flattening paper grain.
    enhanced = cv2.bilateralFilter(enhanced, d=5, sigmaColor=25, sigmaSpace=25)
    actions.append("Edge-preserving smoothing applied")

    # 4. Adaptive Local Contrast Enhancement (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    enhanced = clahe.apply(enhanced)
    actions.append("Local contrast enhanced (CLAHE)")

    # 5. Text Edge Sharpening (Unsharp Masking)
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=1.5)
    enhanced = cv2.addWeighted(enhanced, 1.4, gaussian, -0.4, 0)
    actions.append("Text edge sharpening applied")

    # 6. Brightness Correction for Dark Scans
    if original_brightness < TOO_DARK_THRESHOLD:
        enhanced = brighten_dark_image(enhanced, original_brightness)
        actions.append("Dark scan brightness lifted")

    # 7. Deskew / Rotation Correction
    if skew_angle is not None and abs(skew_angle) >= 1.0:
        enhanced = rotate_image(enhanced, -skew_angle)
        actions.append(f"Rotation corrected ({abs(skew_angle):.2f}°)")

    destination_folder = Path(output_folder)
    destination_folder.mkdir(parents=True, exist_ok=True)
    output_path = destination_folder / f"enhanced_{uuid4().hex}.png"
    if not cv2.imwrite(str(output_path), enhanced):
        raise ImageEnhancementError("Could not save the enhanced image.")

    return EnhancementResult(output_path=output_path, actions=tuple(actions))


def rotate_image(image: np.ndarray, angle: float) -> np.ndarray:
    """Rotate an image around its centre while retaining a clean white background."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )


def brighten_dark_image(image: np.ndarray, current_brightness: float) -> np.ndarray:
    """Use gamma correction to lift a dark scan without clipping highlights."""
    safe_brightness = max(current_brightness, 1.0)
    gamma = np.log(TARGET_DARK_IMAGE_BRIGHTNESS / 255) / np.log(safe_brightness / 255)
    gamma = float(np.clip(gamma, 0.35, 0.95))
    lookup_table = np.array([((value / 255.0) ** gamma) * 255 for value in range(256)]).astype("uint8")
    return cv2.LUT(image, lookup_table)

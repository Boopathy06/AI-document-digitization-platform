"""OpenCV image enhancement service for Module 4."""

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
TOO_DARK_THRESHOLD = 70.0
TARGET_DARK_IMAGE_BRIGHTNESS = 135.0


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
    """Create an OCR-ready enhanced copy without changing the original file."""
    source_path = Path(document_path)
    if source_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ImageEnhancementError(
            "Image enhancement currently supports PNG, JPG, and JPEG files."
        )

    image = cv2.imread(str(source_path))
    if image is None:
        raise ImageEnhancementError("Unable to open this image for enhancement.")

    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    original_brightness = float(grayscale.mean())

    # A light denoise avoids smearing thin characters, which is especially
    # important for screenshots and already-clear scanned documents.
    denoised = cv2.fastNlMeansDenoising(grayscale, None, h=6, templateWindowSize=7, searchWindowSize=21)
    enhanced = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(denoised)
    actions = ["Light denoising", "Local contrast enhanced"]

    if original_brightness < TOO_DARK_THRESHOLD:
        enhanced = brighten_dark_image(enhanced, original_brightness)
        # Otsu uses one image-wide threshold and avoids the halo artefacts that
        # adaptive thresholding can create around screen text and table borders.
        _, enhanced = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        actions.extend(["Brightness corrected", "Binary threshold applied for dark scan"])
    else:
        actions.append("Natural grayscale preserved (threshold not needed)")
    if skew_angle is not None and abs(skew_angle) >= 1.0:
        enhanced = rotate_image(enhanced, -skew_angle)
        actions.append(f"Rotation corrected ({abs(skew_angle):.2f}°)")

    enhanced, scale_factor = upscale_small_document(enhanced)
    if scale_factor > 1:
        actions.append(f"Upscaled {scale_factor}x for small-text OCR")

    destination_folder = Path(output_folder)
    destination_folder.mkdir(parents=True, exist_ok=True)
    output_path = destination_folder / f"enhanced_{uuid4().hex}.png"
    if not cv2.imwrite(str(output_path), enhanced):
        raise ImageEnhancementError("Could not save the enhanced image.")

    return EnhancementResult(output_path=output_path, actions=tuple(actions))


def rotate_image(image, angle: float):
    """Rotate an image around its centre while retaining a white background."""
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


def brighten_dark_image(image, current_brightness: float):
    """Use gamma correction to lift a dark scan before thresholding it."""
    safe_brightness = max(current_brightness, 1.0)
    gamma = np.log(TARGET_DARK_IMAGE_BRIGHTNESS / 255) / np.log(safe_brightness / 255)
    gamma = float(np.clip(gamma, 0.30, 1.0))
    lookup_table = np.array([((value / 255.0) ** gamma) * 255 for value in range(256)]).astype("uint8")
    return cv2.LUT(image, lookup_table)


def upscale_small_document(image):
    """Upscale small scans so OCR can read fine print more reliably."""
    height, width = image.shape[:2]
    if max(height, width) >= 1600:
        return image, 1
    return cv2.resize(image, (width * 2, height * 2), interpolation=cv2.INTER_CUBIC), 2

# Smart Government Document Intelligence Platform

## Modules 1–4 — Upload, quality assessment, enhancement, and OCR

This module provides a modular Flask starting point and accepts scanned document
images or PDFs. Uploaded files are safely renamed and saved in `uploads/`.
EasyOCR then extracts all detected English text from uploaded image files.
For bilingual Tamil-English documents, EasyOCR reads both languages and removes
very low-confidence detections. Small scans are upscaled before OCR.
OpenCV also reports image blur, brightness, and estimated page rotation before
OCR begins. It then creates an enhanced PNG copy using denoising, local contrast
improvement, adaptive thresholding, and skew correction where required. OCR uses
the enhanced copy, while the original upload is preserved.

### Run

```powershell
cd backend
python app.py
```

Open `http://127.0.0.1:5000`, select a PNG, JPG, JPEG, or PDF (up to 16 MB),
and upload it. PNG/JPG/JPEG files show their extracted text after upload.
PDF upload remains available, but PDF-to-image conversion is not included yet;
the page will explain that limitation. Database storage is a later module.

The page includes an **Open enhanced image** link after a supported image upload.
Module 5 also displays labelled structured fields detected from OCR text, including
name, date of birth, certificate number, Aadhaar number, district, issue date,
registration number, gender, and common certificate types. Uncertain values are
left out instead of being guessed.

> Do not generate the complete project at once. Build the project module by
> module. Wait for my confirmation after each module before proceeding to the
> next one.

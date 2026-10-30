"""Prepares a bill photo for reading: fix rotation, cap size, lift contrast. PDFs pass through untouched."""
import io

import cv2
import numpy as np
from PIL import Image, ImageOps

MAX_SIDE = 1600


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def preprocess_image(data: bytes, max_side: int = MAX_SIDE) -> bytes:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if max(img.size) > max_side:
        scale = max_side / max(img.size)
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    lab = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    out = io.BytesIO()
    Image.fromarray(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)).save(out, "JPEG", quality=90)
    return out.getvalue()


def prepare(data: bytes) -> tuple[bytes, str, str]:
    """Return (bytes, content_type, filename) ready for Document AI."""
    if is_pdf(data):
        return data, "application/pdf", "bill.pdf"
    return preprocess_image(data), "image/jpeg", "bill.jpg"

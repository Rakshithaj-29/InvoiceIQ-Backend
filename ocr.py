import pytesseract
import platform
import cv2
import numpy as np
from PIL import Image
from pdf2image import convert_from_path

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\Program Files\poppler\poppler-26.02.0\Library\bin" if platform.system() == "Windows" else None
TESS_CONFIG = "--psm 4 --oem 3"

def preprocess(pil_image):
    img = np.array(pil_image.convert("RGB"))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, h=15)
    binary = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 15
    )
    return Image.fromarray(binary)

def extract_text(file_path):
    if file_path.lower().endswith(".pdf"):
        pages = convert_from_path(file_path, dpi=300, poppler_path=POPPLER_PATH)
        return "\n".join(
            pytesseract.image_to_string(preprocess(p), config=TESS_CONFIG)
            for p in pages
        )
    return pytesseract.image_to_string(preprocess(Image.open(file_path)), config=TESS_CONFIG)
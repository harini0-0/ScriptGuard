"""Step 0: turn a document (txt, digital PDF, scanned PDF, or image) into text.

- .txt                  read directly
- digital .pdf          text layer via pdfplumber (exact, no OCR errors)
- scanned .pdf          no usable text layer -> rasterize pages with pdftoppm -> OCR
- .png/.jpg/.jpeg/.tif  OCR with Tesseract

OCR also reports low-confidence words that contain digits. A misread dose is the most
dangerous OCR error, so the pipeline routes those cases to NEEDS_REVIEW.

Requirements on the GB10 (install before the event, works offline):
  sudo apt install tesseract-ocr poppler-utils
  pip install pytesseract pdfplumber pillow
"""
import re
import subprocess
import tempfile
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
DOC_EXTS = [".txt", ".pdf"] + sorted(IMAGE_EXTS)
LOW_CONF = 80          # Tesseract word confidence (0-100) below which a numeric word is flagged
MIN_PDF_TEXT = 40      # fewer characters than this in a PDF text layer = treat as scanned


def find_document(case_dir, stem):
    """Return the first existing file named <stem>.<ext> in priority order, or None."""
    for ext in DOC_EXTS:
        p = Path(case_dir) / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def _ocr_image(img):
    import pytesseract
    from PIL import ImageFilter, ImageOps
    img = ImageOps.autocontrast(img.convert("L"))
    if img.width < 2000:                                   # aim for roughly 300 dpi on a letter page
        img = img.resize((int(img.width * 1.5), int(img.height * 1.5)))
    img = img.filter(ImageFilter.MedianFilter(3))          # removes fax / scanner speckle
    data = pytesseract.image_to_data(img, config="--psm 4", output_type=pytesseract.Output.DICT)
    lines, low = {}, []
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        conf = float(data["conf"][i])
        if re.search(r"\d", word) and 0 <= conf < LOW_CONF:
            low.append({"word": word, "confidence": round(conf, 1)})
    text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
    return fix_ocr_confusions(text), low


# Known OCR confusions that are safe to correct because the wrong form is never valid on a
# medication line. Digits are deliberately NOT auto-corrected: a misread dose must go to review.
OCR_FIXES = [
    (re.compile(r"(?<=\d) ?meg\b"), " mcg"),
    (re.compile(r"(?<=\d) ?rng\b"), " mg"),
    (re.compile(r"\brnouth\b"), "mouth"),
    # Tall Man lettering (amLODIPine): a capital I between letters is often read as ] ! or |
    (re.compile(r"(?<=[A-Za-z])[\]!|](?=[A-Za-z])"), "I"),
]


def fix_ocr_confusions(text):
    for pattern, repl in OCR_FIXES:
        text = pattern.sub(repl, text)
    return text


def _ocr_pdf(path):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", "300", "-png", str(path), f"{tmp}/page"], check=True)
        from PIL import Image
        texts, lows = [], []
        for page in sorted(Path(tmp).glob("page*.png")):
            t, l = _ocr_image(Image.open(page))
            texts.append(t); lows += l
    return "\n".join(texts), lows


def to_text(path):
    """Returns {"text", "method", "low_confidence_numbers", "file"}."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".txt":
        return {"text": path.read_text(), "method": "text", "low_confidence_numbers": [], "file": path.name}
    if ext == ".pdf":
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if len(text.strip()) >= MIN_PDF_TEXT:
            return {"text": text, "method": "pdf_text_layer", "low_confidence_numbers": [], "file": path.name}
        text, low = _ocr_pdf(path)
        return {"text": text, "method": "ocr_scanned_pdf", "low_confidence_numbers": low, "file": path.name}
    if ext in IMAGE_EXTS:
        from PIL import Image
        text, low = _ocr_image(Image.open(path))
        return {"text": text, "method": "ocr_image", "low_confidence_numbers": low, "file": path.name}
    raise ValueError(f"Unsupported document type: {path.name}")

import pdfplumber
from pdf2image import convert_from_path
from ocr import extract_text

def extract_text_from_pdf(pdf_path):

    text = ""

    with pdfplumber.open(pdf_path) as pdf:

        for page in pdf.pages:

            page_text = page.extract_text()

            if page_text:
                text += page_text + "\n"

    return text
def extract_text_from_scanned_pdf(pdf_path):

    text = ""

    pages = convert_from_path(pdf_path,dpi=500)

    for page in pages:

        temp_path = "temp_page.jpg"

        page.save(temp_path, "JPEG")

        page_text = extract_text(temp_path)

        text += page_text + "\n"

    return text
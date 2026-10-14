from ocr import extract_text
from extract_invoice_data import extract_invoice_data
text = extract_text("uploads/reliance.jpeg")
data = extract_invoice_data(text)
print(text)
print(data)

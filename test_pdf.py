from pdf2image import convert_from_path

pages = convert_from_path("uploads/radhas.pdf")

print(f"Total pages: {len(pages)}")
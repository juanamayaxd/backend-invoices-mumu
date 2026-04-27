import pdfplumber

with pdfplumber.open("acueducto.pdf") as pdf:
    texto = pdf.pages[0].extract_text()
    print(repr(texto)) # repr() es clave porque me mostrará los saltos de línea y espacios reales
import pdfplumber

with pdfplumber.open("CERTIFICACION_101_GAS_BELMIRA_ABR.pdf") as pdf:
    texto = pdf.pages[0].extract_text()
    print(repr(texto)) # repr() es clave porque me mostrará los saltos de línea y espacios reales
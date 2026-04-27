from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from pydantic import BaseModel
from enum import Enum
from typing import Union
import pdfplumber
import re
import io

app = FastAPI(title="API Dinámica de Extracción y Comparación")

class TipoServicio(str, Enum):
    acueducto = "Acueducto"
    aseo = "Aseo"
    gas = "Gas"
    luz = "Luz"

class FacturaExtraida(BaseModel):
    empresa: str
    nit: str
    fecha_vencimiento: str
    cuenta_contrato: str
    numero_factura: str
    periodo_facturado: str
    fecha_generacion: str
    valor_pagar: str
    intereses_mora: str

class ResultadoComparacion(BaseModel):
    coinciden: bool
    mensaje: str
    diferencias: dict
    datos_factura: FacturaExtraida
    datos_dian: FacturaExtraida

PATRONES_EXTRACCION = {
    TipoServicio.acueducto: {
        "empresa": r"(EMPRESA DE ACUEDUCTO[^\n]*)",
        "nit": r"NIT[\s\.\:]*([\d\.-]+)",
        "fecha_vencimiento": r"([A-Z]{3}/\d{2}/\d{4})\s+[A-Z]{3}/\d{2}/\d{4}",
        "cuenta_contrato": r"(?:^|\n)\s*(\d{7,9})\s+\d{10,}",
        "numero_factura": r"(?:^|\n)\s*\d{7,9}\s+(\d{10,})",
        "periodo_facturado": r"([A-Z]{3}/\d{2}/\d{4}\s*-\s*[A-Z]{3}/\d{2}/\d{4})",
        "fecha_generacion": r"([A-Z]{3}/\d{2}/\d{4})\s+\d{2}:\d{2}:\d{2}",
        "valor_pagar": r"\$([\d\.,]+)\n[a-f0-9]{50,}",
        "intereses_mora": r"(mora_inexistente)"
    },
    TipoServicio.aseo: {
        "empresa": r"([^\n]+)\n\s*(?:NIT|ΝΙΤ)",
        "nit": r"(?:NIT|ΝΙΤ)[\.\s]*([\d\.-]+)",
        "fecha_vencimiento": r"\n(\d{2}/[A-Z]{3}/\d{4})\s*\n\d{6,}\s*\n[\d\.,]+",
        "cuenta_contrato": r"\n\d{2}/[A-Z]{3}/\d{4}\s*\n(\d{6,})\s*\n[\d\.,]+",
        "numero_factura": r"ELECTRÓNICO No\.\s*(\d+)",
        "periodo_facturado": r"(\d{2}/[A-Z]{3}/\d{4}\s*-\s*\d{2}/[A-Z]{3}/\d{4})",
        "fecha_generacion": r"Generación:\s*([\d-]+)",
        "valor_pagar": r"\n\d{2}/[A-Z]{3}/\d{4}\s*\n\d{6,}\s*\n([\d\.,]+)",
        "intereses_mora": r"Meses Mora:\s*([1-9]\d*)"
    },
    TipoServicio.gas: {
        "empresa": r"(GAS NATURAL[^\n]+)",
        "nit": r"-\s*([\d\.-]+)\n:TIN",
        "fecha_vencimiento": r"\d{2}\s+[A-Za-z]{3}\.\s+\d{4}\s+(\d{2}\s+[A-Za-z]{3}\.\s+\d{4})",
        "cuenta_contrato": r"\n(\d{8})\n",
        "numero_factura": r"\n(\d{16})\n",
        "periodo_facturado": r"([A-Za-z]{3}\.\s*-\s*[A-Za-z]{3}\.\s+\d{4})",
        "fecha_generacion": r"(\d{2}\s+[A-Za-z]{3}\.\s+\d{4})\s+\d{2}\s+[A-Za-z]{3}\.\s+\d{4}",
        "valor_pagar": r"([\d\.,]+)$",
        "intereses_mora": r"(mora_inexistente)"
    },
    TipoServicio.luz: {
        "empresa": r"Operador de red:\s*([A-Z\s\.]+ESP)",
        "nit": r"NIT\.\s*([\d\.-]+)",
        "fecha_vencimiento": r"Subclase Básica\s*\n(\d{2}\s+[A-Z]{3}\s*/\d{4})",
        "cuenta_contrato": r"(\d{6,}-\d)\n(?:[A-Z\s]+\n)?Ruta:",
        "numero_factura": r"Transformador:\s*\S+\s+(\d+-\d)",
        "periodo_facturado": r"USO\s+(\d{2}\s+[A-Z]{3}/\d{4}\s+[A-Z]\s+\d{2}\s+[A-Z]{3}/\d{4})",
        "fecha_generacion": r"FECHA GENERACIÓN:\s*\n(\d{2}/\d{2}/\d{4})",
        "valor_pagar": r"\$([\d\.,]+)\s+\$[\d\.,]+\s*\nESTIMADO CLIENTE:",
        "intereses_mora": r"(mora_inexistente)"
    },
    "Dian": {
        "empresa": r"15\.\s*Nombre o razón social:\s*([^\n]+)",
        "nit": r"16\.\s*NIT/CC:\s*([\d\.-]+)",
        "fecha_vencimiento": r"17\.\s*Fecha L[íi]mite de.*?D[íi]a\s*(\d+)\s*Mes\s*(\d+)\s*Año\s*(\d{4})",
        "cuenta_contrato": r"cuenta contrato N[°º]\s*(\d+)",
        "numero_factura": r"19\.\s*Número de\n[^\d]*(\d+)",
        "periodo_facturado": r"([A-Z]{3}/\d{2}/\d{4}\s*-\s*[A-Z]{3}/\d{2}/\d{4})",
        "fecha_generacion": r"19\.\s*Número de\n[^\n]*?Fecha Día\s*(\d+)\s*Mes\s*(\d+)\s*Año\s*(\d{4})",
        "valor_pagar": r"21\.\s*Valor pagar\s*\$\s*([\d\.,]+)",
        "intereses_mora": r"(mora_inexistente)"
    }
}

def normalizar_valor(s: str) -> str:
    if "No " in s:
        return ""
    s = s.upper()
    meses = {"ENE":"01", "FEB":"02", "MAR":"03", "ABR":"04", "MAY":"05", "JUN":"06", "JUL":"07", "AGO":"08", "SEP":"09", "OCT":"10", "NOV":"11", "DIC":"12"}
    for k, v in meses.items():
        s = s.replace(k, v)
    if '/' in s or '-' in s:
        partes = re.findall(r'\d+', s)
        partes.sort()
        return "".join(partes)
    s = re.sub(r'[\$\s\.\-]', '', s)
    if s.endswith(',00'):
        s = s[:-3]
    s = s.replace(',', '')
    return s

def comparar_factura_dian(datos_f: dict, datos_d: dict):
    diferencias = {}
    for k in datos_d.keys():
        if k == "intereses_mora":
            continue
        vf = normalizar_valor(datos_f.get(k, ""))
        vd = normalizar_valor(datos_d.get(k, ""))
        if vf != vd:
            diferencias[k] = {"factura": datos_f.get(k, ""), "dian": datos_d.get(k, "")}
    return len(diferencias) == 0, diferencias

def extraer_datos_dinamicos(texto: str, tipo: Union[TipoServicio, str]) -> dict:
    datos = {k: "No encontrada" if k != "intereses_mora" else "No registra" for k in FacturaExtraida.__annotations__.keys()}
    patrones = PATRONES_EXTRACCION[tipo]

    for campo, patron in patrones.items():
        match = re.search(patron, texto, re.DOTALL | re.IGNORECASE)
        if match:
            if tipo == "Dian" and campo in ["fecha_vencimiento", "fecha_generacion"] and len(match.groups()) == 3:
                dia, mes, ano = match.groups()
                meses_dict = {"1":"ENE","2":"FEB","3":"MAR","4":"ABR","5":"MAY","6":"JUN","7":"JUL","8":"AGO","9":"SEP","10":"OCT","11":"NOV","12":"DIC"}
                datos[campo] = f"{meses_dict.get(mes, mes)}/{dia.zfill(2)}/{ano}"
            elif campo == "nit" and tipo == TipoServicio.gas:
                datos[campo] = match.group(1).strip()[::-1]
            else:
                datos[campo] = match.group(1).strip()
        
        if campo == "intereses_mora" and datos[campo] == "No encontrada":
            datos[campo] = "No registra"

    if tipo == TipoServicio.acueducto:
        if datos["empresa"] == "No encontrada":
            datos["empresa"] = "EMPRESA DE ACUEDUCTO Y ALCANTARILLADO DE BOGOTA - ESP"
        if datos["nit"] == "No encontrada":
            datos["nit"] = "899.999.094-1"

    return datos

@app.post("/comparar-facturas", response_model=ResultadoComparacion)
async def comparar_facturas(
    tipo_factura: TipoServicio = Form(...), 
    factura: UploadFile = File(...),
    formato_dian: UploadFile = File(...)
):
    if not factura.filename.endswith('.pdf') or not formato_dian.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Ambos archivos deben ser PDF.")
    
    try:
        cont_factura = await factura.read()
        cont_dian = await formato_dian.read()
        
        texto_dian = ""
        with pdfplumber.open(io.BytesIO(cont_dian)) as pdf_d:
            for pagina in pdf_d.pages:
                txt = pagina.extract_text()
                if txt:
                    texto_dian += txt + "\n"
        
        datos_dian = extraer_datos_dinamicos(texto_dian, "Dian")
        
        with pdfplumber.open(io.BytesIO(cont_factura)) as pdf_f:
            if tipo_factura == TipoServicio.luz:
                if len(pdf_f.pages) < 3:
                    raise HTTPException(status_code=400, detail="El PDF de luz debe tener al menos 3 páginas.")
                
                datos_base = None
                total_pagar = 0.0
                
                for i in range(2, len(pdf_f.pages)):
                    txt = pdf_f.pages[i].extract_text()
                    if txt and txt.strip():
                        datos_extraidos = extraer_datos_dinamicos(txt, tipo_factura)
                        
                        if datos_base is None:
                            datos_base = datos_extraidos.copy()
                        
                        val_str = datos_extraidos.get("valor_pagar", "0")
                        if val_str != "No encontrada":
                            val_clean = val_str.replace(".", "").replace(",", ".")
                            try:
                                total_pagar += float(val_clean)
                            except ValueError:
                                pass
                
                if datos_base:
                    formatted_total = f"{total_pagar:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    if formatted_total.endswith(",00"):
                        formatted_total = formatted_total[:-3]
                    datos_base["valor_pagar"] = formatted_total
                    datos_factura = datos_base
                else:
                    datos_factura = {k: "No encontrada" if k != "intereses_mora" else "No registra" for k in FacturaExtraida.__annotations__.keys()}
            else:
                texto_f = ""
                for pagina in pdf_f.pages:
                    txt = pagina.extract_text()
                    if txt:
                        texto_f += txt + "\n"
                datos_factura = extraer_datos_dinamicos(texto_f, tipo_factura)

        coinciden, diferencias = comparar_factura_dian(datos_factura, datos_dian)
        
        mensaje = "Los datos coinciden perfectamente." if coinciden else "Se encontraron diferencias entre los documentos."
        
        return {
            "coinciden": coinciden,
            "mensaje": mensaje,
            "diferencias": diferencias,
            "datos_factura": datos_factura,
            "datos_dian": datos_dian
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar: {str(e)}")
import io
import os
import re

try:
    import cv2
    import numpy as np
    import pytesseract
    from pytesseract import Output
    from PIL import Image, ImageFilter, ImageEnhance
    import requests as _requests
    OCR_DISPONIBLE = True
except ImportError:
    OCR_DISPONIBLE = False


pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

_RENIEC_TOKEN = os.getenv('RENIEC_TOKEN', 'apis-token-16099.nd0kCbthWLqfHqL04GbpyY3e8OE83L5G')
_RENIEC_URL = 'https://api.apis.net.pe/v2/reniec/dni'

_ETIQUETAS_DNI = {
    "PRIMER", "SEGUNDO", "APELLIDO", "APELLIDOS", "NOMBRES", "NOMBRE",
    "SEXO", "CIVIL", "UBIGEO", "NACIMIENTO", "EMISION", "CADUCIDAD",
    "FECHA", "ESTADO", "LUGAR", "DNI", "PERU", "PER",
}

_DIGIT_A_LETRA = str.maketrans("015348672", "OISAEBGZA")


# ── Carga de imagen ────────────────────────────────────────────────────────

def _bytes_a_bgr(imagen_bytes: bytes):
    arr = np.frombuffer(imagen_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No se pudo decodificar la imagen. Verifica el formato (JPG, PNG, WEBP).")
    return img


# ── Preprocesamiento ───────────────────────────────────────────────────────

def _escalar(img, min_ancho=1800):
    h, w = img.shape[:2]
    if w < min_ancho:
        factor = min_ancho / w
        img = cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    return img


def _deskew(img):
    coords = np.column_stack(np.where(img < 128))
    if len(coords) < 50:
        return img
    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.5:
        return img
    h, w = img.shape
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _preprocesar_zona(img_bgr, escala_extra=1.0):
    if escala_extra > 1.0:
        img_bgr = cv2.resize(img_bgr, None, fx=escala_extra, fy=escala_extra,
                             interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, h=12)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    gray = cv2.filter2D(gray, -1, kernel)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adapt = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 31, 10)
    return cv2.bitwise_or(otsu, adapt)


# ── Zonas de interés del DNI ───────────────────────────────────────────────

def _recortar(img_bgr, x1r, y1r, x2r, y2r):
    h, w = img_bgr.shape[:2]
    return img_bgr[int(h * y1r):int(h * y2r), int(w * x1r):int(w * x2r)]


def _zona_numero_dni(img_bgr):
    recorte = _recortar(img_bgr, 0.52, 0.04, 1.00, 0.32)
    return _preprocesar_zona(recorte, escala_extra=2.5)


def _zona_mrz(img_bgr):
    recorte = _recortar(img_bgr, 0.00, 0.72, 1.00, 1.00)
    gray = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray, h=20)
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    _, normal = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return normal, cv2.bitwise_not(normal)


# ── OCR con bounding boxes ─────────────────────────────────────────────────

def _score_datos(datos):
    confs = [float(c) for c in datos["conf"] if str(c).lstrip("-").isdigit()]
    return sum(c for c in confs if c >= 50) / (len(confs) + 1) if confs else 0


def _obtener_datos_ocr(img):
    mejor_datos, mejor_score = None, -1
    for psm in ("6", "4", "3"):
        for lang in ("spa", "eng"):
            try:
                datos = pytesseract.image_to_data(
                    img, output_type=Output.DICT,
                    config=f"--oem 3 --psm {psm} -l {lang}"
                )
                score = _score_datos(datos)
                if score > mejor_score:
                    mejor_score, mejor_datos = score, datos
            except Exception:
                pass
    if mejor_datos is None:
        raise RuntimeError("No fue posible ejecutar OCR.")
    return mejor_datos


def _ocr_digitos(img_bin):
    resultados = []
    for psm in ("7", "6", "8", "13"):
        try:
            t = pytesseract.image_to_string(
                img_bin,
                config="--oem 3 --psm " + psm + " -l eng"
                       " -c tessedit_char_whitelist=0123456789"
            )
            resultados.append(re.sub(r"\D", "", t))
        except Exception:
            pass
    resultados.sort(key=len, reverse=True)
    return resultados[0] if resultados else ""


def _construir_palabras(datos, conf_min=25):
    palabras = []
    for i, txt in enumerate(datos["text"]):
        txt = txt.strip()
        if not txt:
            continue
        try:
            conf = float(datos["conf"][i])
        except Exception:
            conf = 0
        if conf < conf_min:
            continue
        palabras.append({
            "texto": txt,
            "x": datos["left"][i],
            "y": datos["top"][i],
            "w": datos["width"][i],
            "h": datos["height"][i],
            "conf": conf,
        })
    return palabras


def _texto_completo(palabras):
    if not palabras:
        return ""
    ordenadas = sorted(palabras, key=lambda p: (p["y"], p["x"]))
    lineas, linea_actual = [], [ordenadas[0]]
    for p in ordenadas[1:]:
        if abs(p["y"] - linea_actual[-1]["y"]) < 16:
            linea_actual.append(p)
        else:
            lineas.append(sorted(linea_actual, key=lambda x: x["x"]))
            linea_actual = [p]
    lineas.append(sorted(linea_actual, key=lambda x: x["x"]))
    return "\n".join(" ".join(p["texto"] for p in l) for l in lineas)


# ── MRZ ────────────────────────────────────────────────────────────────────

def _score_mrz(texto):
    score = texto.count("<") * 3
    if re.search(r"\d{6}[0-9][MF<]", texto):
        score += 20
    if re.search(r"ID[A-Z]{3}", texto):
        score += 15
    if re.search(r"[A-Z]{3,}<<[A-Z]{2,}", texto):
        score += 10
    return score


def _ocr_mrz_zona(img_normal, img_invertida):
    mejor_texto, mejor_score = "", -1
    wl = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
    for img in (img_normal, img_invertida):
        for psm in ("6", "4", "11"):
            try:
                t = pytesseract.image_to_string(
                    img,
                    config=f"--oem 3 --psm {psm} -l eng"
                           f" -c tessedit_char_whitelist={wl}"
                )
                score = _score_mrz(t)
                if score > mejor_score:
                    mejor_score, mejor_texto = score, t
            except Exception:
                pass
    return mejor_texto


def _mrz_desde_texto_general(texto):
    candidatas = []
    for linea in texto.splitlines():
        limpia = linea.strip().replace(" ", "")
        if len(limpia) < 15:
            continue
        if "<<" in limpia and re.search(r"[A-Z]{3,}", limpia):
            candidatas.append(limpia)
        elif re.match(r"[I1][D0][A-Z]{3}", limpia.upper()) and len(limpia) >= 20:
            candidatas.append(limpia)
        elif re.match(r"\d{6}\d[MF<]", limpia) and len(limpia) >= 14:
            candidatas.append(limpia)
    return "\n".join(candidatas) if candidatas else None


def _limpiar_linea_mrz(linea):
    return (linea.upper().replace(" ", "")
            .replace("O", "0").replace("Q", "0")
            .replace("l", "1").replace("|", "1").replace("!", "1")
            .replace("S", "5").replace("B", "8")
            .replace("G", "6").replace("Z", "2"))


def _mrz_fecha(raw6):
    if not re.match(r"^\d{6}$", raw6):
        return None
    yy, mm, dd = int(raw6[:2]), raw6[2:4], raw6[4:6]
    return f"{dd}/{mm}/{2000 + yy if yy <= 30 else 1900 + yy}"


def _corregir_nombre(texto):
    if not texto:
        return None
    texto = re.sub(r'["\'\*`´#@\(\)\[\]\{\}\|\\]', '', texto)
    corregido = texto.upper().translate(_DIGIT_A_LETRA)
    corregido = re.sub(r"[^A-ZÁÉÍÓÚÜÑ\s]", "", corregido)
    return " ".join(corregido.split()) or None


def _es_etiqueta_dni(texto):
    if not texto:
        return True
    return all(p in _ETIQUETAS_DNI for p in texto.upper().split())


def _parsear_mrz(texto_mrz):
    if not texto_mrz:
        return None
    lineas_raw = [l.strip() for l in texto_mrz.splitlines() if len(l.strip()) >= 15]
    if not lineas_raw:
        return None
    lineas = [_limpiar_linea_mrz(l) for l in lineas_raw]
    resultado = {}

    linea1 = next(
        (l for l in lineas if re.match(r"[I1l][D0][A-Z]{3}", l)),
        next((l for l in lineas if len(l) >= 25), None)
    )
    if linea1:
        m = re.search(r"(?:[I1][D0][A-Z]{3})\s*([0-9]{8})", linea1)
        if not m:
            m = re.search(r"^.{3,8}([0-9]{8})", linea1)
        if m:
            resultado["numero_dni_mrz"] = m.group(1)

    linea2 = next((l for l in lineas if re.match(r"\d{6}\d[MF<]", l)), None)
    if linea2 and len(linea2) >= 14:
        resultado["fecha_nacimiento_mrz"] = _mrz_fecha(linea2[0:6])
        s = linea2[7] if len(linea2) > 7 else None
        resultado["sexo_mrz"] = s if s in ("M", "F") else None
        resultado["fecha_caducidad_mrz"] = _mrz_fecha(linea2[8:14])

    linea3 = next(
        (l for l in lineas if "<" in l and l != linea2
         and not re.match(r"\d{6}\d[MF<]", l)),
        None
    )
    if linea3:
        segmentos = [_corregir_nombre(s) for s in re.split(r"<+", linea3) if s]
        segmentos = [s for s in segmentos if s and not _es_etiqueta_dni(s)]
        if len(segmentos) >= 3:
            resultado["apellido_paterno_mrz"] = segmentos[0]
            resultado["apellido_materno_mrz"] = segmentos[1]
            resultado["nombres_mrz"] = " ".join(segmentos[2:])
        elif len(segmentos) == 2:
            resultado["apellido_paterno_mrz"] = segmentos[0]
            resultado["apellido_materno_mrz"] = None
            resultado["nombres_mrz"] = segmentos[1]
        elif len(segmentos) == 1:
            resultado["apellido_paterno_mrz"] = segmentos[0]
            resultado["apellido_materno_mrz"] = None
            resultado["nombres_mrz"] = None

    return resultado if resultado else None


# ── Búsqueda espacial de campos ────────────────────────────────────────────

def _buscar_valor_derecha(palabras, etiquetas, dist_max=700, tol_y=22):
    etiquetas_up = [e.upper() for e in etiquetas]
    for p in palabras:
        if any(e in p["texto"].upper() for e in etiquetas_up):
            candidatos = sorted(
                [q for q in palabras
                 if abs(q["y"] - p["y"]) <= tol_y
                 and q["x"] > p["x"]
                 and (q["x"] - p["x"]) < dist_max],
                key=lambda x: x["x"]
            )
            if candidatos:
                return " ".join(c["texto"] for c in candidatos)
    return None


def _buscar_valor_abajo(palabras, etiquetas, dist_max=80, tol_x=300):
    etiquetas_up = [e.upper() for e in etiquetas]
    for p in palabras:
        if any(e in p["texto"].upper() for e in etiquetas_up):
            candidatos = sorted(
                [q for q in palabras
                 if q["y"] > p["y"]
                 and (q["y"] - p["y"]) < dist_max
                 and abs(q["x"] - p["x"]) < tol_x],
                key=lambda x: x["y"]
            )
            if candidatos:
                return " ".join(c["texto"] for c in candidatos)
    return None


# ── Extracción del número DNI ──────────────────────────────────────────────

def _parece_fecha(s):
    return bool(re.match(r"^(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])(19|20)\d{2}$", s))


def _limpiar_ocr_num(txt):
    return (txt
            .replace("O", "0").replace("o", "0").replace("Q", "0").replace("D", "0")
            .replace("l", "1").replace("I", "1").replace("|", "1").replace("!", "1")
            .replace("S", "5").replace("B", "8").replace("G", "6")
            .replace("Z", "2").replace("T", "7"))


def _extraer_numero_simple(lineas: list) -> str | None:
    """Regex directo sobre cada línea — fue el que detectó correctamente el DNI."""
    for linea in lineas:
        m = re.search(r'\b(\d{8})\b', linea)
        if m:
            candidato = m.group(1)
            if not _parece_fecha(candidato):
                return candidato
    return None


def _extraer_numero_dni_spatial(texto, palabras, zona_num_img=None):
    """Enfoque espacial como segundo intento."""
    def _validar(s):
        s = _limpiar_ocr_num(re.sub(r"\D", "", s))
        return s[:8] if len(s) >= 8 and not _parece_fecha(s[:8]) else None

    if zona_num_img is not None:
        v = _validar(_ocr_digitos(zona_num_img))
        if v:
            return v

    m = re.search(r"(\d[\d\s]{5,9}\d)\s*[-–]\s*\d{1,3}", texto)
    if m:
        v = _validar(m.group(1))
        if v:
            return v

    m = re.search(r"\bPER[<\s]*(\d[\d\s]{5,9}\d)", texto, re.IGNORECASE)
    if m:
        v = _validar(m.group(1))
        if v:
            return v

    for p in palabras:
        if re.search(r"\bDNI\b", p["texto"], re.IGNORECASE):
            for candidatos in [
                sorted([q for q in palabras if q["x"] > p["x"]
                        and abs(q["y"] - p["y"]) <= 25
                        and (q["x"] - p["x"]) < 500], key=lambda x: x["x"]),
                sorted([q for q in palabras if q["y"] > p["y"]
                        and (q["y"] - p["y"]) < 70
                        and abs(q["x"] - p["x"]) < 150], key=lambda x: x["y"]),
            ]:
                v = _validar("".join(c["texto"] for c in candidatos))
                if v:
                    return v

    for patron in [r"\bDNI\s*[:\-Nº°]?\s*([\d][\d\s]{5,10}[\d])",
                   r"(?<!\d)([\d][\d\s]{5,10}[\d])(?!\d)"]:
        for m in re.finditer(patron, texto, re.IGNORECASE):
            v = _validar(m.group(1))
            if v:
                return v

    return None


def _extraer_codigo_verificador(texto, palabras):
    m = re.search(r"(?<!\d)\d{8}\s*[-–]\s*(\d{1,3})(?!\d)", texto)
    if m:
        return m.group(1)
    for p in palabras:
        if re.search(r"\d{8}", p["texto"]):
            vecinos = sorted(
                [q for q in palabras if abs(q["y"] - p["y"]) <= 20
                 and q["x"] > p["x"] and (q["x"] - p["x"]) < 120],
                key=lambda x: x["x"]
            )
            for v in vecinos:
                cod = re.sub(r"\D", "", v["texto"])
                if 1 <= len(cod) <= 3:
                    return cod
    return None


# ── Extracción de otros campos DNI ─────────────────────────────────────────

def _extraer_apellidos(texto, palabras):
    paterno, materno = None, None

    for etq in ["PRIMER", "Primer"]:
        v = _buscar_valor_abajo(palabras, [etq], dist_max=100, tol_x=350)
        if v:
            v = _corregir_nombre(v)
            if v and not _es_etiqueta_dni(v) and len(v) >= 2:
                paterno = v
                break

    for etq in ["SEGUNDO", "Segundo"]:
        v = _buscar_valor_abajo(palabras, [etq], dist_max=100, tol_x=350)
        if v:
            v = _corregir_nombre(v)
            if v and not _es_etiqueta_dni(v) and len(v) >= 2:
                materno = v
                break

    if not paterno:
        v = _buscar_valor_abajo(palabras, ["APELLIDOS", "APELLIDO"], dist_max=100, tol_x=350)
        if v:
            v = _corregir_nombre(v)
            if v:
                partes = v.split()
                paterno = partes[0] if partes else None
                if not materno:
                    materno = partes[1] if len(partes) > 1 else None

    if not paterno:
        m = re.search(r"PRIMER\s+APELLIDO\s*[:\-]?\s*([A-ZÁÉÍÓÚÜÑ0-9 ]+)", texto, re.I)
        if m:
            paterno = _corregir_nombre(m.group(1))
    if not materno:
        m = re.search(r"SEGUNDO\s+APELLIDO\s*[:\-]?\s*([A-ZÁÉÍÓÚÜÑ0-9 ]+)", texto, re.I)
        if m:
            materno = _corregir_nombre(m.group(1))

    return paterno, materno


def _extraer_nombres(texto, palabras):
    v = _buscar_valor_abajo(palabras, ["NOMBRES", "NOMBRE"], dist_max=100, tol_x=350)
    if v:
        v = _corregir_nombre(v)
        if v and not _es_etiqueta_dni(v):
            return v
    v = _buscar_valor_derecha(palabras, ["NOMBRES", "NOMBRE"], dist_max=700, tol_y=22)
    if v:
        v = _corregir_nombre(v)
        if v and not _es_etiqueta_dni(v):
            return v
    m = re.search(r"NOMBRES?\s*[:\-]?\s*([A-ZÁÉÍÓÚÜÑ0-9 ]+)", texto, re.IGNORECASE)
    return _corregir_nombre(m.group(1)) if m else None


def _normalizar_fecha(txt):
    return re.sub(r"[.\-]", "/", txt.strip()) if txt else None


def _extraer_fecha_nacimiento(texto, palabras):
    v = _buscar_valor_derecha(palabras, ["NACIMIENTO", "F.NAC"])
    if v:
        m = re.search(r"\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}", v)
        if m:
            return _normalizar_fecha(m.group())
    m = re.search(
        r"(?:FECHA\s+DE\s+NACIMIENTO|NACIMIENTO)\s*[:\-]?\s*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})",
        texto, re.IGNORECASE
    )
    return _normalizar_fecha(m.group(1)) if m else None


def _extraer_fecha_emision(texto, palabras):
    v = _buscar_valor_derecha(palabras, ["EMISION", "EMISIÓN", "F.EMIS"])
    if v:
        m = re.search(r"\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}", v)
        if m:
            return _normalizar_fecha(m.group())
    m = re.search(
        r"(?:FECHA\s+DE\s+EMISI[OÓ]N|EMISI[OÓ]N)\s*[:\-]?\s*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})",
        texto, re.IGNORECASE
    )
    return _normalizar_fecha(m.group(1)) if m else None


def _extraer_fecha_caducidad(texto, palabras):
    v = _buscar_valor_derecha(palabras, ["VENCIMIENTO", "CADUCIDAD", "VENC", "CADUC"])
    if v:
        m = re.search(r"\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}", v)
        if m:
            return _normalizar_fecha(m.group())
    m = re.search(
        r"(?:FECHA\s+DE\s+(?:VENCIMIENTO|CADUCIDAD)|VENCIMIENTO|CADUCIDAD)\s*[:\-]?\s*"
        r"(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})",
        texto, re.IGNORECASE
    )
    return _normalizar_fecha(m.group(1)) if m else None


def _extraer_sexo(texto, palabras):
    v = _buscar_valor_derecha(palabras, ["SEXO"])
    if v:
        if re.search(r"\bM\b|MASCULINO", v.upper()):
            return "M"
        if re.search(r"\bF\b|FEMENINO", v.upper()):
            return "F"
    m = re.search(r"SEXO\s*[:\-]?\s*(M|F|MASCULINO|FEMENINO)", texto, re.IGNORECASE)
    if m:
        return "M" if m.group(1).upper().startswith("M") else "F"
    return None


def _extraer_estado_civil(texto, palabras):
    v = _buscar_valor_derecha(palabras, ["EST.CIVIL", "ESTADO CIVIL", "EST CIVIL"])
    if v:
        return _corregir_nombre(v.strip())
    m = re.search(r"(?:EST\.?\s*CIVIL|ESTADO\s+CIVIL)\s*[:\-]?\s*(\w+)", texto, re.IGNORECASE)
    return _corregir_nombre(m.group(1)) if m else None


def _extraer_ubigeo(texto, palabras):
    v = _buscar_valor_derecha(palabras, ["UBIGEO", "UBIG"])
    if v:
        m = re.search(r"\d{6}", v)
        if m:
            return m.group()
    m = re.search(r"\bUBIGEO\s*[:\-]?\s*(\d{6})\b", texto, re.IGNORECASE)
    return m.group(1) if m else None


# ── RENIEC ─────────────────────────────────────────────────────────────────

def _consultar_reniec(numero_dni: str) -> dict | None:
    try:
        r = _requests.get(
            _RENIEC_URL,
            params={"numero": numero_dni, "token": _RENIEC_TOKEN},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _completar_desde_reniec(campos: dict, reniec: dict) -> None:
    """Rellena con datos de RENIEC los campos que el OCR no detectó."""
    mapa = {
        'apellido_paterno': 'apellidoPaterno',
        'apellido_materno': 'apellidoMaterno',
        'nombres': 'nombres',
    }
    for campo_local, campo_reniec in mapa.items():
        if not campos[campo_local] and reniec.get(campo_reniec):
            campos[campo_local] = reniec[campo_reniec]

    if not campos.get('codigo_verificador') and reniec.get('digitoVerificador') is not None:
        campos['codigo_verificador'] = str(reniec['digitoVerificador'])


# ── Procesador DNI ─────────────────────────────────────────────────────────

def _procesar_dni(imagen_bytes: bytes) -> dict:
    img_color = _bytes_a_bgr(imagen_bytes)
    img_color = _escalar(img_color)
    img_bin = _preprocesar_zona(img_color)
    img_bin = _deskew(img_bin)

    # OCR con bounding boxes (para extracción espacial)
    datos_ocr = _obtener_datos_ocr(img_bin)
    palabras = _construir_palabras(datos_ocr)
    texto_espacial = _texto_completo(palabras)

    # OCR simple (para regex de 8 dígitos que funcionó)
    texto_simple = pytesseract.image_to_string(img_bin, config='--oem 3 --psm 6 -l spa+eng')
    lineas_simples = [l.strip() for l in texto_simple.splitlines() if l.strip()]

    # Zonas especializadas
    img_zona_num = _zona_numero_dni(img_color)
    img_mrz_n, img_mrz_i = _zona_mrz(img_color)

    # MRZ
    texto_mrz = _ocr_mrz_zona(img_mrz_n, img_mrz_i)
    if _score_mrz(texto_mrz) < 10:
        texto_mrz = _mrz_desde_texto_general(texto_simple) or texto_mrz
    mrz = _parsear_mrz(texto_mrz)

    # Número DNI: mi regex simple primero → espacial → MRZ
    numero_dni = _extraer_numero_simple(lineas_simples)
    if not numero_dni:
        numero_dni = _extraer_numero_dni_spatial(texto_espacial, palabras, img_zona_num)
    if not numero_dni and mrz:
        numero_dni = mrz.get('numero_dni_mrz')

    # Demás campos: enfoque espacial + MRZ como fallback
    apellido_paterno, apellido_materno = _extraer_apellidos(texto_espacial, palabras)
    if not apellido_paterno and mrz:
        apellido_paterno = mrz.get('apellido_paterno_mrz')
    if not apellido_materno and mrz:
        apellido_materno = mrz.get('apellido_materno_mrz')

    nombres = _extraer_nombres(texto_espacial, palabras)
    if not nombres and mrz:
        nombres = mrz.get('nombres_mrz')

    fecha_nac = _extraer_fecha_nacimiento(texto_espacial, palabras)
    if not fecha_nac and mrz:
        fecha_nac = mrz.get('fecha_nacimiento_mrz')

    sexo = _extraer_sexo(texto_espacial, palabras)
    if not sexo and mrz:
        sexo = mrz.get('sexo_mrz')

    fecha_cad = _extraer_fecha_caducidad(texto_espacial, palabras)
    if not fecha_cad and mrz:
        fecha_cad = mrz.get('fecha_caducidad_mrz')

    campos = {
        'numero_dni': numero_dni,
        'codigo_verificador': _extraer_codigo_verificador(texto_espacial, palabras),
        'apellido_paterno': apellido_paterno,
        'apellido_materno': apellido_materno,
        'nombres': nombres,
        'fecha_nacimiento': fecha_nac,
        'sexo': sexo,
        'estado_civil': _extraer_estado_civil(texto_espacial, palabras),
        'ubigeo': _extraer_ubigeo(texto_espacial, palabras),
        'fecha_emision': _extraer_fecha_emision(texto_espacial, palabras),
        'fecha_caducidad': fecha_cad,
    }

    # Consulta RENIEC para completar campos no detectados
    reniec_data = None
    if numero_dni and len(numero_dni) == 8 and numero_dni.isdigit():
        reniec_data = _consultar_reniec(numero_dni)
        if reniec_data:
            _completar_desde_reniec(campos, reniec_data)

    return {
        'tipo_documento': 'DNI',
        'campos': campos,
        'reniec': reniec_data,
        'texto_raw': texto_simple,
    }


# ── Procesador Carnet de Extranjería (Pillow, más simple) ──────────────────

def _procesar_carnet(imagen_bytes: bytes) -> dict:
    img = Image.open(io.BytesIO(imagen_bytes)).convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    w, h = img.size
    if w < 800:
        factor = 800 / w
        img = img.resize((int(w * factor), int(h * factor)), Image.LANCZOS)

    texto = pytesseract.image_to_string(img, config='--oem 3 --psm 6 -l spa+eng')
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]

    numero_carnet = None
    for linea in lineas:
        m = re.search(r'\b([A-Z]{0,3}\d{6,9})\b', linea)
        if m:
            numero_carnet = m.group(1)
            break

    fecha_nacimiento = None
    patron_fecha = re.compile(r'\b(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})\b')
    for linea in lineas:
        m = patron_fecha.search(linea)
        if m:
            fecha_nacimiento = m.group(1)
            break

    sexo = None
    for linea in lineas:
        u = linea.upper()
        if re.search(r'\bMASCULINO\b|\bMASC\b', u):
            sexo = 'M'
            break
        if re.search(r'\bFEMENINO\b|\bFEM\b', u):
            sexo = 'F'
            break

    nacionalidad = None
    for i, linea in enumerate(lineas):
        if re.search(r'NACIONAL', linea.upper()):
            partes = linea.split(':')
            if len(partes) > 1 and partes[1].strip():
                nacionalidad = partes[1].strip().upper()
            elif i + 1 < len(lineas):
                nacionalidad = lineas[i + 1].upper()
            break

    patron_letras = re.compile(r'^[A-ZÁÉÍÓÚÑÜA-Z\s\-]+$', re.IGNORECASE)
    nombres_lineas = [l.upper() for l in lineas if patron_letras.match(l) and len(l.strip()) >= 2]
    apellidos = nombres_lineas[0] if len(nombres_lineas) >= 1 else None
    nombre = nombres_lineas[1] if len(nombres_lineas) >= 2 else None

    return {
        'tipo_documento': 'CARNET_EXTRANJERIA',
        'campos': {
            'numero_carnet': numero_carnet,
            'apellidos': apellidos,
            'nombre': nombre,
            'nacionalidad': nacionalidad,
            'fecha_nacimiento': fecha_nacimiento,
            'sexo': sexo,
        },
        'reniec': None,
        'texto_raw': texto,
    }


# ── API pública ────────────────────────────────────────────────────────────

def detectar(imagen_bytes: bytes, tipo_documento: str) -> dict:
    if not OCR_DISPONIBLE:
        raise RuntimeError(
            'Faltan dependencias: pip install pytesseract Pillow opencv-python requests. '
            'También instala Tesseract: https://github.com/UB-Mannheim/tesseract/wiki'
        )
    try:
        if tipo_documento == 'DNI':
            return _procesar_dni(imagen_bytes)
        else:
            return _procesar_carnet(imagen_bytes)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f'Error al procesar la imagen: {exc}. '
            'Verifica que Tesseract esté instalado correctamente.'
        ) from exc

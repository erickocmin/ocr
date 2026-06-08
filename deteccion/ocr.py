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

# fastmrz: MRZ con modelos ONNX + validación de checksum ICAO (pip install fastmrz)
try:
    from fastmrz import FastMRZ as _FastMRZ
    _fast_mrz = _FastMRZ()
    FASTMRZ_DISPONIBLE = True
except Exception:
    FASTMRZ_DISPONIBLE = False


pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"

# ── Lazy loaders para motores alternativos (easyocr, paddleocr) ────────────
# Se inicializan solo cuando se necesitan para no penalizar el arranque.
_easy_ocr_reader   = None
_paddle_ocr_instance = None


def _get_easyocr():
    global _easy_ocr_reader
    if _easy_ocr_reader is None:
        try:
            import easyocr  # noqa: PLC0415
            _easy_ocr_reader = easyocr.Reader(['es', 'en'], gpu=False, verbose=False)
        except Exception:
            pass
    return _easy_ocr_reader


def _get_paddleocr():
    global _paddle_ocr_instance
    if _paddle_ocr_instance is None:
        # Bug conocido: PaddlePaddle 3.x en Windows usa oneDNN con PIR, lo que falla
        # con ciertos modelos. Deshabilitar PIR antes de importar paddle.
        import os  # noqa: PLC0415
        os.environ.setdefault('FLAGS_enable_pir_api', '0')
        for lang in ('es', 'latin', 'en'):
            # PaddleOCR v3 (paddlex) sin clasificadores de orientacion (evitar el bug oneDNN)
            try:
                from paddleocr import PaddleOCR  # noqa: PLC0415
                _paddle_ocr_instance = PaddleOCR(
                    lang=lang,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
                break
            except Exception:
                pass
            # PaddleOCR v2 — API clásica
            try:
                from paddleocr import PaddleOCR  # noqa: PLC0415
                _paddle_ocr_instance = PaddleOCR(
                    lang=lang, use_angle_cls=True, show_log=False, use_gpu=False
                )
                break
            except Exception:
                continue
    return _paddle_ocr_instance

_RENIEC_TOKEN = os.getenv('RENIEC_TOKEN', 'apis-token-16099.nd0kCbthWLqfHqL04GbpyY3e8OE83L5G')
_RENIEC_URL = 'https://api.apis.net.pe/v2/reniec/dni'

_ETIQUETAS_DNI = {
    "PRIMER", "SEGUNDO", "APELLIDO", "APELLIDOS", "NOMBRES", "NOMBRE",
    "SEXO", "CIVIL", "UBIGEO", "NACIMIENTO", "EMISION", "CADUCIDAD",
    "FECHA", "ESTADO", "LUGAR", "DNI", "PERU", "PER", "PRE",
    "INSCRIPCION", "INSCRIPCIÓN", "IDENTIDAD", "NACIONAL", "REGISTRO",
}

_DIGIT_A_LETRA = str.maketrans("015348672", "OISAEBGZA")


def _bytes_a_bgr(imagen_bytes: bytes):
    arr = np.frombuffer(imagen_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No se pudo decodificar la imagen. Verifica el formato (JPG, PNG, WEBP).")
    return img


def _rotar_si_necesario(img_bgr):
    try:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT)
        angulo = osd.get('rotate', 0)
        confianza = float(osd.get('orientation_conf', 0))
        if confianza >= 4.0 and angulo in (90, 180, 270):
            if angulo == 90:
                return cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
            if angulo == 180:
                return cv2.rotate(img_bgr, cv2.ROTATE_180)
            if angulo == 270:
                return cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
    except Exception:
        pass
    return img_bgr


def _corregir_perspectiva(img_bgr):
    h, w = img_bgr.shape[:2]
    area_total = h * w

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.dilate(edges, kernel, iterations=1)

    contornos, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return img_bgr

    contornos = sorted(contornos, key=cv2.contourArea, reverse=True)
    for cnt in contornos[:5]:
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        area_cnt = cv2.contourArea(approx)
        if len(approx) != 4:
            continue
        if area_cnt < area_total * 0.35:
            continue
        pts = approx.reshape(4, 2).astype(np.float32)
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1)
        rect = np.array([
            pts[np.argmin(s)],
            pts[np.argmin(diff)],
            pts[np.argmax(s)],
            pts[np.argmax(diff)],
        ], dtype=np.float32)
        ancho = max(int(np.linalg.norm(rect[1] - rect[0])),
                    int(np.linalg.norm(rect[2] - rect[3])))
        alto  = max(int(np.linalg.norm(rect[3] - rect[0])),
                    int(np.linalg.norm(rect[2] - rect[1])))
        ratio = ancho / alto if alto > 0 else 0
        if 1.3 < ratio < 2.0 and ancho > 50 and alto > 50:
            dst = np.array([[0, 0], [ancho - 1, 0],
                            [ancho - 1, alto - 1], [0, alto - 1]], dtype=np.float32)
            M = cv2.getPerspectiveTransform(rect, dst)
            resultado = cv2.warpPerspective(img_bgr, M, (ancho, alto))
            if resultado is not None and resultado.size > 0:
                return resultado
        break
    return img_bgr


def _escalar(img, min_ancho=1800):
    h, w = img.shape[:2]
    if w < min_ancho:
        factor = min_ancho / w
        img = cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_LANCZOS4)
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
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def _eliminar_franja_azul(img_bgr):
    """
    Elimina la franja azul vertical izquierda del DNI peruano usando HSV masking.
    Esta franja contiene el número DNI impreso verticalmente y es la causa principal
    de que el OCR encuentre el número en la posición incorrecta del texto.
    Rango HSV azul: H=[95-135], S=[50-255], V=[30-255]
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    mask_azul = cv2.inRange(hsv, np.array([95, 50, 30]), np.array([135, 255, 255]))
    # Dilatar para cubrir bordes antialiased de la franja
    kernel = np.ones((7, 7), np.uint8)
    mask_azul = cv2.dilate(mask_azul, kernel, iterations=1)
    resultado = img_bgr.copy()
    resultado[mask_azul > 0] = [255, 255, 255]
    return resultado


def _eliminar_encabezado_naranja(img_bgr):
    """Enmascara con blanco el encabezado naranja/rojo del DNI peruano
    (banda 'REPÚBLICA DEL PERÚ / RENIEC'). Evita que el OCR lea ese texto
    como parte de los campos de datos personales."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    # Naranja: H=[2-25] — Rojo bajo: H=[0-2] — Rojo alto: H=[168-180]
    mask = cv2.inRange(hsv, np.array([2, 70, 70]),   np.array([25, 255, 255]))
    mask |= cv2.inRange(hsv, np.array([0, 70, 70]),  np.array([2, 255, 255]))
    mask |= cv2.inRange(hsv, np.array([168, 70, 70]), np.array([180, 255, 255]))
    kernel = np.ones((9, 9), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=2)
    resultado = img_bgr.copy()
    resultado[mask > 0] = [255, 255, 255]
    return resultado


def _zona_texto_campos(img_bgr):
    """Recorta la zona de campos de datos del DNI peruano eliminando:
    franja azul (izq), encabezado (top), foto (der) y MRZ (bottom).
    Proporciones estimadas para DNI escaneado/fotografiado a ~1800 px de ancho."""
    h, w = img_bgr.shape[:2]
    return img_bgr[int(h * 0.13):int(h * 0.80), int(w * 0.13):int(w * 0.68)]


def _img_bgr_a_bytes(img_bgr) -> bytes:
    """Codifica imagen numpy BGR a PNG bytes (para Pillow / pytesseract)."""
    _, buf = cv2.imencode('.png', img_bgr)
    return buf.tobytes()


def _preprocesar_zona(img_bgr):
    # Canal L del espacio LAB — mejor separación de luminancia que grayscale simple
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    gray = lab[:, :, 0]

    # Bilateral filter: preserva bordes mejor que NLMeans, más rápido
    gray = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)

    # CLAHE más agresivo
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Unsharp mask para nitidez de texto
    blur = cv2.GaussianBlur(gray, (0, 0), 1.5)
    gray = cv2.addWeighted(gray, 1.8, blur, -0.8, 0)

    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adapt = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 25, 8)
    combined = cv2.bitwise_or(otsu, adapt)
    # Cierre morfológico pequeño: conecta caracteres fragmentados por el threshold
    # sin fusionar letras adyacentes (kernel 2x2 conservador a 1800px de ancho)
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    return cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel_close)


def _texto_pillow_variante(imagen_bytes: bytes, contrast: float = 2.0,
                           brightness: float = 1.0) -> str:
    img = Image.open(io.BytesIO(imagen_bytes)).convert('L')
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    w, h = img.size
    if w < 800:
        img = img.resize((int(w * 800 / w), int(h * 800 / w)), Image.LANCZOS)
    return pytesseract.image_to_string(img, config='--oem 3 --psm 6 -l spa+eng')


# Patrones para puntuar cuán bien un texto OCR refleja la estructura del DNI peruano
_LABEL_SCORE_PATS = [
    r'PRIMER\s+APELLIDO', r'SEGUNDO\s+APELLIDO', r'APELLIDO\s+PATERNO',
    r'APELLIDO\s+MATERNO', r'NOMBRES?', r'FECHA\s+DE\s+NACIMIENTO',
    r'SEXO', r'ESTADO\s+CIVIL', r'UBIGEO', r'EMISI[OÓ]N',
    r'VENCIMIENTO', r'CADUCIDAD', r'DNI\s+\d{8}',
]


def _texto_pillow_mejor(imagen_bytes: bytes) -> str:
    """Prueba múltiples combinaciones PSM/contraste y devuelve el texto
    con la mayor densidad de etiquetas DNI reconocibles."""
    variantes = [
        ('--oem 3 --psm 6 -l spa+eng', 2.0, 1.0),
        ('--oem 3 --psm 4 -l spa+eng', 2.0, 1.0),
        ('--oem 3 --psm 6 -l spa+eng', 2.8, 1.1),
        ('--oem 3 --psm 4 -l spa+eng', 1.7, 0.95),
        ('--oem 3 --psm 6 -l spa+eng', 1.5, 1.0),
    ]
    mejor_texto, mejor_score = '', -1
    base_img = Image.open(io.BytesIO(imagen_bytes)).convert('L')
    w, h = base_img.size
    if w < 1200:
        base_img = base_img.resize((1200, int(h * 1200 / w)), Image.LANCZOS)

    for config, contrast, brightness in variantes:
        try:
            img = base_img.copy()
            if brightness != 1.0:
                img = ImageEnhance.Brightness(img).enhance(brightness)
            img = ImageEnhance.Contrast(img).enhance(contrast)
            img = img.filter(ImageFilter.MedianFilter(size=3))
            texto = pytesseract.image_to_string(img, config=config)
            score = sum(1 for p in _LABEL_SCORE_PATS if re.search(p, texto, re.I))
            if score > mejor_score:
                mejor_score, mejor_texto = score, texto
        except Exception:
            continue
    return mejor_texto



def _recortar(img_bgr, x1r, y1r, x2r, y2r):
    h, w = img_bgr.shape[:2]
    return img_bgr[int(h * y1r):int(h * y2r), int(w * x1r):int(w * x2r)]


def _zona_numero_dni(img_bgr):
    """Recorta la zona del encabezado donde aparece 'DNI XXXXXXXX-X'."""
    recorte = _recortar(img_bgr, 0.45, 0.00, 1.00, 0.28)
    gray = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_LANCZOS4)
    _, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return b


def _zona_mrz(img_bgr):
    recorte = _recortar(img_bgr, 0.00, 0.70, 1.00, 1.00)
    gray = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.fastNlMeansDenoising(gray, h=20)
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    _, normal = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return normal, cv2.bitwise_not(normal)


def _obtener_datos_ocr(img):
    mejor_datos, mejor_score = None, -1
    for psm in ("6", "4", "3"):
        for lang in ("spa+eng", "spa", "eng"):
            try:
                datos = pytesseract.image_to_data(
                    img, output_type=Output.DICT,
                    config=f"--oem 3 --psm {psm} -l {lang}"
                )
                confs = [float(c) for c in datos["conf"] if str(c).lstrip("-").isdigit()]
                score = sum(c for c in confs if c >= 50) / (len(confs) + 1) if confs else 0
                if score > mejor_score:
                    mejor_score, mejor_datos = score, datos
                break
            except Exception:
                continue
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
        if abs(p["y"] - linea_actual[-1]["y"]) < 20:
            linea_actual.append(p)
        else:
            lineas.append(sorted(linea_actual, key=lambda x: x["x"]))
            linea_actual = [p]
    lineas.append(sorted(linea_actual, key=lambda x: x["x"]))
    return "\n".join(" ".join(p["texto"] for p in l) for l in lineas)


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
        for psm in ("6", "4", "11", "7"):
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


def _nombre_mrz_valido(texto) -> bool:
    """Verifica que un valor del MRZ sea un nombre plausible (sin dígitos ni ruido)."""
    if not texto or len(texto) < 2:
        return False
    if re.search(r'\d', texto):
        return False
    return bool(re.search(r'[A-ZÁÉÍÓÚÜÑ]', texto))


def _parsear_mrz_fastmrz(imagen_bytes: bytes) -> dict | None:
    """
    MRZ usando fastmrz con modelos ONNX y checksum ICAO.
    - input_type='numpy': acepta array numpy BGR directo
    - Retorna status='SUCCESS' cuando los checksums son validos
    - Keys TD1: document_number, surname, given_name, birth_date, sex, expiry_date
    """
    if not FASTMRZ_DISPONIBLE:
        return None
    try:
        arr = np.frombuffer(imagen_bytes, np.uint8)
        img_np = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img_np is None:
            return None

        res = _fast_mrz.get_details(img_np, input_type='numpy')
        if not res or res.get('status') != 'SUCCESS':
            return None

        # document_number puede tener padding '<' (ej: "46409361<" para 8 digitos)
        doc_num  = str(res.get('document_number') or '').replace('<', '').strip()
        apellido = str(res.get('surname')         or '').replace('<', ' ').strip()
        nombres  = str(res.get('given_name')      or '').replace('<', ' ').strip()
        nac_raw  = str(res.get('birth_date')      or '')
        cad_raw  = str(res.get('expiry_date')     or '')
        sexo     = str(res.get('sex')             or '')

        partes_ap  = [p for p in apellido.split() if p and not _es_etiqueta_dni(p)]
        nombres_ok = ' '.join(n for n in nombres.split() if n and not _es_etiqueta_dni(n))

        # Normalizar fechas — fastmrz puede devolverlas como "DD/MM/YYYY" o "YYMMDD"
        def _norm(raw):
            solo_dig = re.sub(r'\D', '', raw)
            if len(solo_dig) == 6:
                return _mrz_fecha(solo_dig)
            if len(solo_dig) == 8:
                return f"{solo_dig[6:]}/{solo_dig[4:6]}/{solo_dig[:4]}"
            if '/' in raw or '-' in raw:
                return _normalizar_fecha(raw)
            return None

        return {
            'numero_dni_mrz':       doc_num if len(doc_num) == 8 and doc_num.isdigit() else None,
            'apellido_paterno_mrz': _corregir_nombre(partes_ap[0]) if partes_ap else None,
            'apellido_materno_mrz': _corregir_nombre(partes_ap[1]) if len(partes_ap) > 1 else None,
            'nombres_mrz':          _corregir_nombre(nombres_ok) if nombres_ok else None,
            'fecha_nacimiento_mrz': _norm(nac_raw),
            'sexo_mrz':             sexo if sexo in ('M', 'F') else None,
            'fecha_caducidad_mrz':  _norm(cad_raw),
        }
    except Exception:
        return None


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
        (l for l in lineas if "<<" in l and l != linea2
         and not re.match(r"\d{6}\d[MF<]", l)),
        None
    )
    if linea3:
        partes = linea3.split("<<", 1)
        apellidos_part = partes[0]
        nombres_part = partes[1] if len(partes) > 1 else ""

        apellidos_segs = [_corregir_nombre(s) for s in apellidos_part.split("<") if s]
        apellidos_segs = [s for s in apellidos_segs if s and not _es_etiqueta_dni(s)]
        if len(apellidos_segs) >= 2:
            resultado["apellido_paterno_mrz"] = apellidos_segs[0]
            resultado["apellido_materno_mrz"] = apellidos_segs[1]
        elif len(apellidos_segs) == 1:
            resultado["apellido_paterno_mrz"] = apellidos_segs[0]
            resultado["apellido_materno_mrz"] = None

        nombres_segs = [_corregir_nombre(s) for s in nombres_part.split("<") if s]
        nombres_segs = [s for s in nombres_segs if s and not _es_etiqueta_dni(s)]
        if nombres_segs:
            resultado["nombres_mrz"] = " ".join(nombres_segs)

    return resultado if resultado else None



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


def _agrupar_en_lineas(palabras_sorted, tol_y=20):
    """Agrupa palabras (ya ordenadas por y) en líneas según proximidad vertical."""
    if not palabras_sorted:
        return []
    lineas, grupo = [], [palabras_sorted[0]]
    for q in palabras_sorted[1:]:
        if abs(q["y"] - grupo[-1]["y"]) < tol_y:
            grupo.append(q)
        else:
            lineas.append(grupo)
            grupo = [q]
    lineas.append(grupo)
    return lineas


def _buscar_valor_abajo(palabras, etiquetas, dist_max=220, tol_x=400):
    etiquetas_up = [e.upper() for e in etiquetas]
    for p in palabras:
        if not any(e in p["texto"].upper() for e in etiquetas_up):
            continue
        candidatos = sorted(
            [q for q in palabras
             if q["y"] > p["y"]
             and (q["y"] - p["y"]) < dist_max
             and abs(q["x"] - p["x"]) < tol_x],
            key=lambda x: (x["y"], x["x"])
        )
        if not candidatos:
            continue
        # Iterar línea por línea y devolver la primera que no sea etiqueta de DNI
        for linea in _agrupar_en_lineas(candidatos):
            texto_linea = " ".join(c["texto"] for c in sorted(linea, key=lambda x: x["x"]))
            if not _es_etiqueta_dni(texto_linea):
                return texto_linea
    return None



def _parece_fecha(s):
    return bool(re.match(r"^(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])(19|20)\d{2}$", s))


def _limpiar_ocr_num(txt):
    return (txt
            .replace("O", "0").replace("o", "0").replace("Q", "0").replace("D", "0")
            .replace("l", "1").replace("I", "1").replace("|", "1").replace("!", "1")
            .replace("S", "5").replace("B", "8").replace("G", "6")
            .replace("Z", "2").replace("T", "7"))


def _extraer_numero_simple(lineas: list) -> str | None:
    texto = '\n'.join(lineas)

    m = re.search(r'\bDNI\s+(\d{8})\s*[-–]\s*\d', texto, re.IGNORECASE)
    if m and not _parece_fecha(m.group(1)):
        return m.group(1)

    m = re.search(r'\bDNI\s+(\d{8})\b', texto, re.IGNORECASE)
    if m and not _parece_fecha(m.group(1)):
        return m.group(1)

    for linea in lineas:
        m = re.search(r'\b(\d{8})\b', linea)
        if m and not _parece_fecha(m.group(1)):
            return m.group(1)

    return None


def _extraer_numero_multi_variante(imagen_bytes: bytes) -> str | None:
    """
    Prueba multiples variantes para encontrar el numero DNI:
    1. Imagen sin franja izquierda (elimina el numero vertical azul que confunde el OCR)
    2. Imagen original con distintos contrastes/brillo
    """
    variantes = [(2.0, 1.0), (1.5, 1.2), (3.0, 0.9), (1.0, 1.0)]

    # Generar version sin la franja izquierda (~13%) donde esta el numero vertical azul
    try:
        img_pil = Image.open(io.BytesIO(imagen_bytes))
        w, h = img_pil.size
        img_sin_izq = img_pil.crop((int(w * 0.13), 0, w, h))
        buf = io.BytesIO()
        img_sin_izq.save(buf, format='PNG')
        imagen_sin_izq = buf.getvalue()
    except Exception:
        imagen_sin_izq = imagen_bytes

    # Probar primero sin franja (mas fiable), luego imagen original
    for img_b in [imagen_sin_izq, imagen_bytes]:
        for contrast, brightness in variantes:
            try:
                texto = _texto_pillow_variante(img_b, contrast, brightness)
                lineas = [l.strip() for l in texto.splitlines() if l.strip()]
                resultado = _extraer_numero_simple(lineas)
                if resultado:
                    return resultado
            except Exception:
                continue
    return None


def _extraer_numero_dni_spatial(texto, palabras, zona_num_img=None):
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


def _limpiar_valor_nombre(v: str | None) -> str | None:
    """Elimina palabras-etiqueta del DNI que se cuelen en el valor extraído."""
    if not v:
        return None
    v = _corregir_nombre(v)
    if not v:
        return None
    # Quitar tokens que sean etiquetas puras (ej. "APELLIDO" que OCR incluyó en la línea)
    tokens = [p for p in v.split() if p.upper() not in _ETIQUETAS_DNI]
    return " ".join(tokens) if tokens else None


def _extraer_apellidos(texto, palabras):
    paterno, materno = None, None

    for etq in ["PRIMER", "Primer"]:
        v = _buscar_valor_abajo(palabras, [etq], dist_max=220, tol_x=400)
        v = _limpiar_valor_nombre(v)
        if v and len(v) >= 2:
            paterno = v
            break

    for etq in ["SEGUNDO", "Segundo"]:
        v = _buscar_valor_abajo(palabras, [etq], dist_max=220, tol_x=400)
        v = _limpiar_valor_nombre(v)
        if v and len(v) >= 2:
            materno = v
            break

    if not paterno:
        v = _buscar_valor_abajo(palabras, ["APELLIDOS", "APELLIDO"], dist_max=220, tol_x=400)
        v = _limpiar_valor_nombre(v)
        if v:
            partes = v.split()
            paterno = partes[0] if partes else None
            if not materno:
                materno = partes[1] if len(partes) > 1 else None

    # Regex con variantes: multilinea, con y sin dos puntos, orden alternativo
    _RE_AP1 = [
        r"PRIMER\s+APELLIDO\s*[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ ]+)",
        r"APELLIDO\s+PATERNO\s*[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ ]+)",
        r"1[Ee][Rr]\.?\s+APELLIDO\s*[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ ]+)",
    ]
    _RE_AP2 = [
        r"SEGUNDO\s+APELLIDO\s*[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ ]+)",
        r"APELLIDO\s+MATERNO\s*[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ ]+)",
        r"2[Dd][Oo]\.?\s+APELLIDO\s*[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ ]+)",
    ]
    if not paterno:
        for pat in _RE_AP1:
            m = re.search(pat, texto, re.I)
            if m:
                paterno = _limpiar_valor_nombre(m.group(1))
                if paterno:
                    break
    if not materno:
        for pat in _RE_AP2:
            m = re.search(pat, texto, re.I)
            if m:
                materno = _limpiar_valor_nombre(m.group(1))
                if materno:
                    break

    return paterno, materno


def _extraer_nombres(texto, palabras):
    v = _buscar_valor_abajo(palabras, ["NOMBRES", "NOMBRE"], dist_max=220, tol_x=400)
    v = _limpiar_valor_nombre(v)
    if v and not _es_etiqueta_dni(v):
        return v
    v = _buscar_valor_derecha(palabras, ["NOMBRES", "NOMBRE"], dist_max=700, tol_y=35)
    v = _limpiar_valor_nombre(v)
    if v and not _es_etiqueta_dni(v):
        return v
    for pat in [
        r"NOMBRES?\s*[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ ]+)",
        r"NOMBRE\s+COMPLETO\s*[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ ]+)",
    ]:
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            v = _limpiar_valor_nombre(m.group(1))
            if v:
                return v
    return None


_RE_FECHA = re.compile(r'(\d{2})[\s\/\-\.](\d{2})[\s\/\-\.](\d{4})')


def _normalizar_fecha(txt) -> str | None:
    if not txt:
        return None
    # Corregir sustituciones OCR comunes en dígitos: O→0, I/l/|→1
    txt_fix = (str(txt)
               .replace('O', '0').replace('o', '0')
               .replace('I', '1').replace('l', '1').replace('|', '1'))
    m = _RE_FECHA.search(txt_fix)
    if m:
        d, mo, a = m.group(1), m.group(2), m.group(3)
        # Validación básica de rango para descartar fechas imposibles
        if 1 <= int(d) <= 31 and 1 <= int(mo) <= 12 and 1900 <= int(a) <= 2100:
            return f"{d}/{mo}/{a}"
    return None


def _extraer_fecha_nacimiento(texto, palabras):
    for fn, kw in [
        (_buscar_valor_derecha, {"dist_max": 700, "tol_y": 35}),
        (_buscar_valor_abajo,   {"dist_max": 220, "tol_x": 400}),
    ]:
        v = fn(palabras, ["NACIMIENTO", "F.NAC"], **kw)
        if v and _normalizar_fecha(v):
            return _normalizar_fecha(v)
    m = re.search(
        r"(?:FECHA\s+DE\s+NACIMIENTO|NACIMIENTO)\s*[:\-]?\s*"
        r"(\d{2}[\s\/\-\.]\d{2}[\s\/\-\.]\d{4})",
        texto, re.IGNORECASE
    )
    return _normalizar_fecha(m.group(1)) if m else None


def _extraer_fecha_emision(texto, palabras):
    for fn, kw in [
        (_buscar_valor_derecha, {"dist_max": 700, "tol_y": 35}),
        (_buscar_valor_abajo,   {"dist_max": 220, "tol_x": 400}),
    ]:
        v = fn(palabras, ["EMISION", "EMISIÓN", "EMISI"], **kw)
        if v and _normalizar_fecha(v):
            return _normalizar_fecha(v)
    m = re.search(
        r"(?:FECHA\s+DE\s+EMISI[OÓ]N|EMISI[OÓ]N)\s*[:\-]?\s*"
        r"(\d{2}[\s\/\-\.]\d{2}[\s\/\-\.]\d{4})",
        texto, re.IGNORECASE
    )
    return _normalizar_fecha(m.group(1)) if m else None


def _extraer_fecha_caducidad(texto, palabras):
    for fn, kw in [
        (_buscar_valor_derecha, {"dist_max": 700, "tol_y": 35}),
        (_buscar_valor_abajo,   {"dist_max": 220, "tol_x": 400}),
    ]:
        v = fn(palabras, ["VENCIMIENTO", "CADUCIDAD", "VENC", "CADUC"], **kw)
        if v and _normalizar_fecha(v):
            return _normalizar_fecha(v)
    m = re.search(
        r"(?:FECHA\s+DE\s+(?:VENCIMIENTO|CADUCIDAD)|VENCIMIENTO|CADUCIDAD)\s*[:\-]?\s*"
        r"(\d{2}[\s\/\-\.]\d{2}[\s\/\-\.]\d{4})",
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
    for etiquetas in [["EST.CIVIL", "ESTADO CIVIL"], ["CIVIL"]]:
        v = _buscar_valor_derecha(palabras, etiquetas)
        if v:
            corrected = _corregir_nombre(v.strip())
            if corrected and not _es_etiqueta_dni(corrected):
                return corrected
    m = re.search(r"(?:EST\.?\s*CIVIL|ESTADO\s+CIVIL)\s*[:\-]?\s*(\w+)", texto, re.IGNORECASE)
    return _corregir_nombre(m.group(1)) if m else None


def _extraer_ubigeo(texto, palabras):
    for fn, kw in [
        (_buscar_valor_derecha, {"dist_max": 700, "tol_y": 35}),
        (_buscar_valor_abajo,   {"dist_max": 220, "tol_x": 400}),
    ]:
        v = fn(palabras, ["UBIGEO", "UBIG"], **kw)
        if v:
            m = re.search(r"\d{6}", v)
            if m:
                return m.group()

    m = re.search(r"\bUBIGEO\s*[:\-]?\s*(\d{6})\b", texto, re.IGNORECASE)
    if m:
        return m.group(1)

    # Patron: fecha de nacimiento seguida del ubigeo en la misma linea
    m = re.search(r"\d{2}[\s\/\-\.]\d{2}[\s\/\-\.]\d{4}\s{1,10}(\d{6})\b", texto)
    if m:
        return m.group(1)

    return None


def _palabras_desde_easyocr(resultados) -> list:
    """Convierte output de EasyOCR al formato interno de palabras con bounding boxes."""
    palabras = []
    for bbox, texto, conf in resultados:
        if not texto.strip() or conf < 0.25:
            continue
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        palabras.append({
            "texto": texto.strip(),
            "x":     int(min(xs)),
            "y":     int(min(ys)),
            "w":     int(max(xs) - min(xs)),
            "h":     int(max(ys) - min(ys)),
            "conf":  conf * 100,
        })
    return palabras


def _palabras_desde_paddleocr(resultados) -> list:
    """Convierte output de PaddleOCR (v2 o v3/paddlex) al formato interno."""
    palabras = []
    if not resultados:
        return palabras

    # PaddleOCR v3 (paddlex): [{'res': [{'dt_polys':..., 'rec_text':..., 'rec_score':...}]}]
    if (isinstance(resultados, list) and resultados
            and isinstance(resultados[0], dict) and 'res' in resultados[0]):
        for page in resultados:
            for item in page.get('res', []):
                texto = item.get('rec_text', '').strip()
                conf  = float(item.get('rec_score', 0.0))
                bbox  = item.get('dt_polys', item.get('text_region', []))
                if not texto or conf < 0.25 or not bbox:
                    continue
                try:
                    xs = [p[0] for p in bbox]
                    ys = [p[1] for p in bbox]
                    palabras.append({
                        "texto": texto,
                        "x":     int(min(xs)),
                        "y":     int(min(ys)),
                        "w":     int(max(xs) - min(xs)),
                        "h":     int(max(ys) - min(ys)),
                        "conf":  conf * 100,
                    })
                except (TypeError, IndexError):
                    continue
        return palabras

    # PaddleOCR v2: [[[bbox, (text, conf)], ...]]
    for pagina in resultados:
        if not pagina:
            continue
        for item in pagina:
            try:
                bbox, (texto, conf) = item
            except (TypeError, ValueError):
                continue
            if not texto.strip() or conf < 0.25:
                continue
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            palabras.append({
                "texto": texto.strip(),
                "x":     int(min(xs)),
                "y":     int(min(ys)),
                "w":     int(max(xs) - min(xs)),
                "h":     int(max(ys) - min(ys)),
                "conf":  conf * 100,
            })
    return palabras


def _es_nombre_valido(texto: str) -> bool:
    """Valida que un string parezca un nombre real en español.
    Rechaza ruido OCR: strings sin vocales, rachas de consonantes, tokens muy cortos."""
    if not texto or len(texto.strip()) < 2:
        return False
    tokens = texto.strip().split()
    if not tokens or len(tokens) > 6:
        return False
    for t in tokens:
        if len(t) < 2:
            return False
        t_up = t.upper()
        # Debe tener al menos una vocal
        if not re.search(r'[AEIOUÁÉÍÓÚÜ]', t_up):
            return False
        # No más de 3 consonantes seguidas (SCCS, KTQR = ruido OCR)
        if re.search(r'[BCDFGHJKLMNPQRSTVWXYZ]{4,}', t_up):
            return False
        # No puede ser solo dígitos ni mezcla rara de dígitos+letras
        if re.search(r'\d', t):
            return False
    return True


# Mapa ordenado de campos → patrones de etiqueta para el parser secuencial
_CAMPOS_LABELS = [
    ('apellido_paterno', [
        r'PRIMER\s+APELLIDO', r'APELLIDO\s+PATERNO', r'1[Ee][Rr]\.?\s*APELLIDO',
    ]),
    ('apellido_materno', [
        r'SEGUNDO\s+APELLIDO', r'APELLIDO\s+MATERNO', r'2[Dd][Oo]\.?\s*APELLIDO',
    ]),
    ('nombres', [r'NOMBRES?\b', r'NOMBRE\s+COMPLETO']),
    ('fecha_nacimiento', [
        r'FECHA\s+(?:DE\s+)?NACIMIENTO', r'F\.?\s*NAC\.?', r'NACIMIENTO',
    ]),
    ('sexo', [r'\bSEXO\b']),
    ('estado_civil', [r'ESTADO\s+CIVIL', r'EST\.?\s*CIVIL']),
    ('ubigeo', [r'\bUBIGEO\b', r'\bUBIG\b']),
    ('fecha_emision', [
        r'FECHA\s+(?:DE\s+)?EMISI[OÓ]N', r'EMISI[OÓ]N', r'F\.?\s*EMIS',
    ]),
    ('fecha_caducidad', [
        r'FECHA\s+(?:DE\s+)?(?:VENCIMIENTO|CADUCIDAD)',
        r'VENCIMIENTO', r'CADUCIDAD', r'F\.?\s*VENC',
    ]),
    ('codigo_verificador', [r'C[OÓ]D(?:\.?\s+VERIF|IFICADOR)', r'DIGITO\s+VERIF']),
]

# Etiquetas a saltar cuando se busca el valor en líneas siguientes
_RE_CUALQUIER_ETIQUETA = re.compile(
    '|'.join(p for _, pats in _CAMPOS_LABELS for p in pats),
    re.IGNORECASE,
)


def _parsear_texto_linea_a_linea(texto: str) -> dict:
    """Parser secuencial: la línea que sigue a una etiqueta conocida contiene su valor.
    Estrategia más fiable que regex libre para documentos estructurados como el DNI."""
    campos: dict = {}
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]

    for i, linea in enumerate(lineas):
        linea_up = linea.upper()
        for campo, patrones in _CAMPOS_LABELS:
            if campo in campos:
                continue
            if not any(re.search(p, linea_up) for p in patrones):
                continue
            # Leer hasta 4 líneas adelante buscando el primer valor válido
            for j in range(i + 1, min(i + 5, len(lineas))):
                candidato = lineas[j].strip()
                # Saltar si el candidato es otra etiqueta
                if _RE_CUALQUIER_ETIQUETA.search(candidato.upper()):
                    continue
                # Procesar según tipo de campo
                if campo in ('apellido_paterno', 'apellido_materno', 'nombres'):
                    v = _limpiar_valor_nombre(candidato)
                    if v and _es_nombre_valido(v):
                        campos[campo] = v
                elif 'fecha' in campo:
                    v = _normalizar_fecha(candidato)
                    if v:
                        campos[campo] = v
                    # Si no hay fecha en esta línea, buscar patrón de fecha en la misma
                    elif re.search(r'\d{2}[/\-\.]\d{2}[/\-\.]\d{4}', candidato):
                        m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', candidato)
                        if m:
                            campos[campo] = _normalizar_fecha(m.group(1))
                    if campo not in campos:
                        continue  # Sigue buscando en líneas siguientes
                elif campo == 'sexo':
                    if re.search(r'\bMASCULINO\b|\bM\b', candidato.upper()):
                        campos[campo] = 'M'
                    elif re.search(r'\bFEMENINO\b|\bF\b', candidato.upper()):
                        campos[campo] = 'F'
                elif campo == 'ubigeo':
                    # Corregir O→0, I→1 antes de buscar el código de 6 dígitos
                    cand_num = (candidato.replace('O', '0').replace('o', '0')
                                .replace('I', '1').replace('l', '1').replace('|', '1'))
                    m = re.search(r'\b(\d{6})\b', cand_num)
                    if m:
                        campos[campo] = m.group(1)
                elif campo == 'estado_civil':
                    v = _limpiar_valor_nombre(candidato)
                    if v and not _es_etiqueta_dni(v):
                        campos[campo] = v
                elif campo == 'codigo_verificador':
                    cand_num = (candidato.replace('O', '0').replace('o', '0')
                                .replace('I', '1').replace('l', '1'))
                    m = re.search(r'\b(\d{1,3})\b', cand_num)
                    if m:
                        campos[campo] = m.group(1)
                if campo in campos:
                    break
    return campos


def _campos_vacios() -> dict:
    return {k: None for k in (
        'numero_dni', 'codigo_verificador', 'apellido_paterno', 'apellido_materno',
        'nombres', 'fecha_nacimiento', 'sexo', 'estado_civil',
        'ubigeo', 'fecha_emision', 'fecha_caducidad',
    )}


def _extraer_campos_dni(palabras: list, mrz: dict | None, numero_pillow: str | None,
                        texto_extra: str = '') -> dict:
    """Extrae campos del DNI con tres fuentes de extracción en cascada:
    1. Parser secuencial sobre texto_extra (Pillow) — más fiable para DNI estructurado
    2. Búsqueda espacial con bounding boxes — complementa con coordenadas
    3. MRZ — fallback definitivo para fechas y nombres
    """
    texto_bboxes = _texto_completo(palabras) if palabras else ''
    texto_para_regex = '\n'.join(filter(None, [texto_bboxes, texto_extra]))

    if not palabras and not texto_para_regex:
        c = _campos_vacios()
        c['numero_dni'] = numero_pillow
        return c

    # ── 1. Parser secuencial: combinar resultados de Pillow + texto bboxes ──
    seq_pillow = _parsear_texto_linea_a_linea(texto_extra) if texto_extra else {}
    seq_bboxes = _parsear_texto_linea_a_linea(texto_bboxes) if texto_bboxes else {}
    # Pillow tiene prioridad; bboxes llena los huecos
    seq = {**seq_bboxes, **seq_pillow}

    # ── 2. Número DNI (Pillow es más fiable, ya viene como número_pillow) ──
    lineas = [l.strip() for l in texto_para_regex.splitlines() if l.strip()]
    numero_dni = numero_pillow
    if not numero_dni:
        numero_dni = _extraer_numero_simple(lineas)
    if not numero_dni:
        numero_dni = _extraer_numero_dni_spatial(texto_bboxes, palabras, None)

    # ── 3. Nombres y apellidos: secuencial primero, espacial como refuerzo ──
    apellido_paterno = seq.get('apellido_paterno')
    apellido_materno = seq.get('apellido_materno')
    nombres          = seq.get('nombres')

    if not apellido_paterno or not apellido_materno:
        ap_sp, am_sp = _extraer_apellidos(texto_para_regex, palabras)
        if not apellido_paterno and ap_sp and _es_nombre_valido(ap_sp):
            apellido_paterno = ap_sp
        if not apellido_materno and am_sp and _es_nombre_valido(am_sp):
            apellido_materno = am_sp

    if not nombres:
        nombres_sp = _extraer_nombres(texto_para_regex, palabras)
        if nombres_sp and _es_nombre_valido(nombres_sp):
            nombres = nombres_sp

    # ── 4. MRZ como fallback de última instancia ─────────────────────────────
    if mrz:
        ap_mrz = mrz.get('apellido_paterno_mrz')
        am_mrz = mrz.get('apellido_materno_mrz')
        n_mrz  = mrz.get('nombres_mrz')
        if not apellido_paterno and _nombre_mrz_valido(ap_mrz):
            apellido_paterno = ap_mrz
        if not apellido_materno and _nombre_mrz_valido(am_mrz):
            apellido_materno = am_mrz
        if not nombres and _nombre_mrz_valido(n_mrz):
            nombres = n_mrz

    # ── 5. Fechas y campos adicionales ───────────────────────────────────────
    fecha_nac    = seq.get('fecha_nacimiento') or _extraer_fecha_nacimiento(texto_para_regex, palabras)
    sexo         = seq.get('sexo')             or _extraer_sexo(texto_para_regex, palabras)
    fecha_cad    = seq.get('fecha_caducidad')  or _extraer_fecha_caducidad(texto_para_regex, palabras)
    estado_civil = seq.get('estado_civil')     or _extraer_estado_civil(texto_para_regex, palabras)
    ubigeo       = seq.get('ubigeo')           or _extraer_ubigeo(texto_para_regex, palabras)
    fecha_emis   = seq.get('fecha_emision')    or _extraer_fecha_emision(texto_para_regex, palabras)
    cod_verif    = seq.get('codigo_verificador') or _extraer_codigo_verificador(texto_para_regex, palabras)

    if mrz:
        if not fecha_nac: fecha_nac = mrz.get('fecha_nacimiento_mrz')
        if not sexo:      sexo      = mrz.get('sexo_mrz')
        if not fecha_cad: fecha_cad = mrz.get('fecha_caducidad_mrz')

    return {
        'numero_dni':         numero_dni,
        'codigo_verificador': cod_verif,
        'apellido_paterno':   apellido_paterno,
        'apellido_materno':   apellido_materno,
        'nombres':            nombres,
        'fecha_nacimiento':   fecha_nac,
        'sexo':               sexo,
        'estado_civil':       estado_civil,
        'ubigeo':             ubigeo,
        'fecha_emision':      fecha_emis,
        'fecha_caducidad':    fecha_cad,
    }


def _campos_engine_easyocr(img_sin_azul, mrz, numero_pillow, texto_pillow='') -> dict:
    reader = _get_easyocr()
    if not reader:
        return _campos_vacios()
    try:
        resultados = reader.readtext(img_sin_azul)
        palabras = _palabras_desde_easyocr(resultados)
        return _extraer_campos_dni(palabras, mrz, numero_pillow, texto_extra=texto_pillow)
    except Exception:
        return _campos_vacios()


def _campos_engine_paddleocr(img_sin_azul, mrz, numero_pillow, texto_pillow='') -> dict:
    ocr_inst = _get_paddleocr()
    if not ocr_inst:
        c = _campos_vacios()
        c['_engine_error'] = 'PaddleOCR no disponible en este sistema'
        return c
    try:
        try:
            resultados = ocr_inst.predict(img_sin_azul)
        except AttributeError:
            resultados = ocr_inst.ocr(img_sin_azul)
        palabras = _palabras_desde_paddleocr(resultados)
        return _extraer_campos_dni(palabras, mrz, numero_pillow, texto_extra=texto_pillow)
    except Exception as e:
        c = _campos_vacios()
        c['_engine_error'] = str(e)[:120]
        return c


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


def _aplicar_reniec(campos: dict, reniec: dict) -> None:
    if reniec.get('apellidoPaterno'):
        campos['apellido_paterno'] = reniec['apellidoPaterno']
    if reniec.get('apellidoMaterno'):
        campos['apellido_materno'] = reniec['apellidoMaterno']
    if reniec.get('nombres'):
        campos['nombres'] = reniec['nombres']
    if not campos.get('codigo_verificador') and reniec.get('digitoVerificador') is not None:
        campos['codigo_verificador'] = str(reniec['digitoVerificador'])


def _procesar_dni(imagen_bytes: bytes) -> dict:
    img_color = _bytes_a_bgr(imagen_bytes)
    try:
        img_color = _rotar_si_necesario(img_color)
        img_color = _corregir_perspectiva(img_color)
    except Exception:
        img_color = _bytes_a_bgr(imagen_bytes)
    img_color = _escalar(img_color)

    # Franja azul eliminada antes del OCR espacial
    img_sin_azul = _eliminar_franja_azul(img_color)

    # Encabezado naranja/rojo enmascarado (REPÚBLICA DEL PERÚ / RENIEC)
    # — evita que el header contamine el texto OCR de los campos de datos
    img_limpia = _eliminar_encabezado_naranja(img_sin_azul)

    # Zona recortada: solo los campos de datos (sin foto, franja azul, header ni MRZ)
    img_zona = _zona_texto_campos(img_limpia)

    # Número DNI vía Pillow — no cambiar, funciona bien
    numero_pillow = _extraer_numero_multi_variante(imagen_bytes)

    # Texto Pillow sobre la zona de campos (menos ruido de foto/header)
    texto_zona = _texto_pillow_mejor(_img_bgr_a_bytes(img_zona))
    # Texto Pillow sobre imagen completa como refuerzo (captura header, MRZ, etc.)
    texto_full = _texto_pillow_mejor(imagen_bytes)
    # Combinar: zona primero (más limpia), imagen completa como complemento
    texto_pillow = '\n'.join(filter(None, [texto_zona, texto_full]))

    # MRZ compartido (fastmrz ONNX primero, luego parser propio)
    mrz = _parsear_mrz_fastmrz(imagen_bytes)
    if not mrz:
        img_mrz_n, img_mrz_i = _zona_mrz(img_color)
        texto_mrz = _ocr_mrz_zona(img_mrz_n, img_mrz_i)
        if _score_mrz(texto_mrz) < 10:
            texto_mrz = _mrz_desde_texto_general(texto_pillow) or texto_mrz
        mrz = _parsear_mrz(texto_mrz)

    # Motor 1 — Tesseract (sobre imagen limpia sin encabezado naranja)
    img_bin = _preprocesar_zona(img_limpia)
    img_bin = _deskew(img_bin)
    datos_ocr = _obtener_datos_ocr(img_bin)
    palabras_tess = _construir_palabras(datos_ocr)

    # Si Pillow no encontró el número, intentar con zona recortada
    if not numero_pillow:
        img_zona_num = _zona_numero_dni(img_color)
        texto_esp = _texto_completo(palabras_tess)
        numero_pillow = _extraer_numero_dni_spatial(texto_esp, palabras_tess, img_zona_num)
        if not numero_pillow and mrz:
            numero_pillow = mrz.get('numero_dni_mrz')

    campos_tess   = _extraer_campos_dni(palabras_tess, mrz, numero_pillow, texto_extra=texto_pillow)

    # Motor 2 — EasyOCR sobre zona de campos (menos ruido que imagen completa)
    campos_easy   = _campos_engine_easyocr(img_zona, mrz, numero_pillow, texto_pillow)

    # Motor 3 — PaddleOCR
    campos_paddle = _campos_engine_paddleocr(img_zona, mrz, numero_pillow, texto_pillow)

    # RENIEC: usa el primer número válido que encuentre algún motor
    numero_final = (campos_tess.get('numero_dni')
                    or campos_easy.get('numero_dni')
                    or campos_paddle.get('numero_dni'))
    reniec_data = None
    if numero_final and len(numero_final) == 8 and numero_final.isdigit():
        reniec_data = _consultar_reniec(numero_final)

    return {
        'tipo_documento': 'DNI',
        'tesseract':  campos_tess,
        'easyocr':    campos_easy,
        'paddleocr':  campos_paddle,
        'reniec':     reniec_data,
        'texto_raw':  texto_pillow,
    }


def _procesar_carnet(imagen_bytes: bytes) -> dict:
    img = Image.open(io.BytesIO(imagen_bytes)).convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    w, h = img.size
    if w < 800:
        img = img.resize((int(w * 800 / w), int(h * 800 / w)), Image.LANCZOS)

    texto = pytesseract.image_to_string(img, config='--oem 3 --psm 6 -l spa+eng')
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]

    numero_carnet = None
    for linea in lineas:
        m = re.search(r'\b([A-Z]{0,3}\d{6,9})\b', linea)
        if m:
            numero_carnet = m.group(1)
            break

    fecha_nacimiento = None
    for linea in lineas:
        f = _normalizar_fecha(linea)
        if f:
            fecha_nacimiento = f
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
            'numero_carnet':    numero_carnet,
            'apellidos':        apellidos,
            'nombre':           nombre,
            'nacionalidad':     nacionalidad,
            'fecha_nacimiento': fecha_nacimiento,
            'sexo':             sexo,
        },
        'reniec': None,
        'texto_raw': texto,
    }


def detectar(imagen_bytes: bytes, tipo_documento: str) -> dict:
    if not OCR_DISPONIBLE:
        raise RuntimeError(
            'Faltan dependencias'
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
            'Verifica que Tesseract este instalado correctamente.'
        ) from exc

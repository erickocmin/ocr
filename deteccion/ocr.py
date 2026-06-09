import io
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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


if OCR_DISPONIBLE:
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    # pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"

_TESSDATA_BEST: str | None = None
_OEM_OPTIMO: str = '3'

if OCR_DISPONIBLE:
    _tes_dir = os.path.dirname(pytesseract.pytesseract.tesseract_cmd)
    _candidatos_best = [
        os.path.join(_tes_dir, 'tessdata_best'),
        os.path.join(_tes_dir, 'tessdata', 'best'),
        r'C:\Program Files\Tesseract-OCR\tessdata_best',
        r'C:\Program Files\Tesseract-OCR\tessdata\best',
    ]
    for _cand in _candidatos_best:
        if (os.path.isdir(_cand)
                and os.path.exists(os.path.join(_cand, 'spa.traineddata'))
                and os.path.exists(os.path.join(_cand, 'eng.traineddata'))):
            _TESSDATA_BEST = _cand
            _OEM_OPTIMO = '1'
            os.environ['TESSDATA_PREFIX'] = _cand
            break


def _tess_config(psm: str, lang: str = 'spa+eng', whitelist: str = '') -> str:
    partes = [f'--oem {_OEM_OPTIMO}', f'--psm {psm}', f'-l {lang}']
    if whitelist:
        partes.append(f'-c tessedit_char_whitelist={whitelist}')
    return ' '.join(partes)

_easy_ocr_reader = None
_doctr_model     = None
_doctr_error     = None
_doctr_lock      = threading.Lock()

_OCR_MAX_WORKERS = max(1, int(os.getenv('OCR_MAX_WORKERS', str(min(4, os.cpu_count() or 2)))))
_OCR_CONCURRENT_REQUESTS = max(1, int(os.getenv('OCR_CONCURRENT_REQUESTS', '2')))
_OCR_REQUEST_SEMAPHORE = threading.BoundedSemaphore(_OCR_CONCURRENT_REQUESTS)
_DOCTR_DET_ARCH = os.getenv('OCR_DOCTR_DET_ARCH', 'db_mobilenet_v3_large')
_DOCTR_RECO_ARCH = os.getenv('OCR_DOCTR_RECO_ARCH', 'crnn_mobilenet_v3_small')


def _detectar_gpu() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except ImportError:
        return False


def _get_easyocr():
    global _easy_ocr_reader
    if _easy_ocr_reader is None:
        try:
            import easyocr
            gpu = _detectar_gpu()
            _easy_ocr_reader = easyocr.Reader(['es', 'en'], gpu=gpu, verbose=False)
        except Exception:
            pass
    return _easy_ocr_reader


def _get_doctr():
    """Carga doctr OCR predictor (detection + recognition). Lazy, thread-safe por GIL."""
    global _doctr_model, _doctr_error
    if _doctr_model is None:
        with _doctr_lock:
            if _doctr_model is not None:
                return _doctr_model
            return _load_doctr()
    return _doctr_model


def _load_doctr():
    global _doctr_model, _doctr_error
    try:
        try:
            import torch  # noqa: PLC0415
            torch.set_num_threads(max(1, int(os.getenv('OCR_TORCH_THREADS', '2'))))
        except Exception:
            pass
        from doctr.models import ocr_predictor  # noqa: PLC0415
        _doctr_model = ocr_predictor(
            det_arch=_DOCTR_DET_ARCH,
            reco_arch=_DOCTR_RECO_ARCH,
            pretrained=True,
            assume_straight_pages=True,
        )
        _doctr_error = None
    except Exception as exc:
        _doctr_error = str(exc)[:240]
    return _doctr_model

_RENIEC_TOKEN = os.getenv('RENIEC_TOKEN', 'apis-token-16099.nd0kCbthWLqfHqL04GbpyY3e8OE83L5G')
_RENIEC_URL = 'https://api.apis.net.pe/v2/reniec/dni'

_ETIQUETAS_DNI = {
    "PRIMER", "SEGUNDO", "APELLIDO", "APELLIDOS", "NOMBRES", "NOMBRE",
    "SEXO", "CIVIL", "UBIGEO", "NACIMIENTO", "EMISION", "CADUCIDAD",
    "FECHA", "ESTADO", "LUGAR", "DNI", "PERU", "PER", "PRE",
    "INSCRIPCION", "INSCRIPCIÓN", "IDENTIDAD", "NACIONAL", "REGISTRO",
    "GRUPO", "VOTACION", "VOTACIÓN", "DONACION", "DONACIÓN", "ORGANOS", "ÓRGANOS",
    "PRENOMBRE", "PRENOMBRES",
    # Variantes OCR comunes
    "APEILIDO", "APELIIDO", "APELL1DO", "APELLIDO", "APELIIDOS",
    "PRENOMBROS", "PRENOMBRS", "PRENOMRES",
    "N0MBRES", "NORNBRES", "NOMRES",
    "UBIG", "UBIGEC", "UB1GEO",
    "EM1SION", "EMISI0N", "CADUClDAD",
    "V0TACION", "D0NACION",
}

_RE_ETIQUETA_OCR = re.compile(
    r'\b(?:'
    r'AP[EI][LI][LI][IU1]D[OA0]S?'
    r'|PRENOMBR[EO0]S?'
    r'|N[O0]MBRES?'
    r'|PR[EI]M[EI]R'
    r'|S[EI]GUND[OA0]'
    r')\b',
    re.IGNORECASE,
)

_DIGIT_A_LETRA = str.maketrans("015348672", "OISAEBGZA")

_PESOS_DV_RENIEC    = [3, 2, 7, 6, 5, 4, 3, 2]
_TABLA_DV_NUMERICO  = [6, 7, 8, 9, 0, 1, 1, 2, 3, 4, 5]   # índices 0-10
_TABLA_DV_ALFABETICO = ['K', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']


def _calcular_digito_verificador(numero_8: str) -> dict | None:
    if not (numero_8 and len(numero_8) == 8 and numero_8.isdigit()):
        return None
    suma = sum(int(d) * p for d, p in zip(numero_8, _PESOS_DV_RENIEC))
    idx = suma % 11
    return {
        'numerico':   str(_TABLA_DV_NUMERICO[idx]),
        'alfabetico': _TABLA_DV_ALFABETICO[idx],
    }


def _validar_digito_verificador(numero_8: str, digito: str) -> bool:
    res = _calcular_digito_verificador(numero_8)
    if not res:
        return False
    dv = str(digito).upper().strip()
    return dv == res['numerico'] or dv == res['alfabetico']


def _icao_check_digit(campo: str) -> int:
    pesos = [7, 3, 1]
    def _val(c):
        if c == '<':  return 0
        if c.isdigit(): return int(c)
        return ord(c.upper()) - ord('A') + 10
    return sum(_val(c) * pesos[i % 3] for i, c in enumerate(campo)) % 10


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


def _escalar(img, min_ancho=1800, max_ancho=2400):
    h, w = img.shape[:2]
    if w < min_ancho:
        factor = min_ancho / w
        img = cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_LANCZOS4)
    elif w > max_ancho:
        factor = max_ancho / w
        img = cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
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
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    mask_azul = cv2.inRange(hsv, np.array([95, 50, 30]), np.array([135, 255, 255]))
    # Dilatar para cubrir bordes antialiased de la franja
    kernel = np.ones((7, 7), np.uint8)
    mask_azul = cv2.dilate(mask_azul, kernel, iterations=1)
    resultado = img_bgr.copy()
    resultado[mask_azul > 0] = [255, 255, 255]
    return resultado


def _eliminar_encabezado_naranja(img_bgr):
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


def _remover_reflejo_hsv(img_bgr):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)
    _, mask_v = cv2.threshold(v, 220, 255, cv2.THRESH_BINARY)
    _, mask_s = cv2.threshold(s, 30,  255, cv2.THRESH_BINARY_INV)
    mask_glare = cv2.bitwise_and(mask_v, mask_s)
    pixeles_glare = int(np.count_nonzero(mask_glare))
    total = img_bgr.shape[0] * img_bgr.shape[1]
    if not (total * 0.003 < pixeles_glare < total * 0.40):
        return img_bgr
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_glare = cv2.erode(mask_glare, kernel, iterations=1)
    mask_glare = cv2.dilate(mask_glare, kernel, iterations=2)
    try:
        return cv2.inpaint(img_bgr, mask_glare, 5, cv2.INPAINT_TELEA)
    except Exception:
        return img_bgr


def _corregir_sombra(img_bgr):
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l_ch = lab[:, :, 0].astype(np.float32)
    sigma = max(img_bgr.shape[1] // 20, 15)
    sigma = sigma if sigma % 2 == 1 else sigma + 1  # ksize impar
    fondo = cv2.GaussianBlur(l_ch, (0, 0), sigmaX=sigma)
    fondo = np.clip(fondo, 30, 255)
    l_norm = np.clip(l_ch / fondo * 130, 0, 255).astype(np.uint8)
    lab[:, :, 0] = l_norm
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _zona_texto_campos(img_bgr):
    h, w = img_bgr.shape[:2]
    return img_bgr[int(h * 0.13):int(h * 0.80), int(w * 0.13):int(w * 0.68)]


def _img_bgr_a_bytes(img_bgr) -> bytes:
    _, buf = cv2.imencode('.png', img_bgr)
    return buf.tobytes()


def _preprocesar_zona(img_bgr):
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    gray = lab[:, :, 0]
    mean_l = float(gray.mean())
    if mean_l < 80:
        gamma = 0.55
    elif mean_l > 200:
        gamma = 1.6
    else:
        gamma = 1.0
    if gamma != 1.0:
        lut = np.array(
            [min(255, int((i / 255.0) ** gamma * 255)) for i in range(256)],
            dtype=np.uint8,
        )
        gray = cv2.LUT(gray, lut)

    gray = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)

    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    blur = cv2.GaussianBlur(gray, (0, 0), 1.5)
    gray = cv2.addWeighted(gray, 1.8, blur, -0.8, 0)

    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adapt = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 25, 8)
    combined = cv2.bitwise_or(otsu, adapt)
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
    return pytesseract.image_to_string(img, config=_tess_config('6'))

_LABEL_SCORE_PATS = [
    r'PRIMER\s+APELLIDO', r'SEGUNDO\s+APELLIDO', r'APELLIDO\s+PATERNO',
    r'APELLIDO\s+MATERNO', r'NOMBRES?', r'FECHA\s+DE\s+NACIMIENTO',
    r'SEXO', r'ESTADO\s+CIVIL', r'UBIGEO', r'EMISI[OÓ]N',
    r'VENCIMIENTO', r'CADUCIDAD', r'DNI\s+\d{8}',
]


def _texto_pillow_mejor(imagen_bytes: bytes) -> str:
    variantes = [
        (_tess_config('6'), 2.0, 1.0),
        (_tess_config('4'), 1.8, 1.0),
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
                if score >= 3:
                    break
        except Exception:
            continue
    return mejor_texto


def _recortar(img_bgr, x1r, y1r, x2r, y2r):
    h, w = img_bgr.shape[:2]
    return img_bgr[int(h * y1r):int(h * y2r), int(w * x1r):int(w * x2r)]


def _zona_numero_dni(img_bgr):
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
                    config=_tess_config(psm, lang=lang),
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
                config=_tess_config(psm, lang='eng', whitelist='0123456789'),
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
                    config=_tess_config(psm, lang='eng', whitelist=wl),
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
    palabras = texto.upper().split()
    return all(
        p in _ETIQUETAS_DNI or bool(_RE_ETIQUETA_OCR.fullmatch(p))
        for p in palabras
    )


def _nombre_mrz_valido(texto) -> bool:
    if not texto or len(texto) < 2:
        return False
    if re.search(r'\d', texto):
        return False
    return bool(re.search(r'[A-ZÁÉÍÓÚÜÑ]', texto))


def _parsear_mrz_fastmrz(imagen_bytes: bytes) -> dict | None:
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

        doc_num  = str(res.get('document_number') or '').replace('<', '').strip()
        apellido = str(res.get('surname')         or '').replace('<', ' ').strip()
        nombres  = str(res.get('given_name')      or '').replace('<', ' ').strip()
        nac_raw  = str(res.get('birth_date')      or '')
        cad_raw  = str(res.get('expiry_date')     or '')
        sexo     = str(res.get('sex')             or '')

        partes_ap  = [p for p in apellido.split() if p and not _es_etiqueta_dni(p)]
        nombres_ok = ' '.join(n for n in nombres.split() if n and not _es_etiqueta_dni(n))

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
            num_cand = m.group(1)
            if len(linea1) >= 15:
                num_field = linea1[5:14]
                cd_char   = linea1[14]
                if cd_char.isdigit() and _icao_check_digit(num_field) == int(cd_char):
                    resultado["numero_dni_mrz"] = num_cand
                elif not cd_char.isdigit():
                    resultado["numero_dni_mrz"] = num_cand
            else:
                resultado["numero_dni_mrz"] = num_cand

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
    variantes = [(2.0, 1.0), (1.5, 1.1)]

    try:
        img_pil = Image.open(io.BytesIO(imagen_bytes))
        w, h = img_pil.size
        img_sin_izq = img_pil.crop((int(w * 0.13), 0, w, h))
        buf = io.BytesIO()
        img_sin_izq.save(buf, format='PNG')
        imagen_sin_izq = buf.getvalue()
    except Exception:
        imagen_sin_izq = imagen_bytes

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
    if not v:
        return None
    v = _corregir_nombre(v)
    if not v:
        return None
    tokens = [
        p for p in v.split()
        if p.upper() not in _ETIQUETAS_DNI
        and not _RE_ETIQUETA_OCR.fullmatch(p.upper())
    ]
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
_RE_NO_CADUCA = re.compile(
    r'NO\s+CAD[UC]|NO\s+VENCE|PERMANENTE|INDEFINID|SIN\s+VENC|NO\s+EXPIR',
    re.IGNORECASE,
)


def _normalizar_fecha(txt) -> str | None:
    if not txt:
        return None
    if _RE_NO_CADUCA.search(str(txt)):
        return 'NO CADUCA'
    txt_fix = (str(txt)
               .replace('O', '0').replace('o', '0')
               .replace('I', '1').replace('l', '1').replace('|', '1'))
    m = _RE_FECHA.search(txt_fix)
    if m:
        d, mo, a = m.group(1), m.group(2), m.group(3)
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


def _normalizar_sexo(v: str | None) -> str | None:
    if not v:
        return None
    u = v.upper()
    if re.search(r'\bMASCULINO\b|\bMASC\b|\bM\b', u):
        return 'M'
    if re.search(r'\bFEMENINO\b|\bFEM\b|\bF\b', u):
        return 'F'
    return None


def _extraer_sexo(texto, palabras):
    v = _buscar_valor_derecha(palabras, ["SEXO"])
    if v:
        resultado = _normalizar_sexo(v)
        if resultado:
            return resultado
    m = re.search(r"SEXO\s*[:\-]?\s*(M|F|MASCULINO|FEMENINO)", texto, re.IGNORECASE)
    if m:
        return _normalizar_sexo(m.group(1))
    return None


def _extraer_estado_civil(texto, palabras):
    for etiquetas in [["EST.CIVIL", "ESTADO CIVIL"], ["CIVIL"]]:
        v = _buscar_valor_derecha(palabras, etiquetas)
        if v:
            normalizado = _valor_estado_civil_campo(v)
            if normalizado:
                return normalizado
    m = re.search(r"(?:EST\.?\s*CIVIL|ESTADO\s+CIVIL)\s*[:\-]?\s*(\w+)", texto, re.IGNORECASE)
    if m:
        return _valor_estado_civil_campo(m.group(1))
    return None


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


def _palabras_desde_doctr(result, img_h: int, img_w: int) -> list:
    """Convierte la salida estructurada de doctr a la lista de palabras que usa _extraer_campos_dni."""
    palabras = []
    try:
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    for word in line.words:
                        texto = (word.value or '').strip()
                        conf  = float(getattr(word, 'confidence', 1.0))
                        if not texto or conf < 0.25:
                            continue
                        (x1n, y1n), (x2n, y2n) = word.geometry
                        x = int(x1n * img_w)
                        y = int(y1n * img_h)
                        w = max(1, int((x2n - x1n) * img_w))
                        h = max(1, int((y2n - y1n) * img_h))
                        palabras.append({
                            'texto': texto,
                            'x': x, 'y': y, 'w': w, 'h': h,
                            'conf': conf * 100,
                        })
    except Exception:
        pass
    return palabras


def _es_nombre_valido(texto: str) -> bool:
    if not texto or len(texto.strip()) < 2:
        return False
    tokens = texto.strip().split()
    if not tokens or len(tokens) > 6:
        return False
    for t in tokens:
        if len(t) < 2:
            return False
        t_up = t.upper()
        if not re.search(r'[AEIOUÁÉÍÓÚÜ]', t_up):
            return False
        if re.search(r'[BCDFGHJKLMNPQRSTVWXYZ]{4,}', t_up):
            return False
        if re.search(r'\d', t):
            return False
    return True


_CAMPOS_LABELS = [
    ('apellido_paterno', [
        r'PRIMER\s+APELLIDO', r'APELLIDO\s+PATERNO', r'1[Ee][Rr]\.?\s*APELLIDO',
    ]),
    ('apellido_materno', [
        r'SEGUNDO\s+APELLIDO', r'APELLIDO\s+MATERNO', r'2[Dd][Oo]\.?\s*APELLIDO',
    ]),
    ('nombres', [r'PRENOMBRES?\b', r'NOMBRES?\b', r'NOMBRE\s+COMPLETO']),
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
    ('grupo_votacion', [r'GRUPO\s+(?:DE\s+)?VOTACI[OÓ]N', r'VOTACI[OÓ]N', r'GR\.?\s*VOT']),
    ('donacion_organos', [r'DONACI[OÓ]N\s+(?:DE\s+)?[OÓ]RGANOS?', r'DONACI[OÓ]N', r'[OÓ]RGANOS?']),
    ('codigo_verificador', [r'C[OÓ]D(?:\.?\s+VERIF|IFICADOR)', r'DIGITO\s+VERIF']),
]

_RE_CUALQUIER_ETIQUETA = re.compile(
    '|'.join(p for _, pats in _CAMPOS_LABELS for p in pats),
    re.IGNORECASE,
)


def _parsear_texto_linea_a_linea(texto: str) -> dict:
    campos: dict = {}
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]

    for i, linea in enumerate(lineas):
        linea_up = linea.upper()
        for campo, patrones in _CAMPOS_LABELS:
            if campo in campos:
                continue
            if not any(re.search(p, linea_up) for p in patrones):
                continue
            for j in range(i + 1, min(i + 5, len(lineas))):
                candidato = lineas[j].strip()
                if _RE_CUALQUIER_ETIQUETA.search(candidato.upper()):
                    continue
                if campo in ('apellido_paterno', 'apellido_materno', 'nombres'):
                    v = _limpiar_valor_nombre(candidato)
                    if v and _es_nombre_valido(v):
                        campos[campo] = v
                elif 'fecha' in campo:
                    v = _normalizar_fecha(candidato)
                    if v:
                        campos[campo] = v
                    elif re.search(r'\d{2}[/\-\.]\d{2}[/\-\.]\d{4}', candidato):
                        m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', candidato)
                        if m:
                            campos[campo] = _normalizar_fecha(m.group(1))
                    if campo not in campos:
                        continue
                elif campo == 'sexo':
                    s = _normalizar_sexo(candidato)
                    if s:
                        campos[campo] = s
                elif campo == 'ubigeo':
                    cand_num = (candidato.replace('O', '0').replace('o', '0')
                                .replace('I', '1').replace('l', '1').replace('|', '1'))
                    m = re.search(r'\b(\d{6})\b', cand_num)
                    if m:
                        campos[campo] = m.group(1)
                elif campo == 'estado_civil':
                    v = _valor_estado_civil_campo(candidato)
                    if v:
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
        'direccion', 'distrito', 'cuarto_nivel', 'grupo_votacion',
        'donacion_organos', 'grupo_sanguineo',
    )}


def _extraer_campos_dni(palabras: list, mrz: dict | None, numero_pillow: str | None,
                        texto_extra: str = '') -> dict:
    texto_bboxes = _texto_completo(palabras) if palabras else ''
    texto_para_regex = '\n'.join(filter(None, [texto_bboxes, texto_extra]))

    if not palabras and not texto_para_regex:
        c = _campos_vacios()
        c['numero_dni'] = numero_pillow
        return c

    seq_pillow = _parsear_texto_linea_a_linea(texto_extra) if texto_extra else {}
    seq_bboxes = _parsear_texto_linea_a_linea(texto_bboxes) if texto_bboxes else {}
    seq_electronico = _extraer_frente_electronico_por_etiquetas(texto_para_regex)
    seq = {**seq_bboxes, **seq_pillow, **seq_electronico}

    lineas = [l.strip() for l in texto_para_regex.splitlines() if l.strip()]
    numero_dni = numero_pillow
    if not numero_dni:
        numero_dni = _extraer_numero_simple(lineas)
    if not numero_dni:
        numero_dni = _extraer_numero_dni_spatial(texto_bboxes, palabras, None)

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


def _campos_engine_doctr(img_bgr, mrz, numero_pillow, texto_pillow='') -> dict:
    model = _get_doctr()
    if model is None:
        c = _campos_vacios()
        c['_engine_error'] = _doctr_error or 'doctr no instalado en el Python activo (pip install python-doctr[torch])'
        return c
    try:
        from doctr.io import DocumentFile  # noqa: PLC0415
        h, w = img_bgr.shape[:2]
        ok, buf = cv2.imencode('.jpg', img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not ok:
            ok, buf = cv2.imencode('.png', img_bgr)
        if not ok:
            raise RuntimeError('No se pudo codificar la imagen para doctr')
        doc = DocumentFile.from_images([buf.tobytes()])
        result = model(doc)
        palabras = _palabras_desde_doctr(result, h, w)
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


def _preparar_documento(imagen_bytes: bytes):
    img_color = _bytes_a_bgr(imagen_bytes)
    try:
        img_color = _rotar_si_necesario(img_color)
        img_color = _corregir_perspectiva(img_color)
    except Exception:
        img_color = _bytes_a_bgr(imagen_bytes)
    img_color = _escalar(img_color)
    img_color = _remover_reflejo_hsv(img_color)
    img_color = _corregir_sombra(img_color)
    return img_color


def _segmentar_dni_azul(img_bgr):
    return {
        'numero':    _recortar(img_bgr, 0.72, 0.00, 1.00, 0.20),
        'apellidos': _recortar(img_bgr, 0.12, 0.15, 0.70, 0.42),
        'nombres':   _recortar(img_bgr, 0.12, 0.35, 0.70, 0.52),
        'datos':     _recortar(img_bgr, 0.12, 0.48, 0.72, 0.72),
        'fechas':    _recortar(img_bgr, 0.12, 0.62, 0.72, 0.84),
        'mrz':       _recortar(img_bgr, 0.00, 0.70, 1.00, 1.00),
    }


def _segmentar_dni_electronico(img_bgr):
    return {
        'numero':             _recortar(img_bgr, 0.00, 0.12, 0.27, 0.34),
        'apellido_paterno':   _recortar(img_bgr, 0.28, 0.14, 0.67, 0.27),
        'apellido_materno':   _recortar(img_bgr, 0.28, 0.26, 0.67, 0.39),
        'nombres_campo':      _recortar(img_bgr, 0.28, 0.37, 0.67, 0.52),
        'sexo':               _recortar(img_bgr, 0.28, 0.51, 0.50, 0.64),
        'estado_civil':       _recortar(img_bgr, 0.52, 0.51, 0.78, 0.64),
        'fecha_nacimiento':   _recortar(img_bgr, 0.28, 0.61, 0.50, 0.73),
        'ubigeo':             _recortar(img_bgr, 0.52, 0.61, 0.78, 0.73),
        'fecha_emision':      _recortar(img_bgr, 0.28, 0.70, 0.50, 0.83),
        'fecha_caducidad':    _recortar(img_bgr, 0.52, 0.70, 0.80, 0.83),
        'grupo_votacion':     _recortar(img_bgr, 0.28, 0.80, 0.52, 0.94),
        'donacion_organos':   _recortar(img_bgr, 0.52, 0.80, 0.78, 0.94),
        'bloque_frente':      _recortar(img_bgr, 0.25, 0.10, 0.80, 0.94),
        'apellidos':          _recortar(img_bgr, 0.27, 0.11, 0.62, 0.39),
        'nombres':            _recortar(img_bgr, 0.27, 0.34, 0.62, 0.51),
        'datos':              _recortar(img_bgr, 0.27, 0.49, 0.76, 0.66),
        'fechas':             _recortar(img_bgr, 0.27, 0.58, 0.76, 0.93),
        'mrz':                _recortar(img_bgr, 0.00, 0.55, 1.00, 1.00),
    }


def _segmentar_reverso_dni_electronico(img_bgr):
    return {
        'direccion':          _recortar(img_bgr, 0.27, 0.04, 0.68, 0.20),
        'distrito':           _recortar(img_bgr, 0.27, 0.19, 0.68, 0.32),
        'cuarto_nivel':       _recortar(img_bgr, 0.27, 0.30, 0.58, 0.39),
        'ubigeo':             _recortar(img_bgr, 0.27, 0.36, 0.58, 0.45),
        'grupo_votacion':     _recortar(img_bgr, 0.27, 0.42, 0.58, 0.51),
        'donacion_organos':   _recortar(img_bgr, 0.27, 0.47, 0.58, 0.56),
        'grupo_sanguineo':    _recortar(img_bgr, 0.27, 0.52, 0.58, 0.61),
        'datos':              _recortar(img_bgr, 0.27, 0.04, 0.68, 0.61),
        'fechas':             _recortar(img_bgr, 0.26, 0.32, 0.56, 0.52),
        'mrz':                _recortar(img_bgr, 0.02, 0.58, 0.98, 0.98),
    }


def _unir_segmentos_vertical(segmentos: dict, claves: tuple[str, ...]):
    partes = [segmentos[k] for k in claves if k in segmentos and segmentos[k].size]
    if not partes:
        return None
    ancho = max(p.shape[1] for p in partes)
    lienzo = []
    separador = np.full((24, ancho, 3), 255, dtype=np.uint8)
    for parte in partes:
        h, w = parte.shape[:2]
        if w != ancho:
            factor = ancho / w
            parte = cv2.resize(parte, (ancho, max(1, int(h * factor))), interpolation=cv2.INTER_LANCZOS4)
        lienzo.append(parte)
        lienzo.append(separador.copy())
    return cv2.vconcat(lienzo[:-1])


def _preparar_mrz_segmento(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.fastNlMeansDenoising(gray, h=20)
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    _, normal = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return normal, cv2.bitwise_not(normal)


def _texto_segmentos_pillow(segmentos: dict, claves: tuple[str, ...]) -> str:
    img_segmentada = _unir_segmentos_vertical(segmentos, claves) if segmentos else None
    if img_segmentada is None or not img_segmentada.size:
        return ''
    try:
        return _texto_pillow_mejor(_img_bgr_a_bytes(img_segmentada))
    except Exception:
        return ''


def _agregar_borde_blanco(img, borde=18):
    return cv2.copyMakeBorder(
        img, borde, borde, borde, borde, cv2.BORDER_CONSTANT, value=[255, 255, 255]
    )


def _preprocesar_campo_ocr(img_bgr, escala=3.0):
    img_bgr = _agregar_borde_blanco(img_bgr, 16)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=escala, fy=escala, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.bilateralFilter(gray, 7, 55, 55)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
    gray = cv2.addWeighted(gray, 1.7, blur, -0.7, 0)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adapt = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9
    )
    return cv2.bitwise_and(otsu, adapt)


def _preprocesar_reverso_texto(img_bgr):
    h, w = img_bgr.shape[:2]
    escala = 2.4 if w >= 360 else 3.0
    img_up = cv2.resize(img_bgr, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    lab = cv2.cvtColor(img_up, cv2.COLOR_BGR2LAB)
    gray = lab[:, :, 0]
    gray = cv2.bilateralFilter(gray, 5, 35, 35)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
    gray = cv2.addWeighted(gray, 1.6, blur, -0.6, 0)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)


def _score_texto_reverso(texto: str) -> int:
    t = (texto or '').upper()
    score = 0
    score += len(re.findall(r'\b(AVENIDA|JR|JIRON|CALLE|DIRECCI[OÓ]N|DEPARTAMENTO|PROVINCIA|DISTRITO)\b', t)) * 4
    score += len(re.findall(r'\b[A-ZÁÉÍÓÚÜÑ]{3,}/[A-ZÁÉÍÓÚÜÑ]{3,}/[A-ZÁÉÍÓÚÜÑ]{3,}\b', t)) * 6
    score += len(re.findall(r'\d{5,9}', t)) * 2
    score -= len(re.findall(r'\b[A-Z0-9]{1,2}\b', t))
    return score


def _ocr_campo_reverso_texto(img_bgr) -> str:
    """OCR para texto fino del reverso (dirección, distrito).
    Combina preprocesamiento top-hat + múltiples PSM + EasyOCR."""
    if img_bgr is None or not img_bgr.size:
        return ''
    textos = []
    img_proc = _preprocesar_reverso_texto(img_bgr)
    for psm in ('6', '11'):
        try:
            t = pytesseract.image_to_string(img_proc, config=_tess_config(psm))
            if t.strip():
                textos.append(t)
        except Exception:
            continue
    reader = _get_easyocr() if _score_texto_reverso('\n'.join(textos)) < 4 else None
    if reader:
        try:
            h, w = img_bgr.shape[:2]
            img_up = cv2.resize(img_bgr, (w * 3, h * 3), interpolation=cv2.INTER_LANCZOS4)
            results = reader.readtext(
                _agregar_borde_blanco(img_up, 20),
                detail=0, paragraph=True,
                contrast_ths=0.1, adjust_contrast=0.5,
                text_threshold=0.5, low_text=0.3,
            )
            textos.extend(str(r) for r in results if str(r).strip())
        except Exception:
            pass
    return '\n'.join(textos)


def _ocr_campo_tesseract(img_bgr, modo='texto', psm='6'):
    if img_bgr is None or not img_bgr.size:
        return ''
    whitelist = ''
    lang = 'spa+eng'
    if modo == 'numero':
        lang = 'eng'
        whitelist = '0123456789-'
    elif modo == 'fecha':
        # Sin whitelist: "NO CADUCA" y similares contienen letras que sería filtradas.
        # La normalización se hace en _valor_fecha_campo, no aquí.
        lang = 'spa+eng'
        whitelist = ''
    elif modo == 'codigo':
        lang = 'eng'
        whitelist = '0123456789'

    textos = []
    imagenes = [_preprocesar_campo_ocr(img_bgr)]
    if modo in ('texto', 'letras'):
        imagenes.append(img_bgr)
    psms = [psm]
    if psm != '7' and modo in ('texto', 'letras'):
        psms.append('7')

    for imagen in imagenes:
        for psm_actual in psms:
            try:
                texto = pytesseract.image_to_string(
                    imagen,
                    config=_tess_config(psm_actual, lang=lang, whitelist=whitelist),
                )
                if texto.strip():
                    textos.append(texto)
                    if modo in ('numero', 'codigo', 'fecha') and psm_actual == psm:
                        return '\n'.join(textos)
            except Exception:
                continue
    return '\n'.join(textos)


def _ocr_campo_easyocr(img_bgr, modo='texto'):
    reader = _get_easyocr()
    if not reader or img_bgr is None or not img_bgr.size:
        return ''
    allowlist = None
    if modo == 'numero':
        allowlist = '0123456789-'
    elif modo == 'fecha':
        allowlist = None  # Sin filtro: "NO CADUCA" contiene letras
    elif modo == 'codigo':
        allowlist = '0123456789'
    elif modo == 'letras':
        allowlist = 'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚÜÑabcdefghijklmnopqrstuvwxyzáéíóúüñ '
    try:
        kwargs = {
            'detail': 0,
            'paragraph': False,
            'contrast_ths': 0.05,
            'adjust_contrast': 0.7,
            'text_threshold': 0.45,
            'low_text': 0.25,
        }
        if allowlist:
            kwargs['allowlist'] = allowlist
        textos = reader.readtext(_agregar_borde_blanco(img_bgr, 12), **kwargs)
        return '\n'.join(str(t) for t in textos if str(t).strip())
    except Exception:
        return ''


def _ocr_campo_combinado(img_bgr, modo='texto', psm='6', skip_easy=False):
    parts = [_ocr_campo_tesseract(img_bgr, modo=modo, psm=psm)]
    if not skip_easy:
        parts.append(_ocr_campo_easyocr(img_bgr, modo=modo))
    return '\n'.join(filter(None, parts))


def _limpiar_texto_campo(texto: str) -> str:
    texto = texto or ''
    texto = texto.replace('|', 'I').replace('`', '').replace('´', '')
    texto = re.sub(r'[_~^"“”]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto)
    return texto.strip()


def _valor_nombre_campo(texto: str, etiquetas: tuple[str, ...]) -> str | None:
    def _candidato_valido(valor: str | None) -> bool:
        if not valor or not _es_nombre_valido(valor):
            return False
        if re.search(r'S[E5]GUNDO|AP[E3I1]LL?ID[O0]|PREN[O0]MBR|N[O0]MBR', valor, re.I):
            return False
        tokens = valor.split()
        if len(tokens) > 4:
            return False
        cortos = [t for t in tokens if len(t) <= 2 and t not in ('DE', 'DEL', 'LA', 'LAS', 'LOS')]
        return len(cortos) == 0

    lineas = [l.strip() for l in (texto or '').splitlines() if l.strip()]
    candidatos = []
    etiquetas_re = '|'.join(re.escape(e) for e in etiquetas) if etiquetas else None
    for linea in lineas:
        limpia = _limpiar_texto_campo(linea)
        if etiquetas_re:
            limpia = re.sub(etiquetas_re, ' ', limpia, flags=re.IGNORECASE)
        limpia = re.sub(r'\b(PRIMER|SEGUNDO|APELLIDO|APELLIDOS|PRENOMBRES|NOMBRES?)\b', ' ', limpia, flags=re.I)
        limpia = _limpiar_valor_nombre(limpia)
        if _candidato_valido(limpia):
            candidatos.append(limpia)
    if candidatos:
        return sorted(candidatos, key=lambda v: (len(v.split()), len(v)))[0]
    texto_limpio = _limpiar_texto_campo(texto)
    if etiquetas_re:
        texto_limpio = re.sub(etiquetas_re, ' ', texto_limpio, flags=re.IGNORECASE)
    texto_limpio = _limpiar_valor_nombre(texto_limpio)
    return texto_limpio if _candidato_valido(texto_limpio) else None


def _valor_fecha_campo(texto: str) -> str | None:
    if not texto:
        return None
    texto_num = _limpiar_ocr_num(texto)
    fecha = _normalizar_fecha(texto_num)
    if fecha:
        return fecha
    m = re.search(r'(\d{2})\s*(\d{2})\s*(\d{4})', texto_num)
    if m:
        return _normalizar_fecha(f'{m.group(1)}/{m.group(2)}/{m.group(3)}')
    if _RE_NO_CADUCA.search(texto):
        return 'NO CADUCA'
    return None


def _valor_sexo_campo(texto: str) -> str | None:
    return _normalizar_sexo(_corregir_nombre(texto or '') or '')


_ESTADOS_CIVILES_VALIDOS = (
    'SOLTERO', 'SOLTERA', 'CASADO', 'CASADA',
    'DIVORCIADO', 'DIVORCIADA', 'VIUDO', 'VIUDA',
    'CONVIVIENTE', 'SEPARADO', 'SEPARADA',
)
# Palabras de otros campos que nunca pertenecen a estado civil
_PALABRAS_SEXO = re.compile(r'\b(MASCULINO|FEMENINO|MASC|FEM)\b', re.IGNORECASE)


def _valor_estado_civil_campo(texto: str) -> str | None:
    texto = _corregir_nombre(texto or '') or ''
    # Eliminar palabras de sexo que se cuelen por overlap de segmento
    texto = _PALABRAS_SEXO.sub('', texto).strip()
    texto = re.sub(r'\bESTADO\b|\bCIVIL\b', ' ', texto).strip()
    texto = re.sub(r'\s+', ' ', texto)
    # Buscar valor exacto en lista blanca
    for estado in _ESTADOS_CIVILES_VALIDOS:
        if estado in texto.upper():
            return estado
    # Correcciones OCR comunes
    if re.search(r'S[O0]LTER[AO]', texto, re.I):
        return 'SOLTERA' if re.search(r'SOLTERA', texto, re.I) else 'SOLTERO'
    if re.search(r'CASAD[AO]', texto, re.I):
        return 'CASADA' if re.search(r'CASADA', texto, re.I) else 'CASADO'
    if re.search(r'VI[UÚ]D[AO]', texto, re.I):
        return 'VIUDA' if re.search(r'VI[UÚ]DA', texto, re.I) else 'VIUDO'
    return None


def _valor_codigo_campo(texto: str, largo=6) -> str | None:
    texto = _limpiar_ocr_num(texto or '')
    candidatos = re.findall(r'\d{%d,9}' % largo, texto)
    if candidatos:
        return candidatos[0][:largo]
    return None


def _valor_texto_reverso(texto: str, etiquetas: tuple[str, ...]) -> str | None:
    lineas = [l.strip() for l in (texto or '').splitlines() if l.strip()]
    etiquetas_re = '|'.join(re.escape(e) for e in etiquetas)
    candidatos = []
    for linea in lineas:
        limpia = _limpiar_texto_campo(linea).upper()
        limpia = re.sub(etiquetas_re, ' ', limpia, flags=re.I)
        limpia = re.sub(r'[^A-Z0-9ÁÉÍÓÚÜÑ/.\-\s]', ' ', limpia)
        limpia = ' '.join(limpia.split())
        if len(limpia) >= 2 and not _es_etiqueta_dni(limpia):
            candidatos.append(limpia)
    return max(candidatos, key=len) if candidatos else None


def _valor_si_no(texto: str) -> str | None:
    texto = _corregir_nombre(texto or '') or ''
    if re.search(r'\bSI\b|\bS[I1]\b', texto):
        return 'SI'
    if re.search(r'\bNO\b|\bN[O0]\b', texto):
        return 'NO'
    return None


def _valor_grupo_sanguineo(texto: str) -> str | None:
    texto = (texto or '').upper().replace('0', 'O')
    m = re.search(r'\b(A|B|AB|O)\s*([+-])\b', texto)
    return f'{m.group(1)}{m.group(2)}' if m else None


_CONECTORES_NOMBRE = {'DE', 'DEL', 'LA', 'LAS', 'LOS', 'Y'}


def _apellido_valido(valor: str | None) -> bool:
    if not valor:
        return False
    tokens = [t for t in str(valor).upper().split() if t not in _CONECTORES_NOMBRE]
    return bool(tokens) and all(len(t) >= 4 for t in tokens) and _es_nombre_valido(' '.join(tokens))


def _nombres_validos(valor: str | None) -> bool:
    if not valor:
        return False
    tokens = str(valor).upper().split()
    utiles = [t for t in tokens if t not in _CONECTORES_NOMBRE]
    return bool(utiles) and _es_nombre_valido(' '.join(tokens))


def _sexo_largo(valor: str | None) -> str | None:
    s = _normalizar_sexo(valor or '')
    if s == 'M':
        return 'MASCULINO'
    if s == 'F':
        return 'FEMENINO'
    if str(valor or '').upper() in ('MASCULINO', 'FEMENINO'):
        return str(valor).upper()
    return None


def _fecha_valida(valor: str | None) -> str | None:
    fecha = _valor_fecha_campo(valor or '')
    if not fecha:
        return None
    if fecha == 'NO CADUCA':
        return fecha
    m = re.fullmatch(r'(\d{2})/(\d{2})/(\d{4})', fecha)
    if not m:
        return None
    dd, mm, yyyy = map(int, m.groups())
    if not (1 <= mm <= 12 and 1 <= dd <= 31 and 1900 <= yyyy <= 2100):
        return None
    if mm in (4, 6, 9, 11) and dd > 30:
        return None
    if mm == 2:
        bisiesto = yyyy % 4 == 0 and (yyyy % 100 != 0 or yyyy % 400 == 0)
        if dd > (29 if bisiesto else 28):
            return None
    return fecha


def _normalizar_campos_electronico(campos: dict) -> dict:
    campos = dict(campos or {})
    if not _apellido_valido(campos.get('apellido_paterno')):
        campos['apellido_paterno'] = None
    if not _apellido_valido(campos.get('apellido_materno')):
        campos['apellido_materno'] = None
    if not _nombres_validos(campos.get('nombres')):
        campos['nombres'] = None
    if not campos.get('apellido_paterno') and not campos.get('apellido_materno'):
        if len(str(campos.get('nombres') or '').split()) < 2:
            campos['nombres'] = None

    campos['sexo'] = _sexo_largo(campos.get('sexo'))
    for k in ('fecha_nacimiento', 'fecha_emision', 'fecha_caducidad'):
        campos[k] = _fecha_valida(campos.get(k))

    if campos.get('fecha_emision') == campos.get('fecha_nacimiento'):
        campos['fecha_emision'] = None
    if campos.get('fecha_caducidad') == campos.get('fecha_emision'):
        campos['fecha_caducidad'] = None
    if campos.get('fecha_caducidad') == campos.get('fecha_nacimiento'):
        campos['fecha_caducidad'] = None

    if campos.get('ubigeo') and not re.fullmatch(r'\d{6}', str(campos['ubigeo'])):
        campos['ubigeo'] = None
    if campos.get('grupo_votacion') and not re.fullmatch(r'\d{6}', str(campos['grupo_votacion'])):
        campos['grupo_votacion'] = None
    return campos


def _lineas_limpias(texto: str) -> list[str]:
    return [
        ' '.join(_limpiar_texto_campo(l).upper().split())
        for l in (texto or '').splitlines()
        if l and l.strip()
    ]


def _valor_despues_etiqueta(lineas: list[str], patrones: tuple[str, ...], stop_extra: str = '',
                            max_lineas: int = 2) -> str | None:
    stop = _RE_CUALQUIER_ETIQUETA.pattern
    if stop_extra:
        stop = f'(?:{stop}|{stop_extra})'
    for i, linea in enumerate(lineas):
        for patron in patrones:
            m = re.search(patron, linea, re.I)
            if not m:
                continue
            resto = linea[m.end():].strip(' :.-')
            if resto:
                cortado = re.split(stop, resto, maxsplit=1, flags=re.I)[0].strip(' :.-')
                if cortado:
                    return cortado
            for j in range(i + 1, min(len(lineas), i + 1 + max_lineas)):
                candidato = lineas[j].strip(' :.-')
                if not candidato or re.search(stop, candidato, re.I):
                    continue
                return candidato
    return None


def _extraer_frente_electronico_por_etiquetas(texto: str) -> dict:
    lineas = _lineas_limpias(texto)
    texto_norm = '\n'.join(lineas)
    campos = {}

    nombre_pats = {
        'apellido_paterno': (r'PRIMER\s+APELLIDO', r'APELLIDO\s+PATERNO'),
        'apellido_materno': (r'SEGUNDO\s+APELLIDO', r'APELLIDO\s+MATERNO'),
        'nombres': (r'PRENOMBRES?', r'NOMBRES?'),
    }
    for clave, patrones in nombre_pats.items():
        raw = _valor_despues_etiqueta(lineas, patrones, max_lineas=2)
        val = _valor_nombre_campo(raw or '', ())
        if val:
            campos[clave] = val

    raw = _valor_despues_etiqueta(lineas, (r'\bSEXO\b',), stop_extra=r'ESTADO\s+CIVIL|FECHA', max_lineas=1)
    sexo = _valor_sexo_campo(raw or '')
    if sexo:
        campos['sexo'] = sexo

    raw = _valor_despues_etiqueta(lineas, (r'ESTADO\s+CIVIL', r'EST\.?\s*CIVIL'), stop_extra=r'FECHA|UBIGEO', max_lineas=1)
    estado = _valor_estado_civil_campo(raw or '')
    if estado:
        campos['estado_civil'] = estado

    fecha_pats = {
        'fecha_nacimiento': (r'FECHA\s+(?:DE\s+)?NACIMIENTO',),
        'fecha_emision': (r'FECHA\s+(?:DE\s+)?EMISI[OÓ]N', r'\bEMISI[OÓ]N\b'),
        'fecha_caducidad': (r'FECHA\s+(?:DE\s+)?CADUCIDAD', r'CADUCIDAD', r'VENCIMIENTO'),
    }
    for clave, patrones in fecha_pats.items():
        raw = _valor_despues_etiqueta(lineas, patrones, stop_extra=r'UBIGEO|GRUPO|DONACI[OÓ]N|SEXO|ESTADO', max_lineas=1)
        val = _valor_fecha_campo(raw or '')
        if val:
            campos[clave] = val

    raw = _valor_despues_etiqueta(lineas, (r'UBIGEO(?:\s+DE\s+NACIMIENTO)?', r'\bUBIGEO\b'), max_lineas=1)
    ubigeo = _valor_codigo_campo(raw or '', largo=6)
    if ubigeo:
        campos['ubigeo'] = ubigeo

    raw = _valor_despues_etiqueta(lineas, (r'GRUPO\s+(?:DE\s+)?VOTACI[OÓ]N',), max_lineas=1)
    grupo = _valor_codigo_campo(raw or '', largo=6)
    if grupo:
        campos['grupo_votacion'] = grupo

    raw = _valor_despues_etiqueta(lineas, (r'DONACI[OÓ]N\s+(?:DE\s+)?[OÓ]RGANOS?',), max_lineas=1)
    don = _valor_si_no(raw or '')
    if don:
        campos['donacion_organos'] = don

    cui = re.search(r'\b(?:CUI|DNI)?\s*(\d{8})\s*[-\s]?\s*(\d{1,2})?\b', texto_norm, re.I)
    if cui and not _parece_fecha(cui.group(1)):
        campos['numero_dni'] = cui.group(1)
        if cui.group(2):
            campos['codigo_verificador'] = cui.group(2)

    return campos


def _limpiar_linea_reverso(linea: str) -> str:
    linea = _limpiar_texto_campo(linea).upper()
    linea = re.sub(r'[^A-Z0-9ÁÉÍÓÚÜÑ/.\-+\s]', ' ', linea)
    return ' '.join(linea.split())


def _extraer_reverso_por_etiquetas(texto: str) -> dict:
    campos = {}
    lineas = [_limpiar_linea_reverso(l) for l in (texto or '').splitlines()]
    lineas = [l for l in lineas if l and not _es_etiqueta_dni(l)]
    texto_norm = '\n'.join(lineas)

    def _valor_despues(patron: str, stop: str, max_lineas=3):
        m = re.search(patron, texto_norm, re.I)
        if not m:
            return None
        resto = texto_norm[m.end():]
        if stop:
            s = re.search(stop, resto, re.I)
            if s:
                resto = resto[:s.start()]
        vals = []
        for linea in resto.splitlines()[:max_lineas]:
            limpia = _limpiar_linea_reverso(linea)
            limpia = re.sub(patron, ' ', limpia, flags=re.I)
            limpia = ' '.join(limpia.split())
            if limpia and not _es_etiqueta_dni(limpia):
                vals.append(limpia)
        return max(vals, key=len) if vals else None

    direccion = _valor_despues(
        r'DIRECCI[OÓ]N|DIRECCION',
        r'DEPARTAMENTO|PROVINCIA|DISTRITO|CUARTO|UBIGEO|GRUPO',
    )
    if direccion:
        campos['direccion'] = direccion

    distrito = _valor_despues(
        r'DEPARTAMENTO\s*/\s*PROVINCIA\s*/\s*DISTRITO|DEPARTAMENTO|PROVINCIA|DISTRITO',
        r'CUARTO|UBIGEO|GRUPO|DONACI[OÓ]N|SANGU[IÍ]NEO',
    )
    if distrito:
        campos['distrito'] = distrito

    patrones_codigo = {
        'cuarto_nivel': r'CUARTO\s+NIVEL\s+(\d{6,9})',
        'ubigeo': r'UBIGEO(?:\s+DE\s+NACIMIENTO)?\s+(\d{6})',
        'grupo_votacion': r'GRUPO\s+(?:DE\s+)?VOTACI[OÓ]N\s+(\d{6})',
    }
    for clave, patron in patrones_codigo.items():
        m = re.search(patron, texto_norm, re.I)
        if m:
            campos[clave] = m.group(1)

    m = re.search(r'DONACI[OÓ]N\s+(?:DE\s+)?[OÓ]RGANOS?\s+(SI|S[I1]|NO|N[O0])', texto_norm, re.I)
    if m:
        campos['donacion_organos'] = _valor_si_no(m.group(1))

    m = re.search(r'(?:GRUPO\s+Y\s+FACTOR\s+)?SANGU[IÍ]NEO\s+(A|B|AB|O|0)\s*([+-])', texto_norm, re.I)
    if m:
        campos['grupo_sanguineo'] = f"{m.group(1).upper().replace('0', 'O')}{m.group(2)}"
    return campos


# Coordenadas de cada campo en el frente del DNI electrónico (fracciones del ancho/alto).
# Usadas por _ocr_campo_multi_crop() para intentar expansiones cuando el OCR falla.
_COORDS_DNI_ELECTRONICO = {
    'apellido_paterno': (0.28, 0.14, 0.67, 0.27),
    'apellido_materno': (0.28, 0.26, 0.67, 0.39),
    'nombres_campo':    (0.28, 0.37, 0.67, 0.52),
    'sexo':             (0.28, 0.51, 0.50, 0.64),
    'estado_civil':     (0.52, 0.51, 0.78, 0.64),
    'fecha_nacimiento': (0.28, 0.61, 0.50, 0.73),
    'ubigeo':           (0.52, 0.61, 0.78, 0.73),
    'fecha_emision':    (0.28, 0.70, 0.50, 0.83),
    'fecha_caducidad':  (0.52, 0.70, 0.80, 0.83),
    'grupo_votacion':   (0.28, 0.80, 0.52, 0.94),
    'donacion_organos': (0.52, 0.80, 0.78, 0.94),
}

_COORDS_REVERSO_ELECTRONICO = {
    'direccion':        (0.27, 0.04, 0.68, 0.20),
    'distrito':         (0.27, 0.19, 0.68, 0.32),
    'cuarto_nivel':     (0.27, 0.30, 0.58, 0.39),
    'ubigeo':           (0.27, 0.36, 0.58, 0.45),
    'grupo_votacion':   (0.27, 0.42, 0.58, 0.51),
    'donacion_organos': (0.27, 0.47, 0.58, 0.56),
    'grupo_sanguineo':  (0.27, 0.52, 0.58, 0.61),
}


def _ocr_campo_multi_crop(img_full, clave: str, modo: str = 'texto', psm: str = '6',
                           validator=None, coords_map: dict | None = None,
                           skip_easy: bool = False) -> str:
    """OCR con múltiples variantes de crop para un campo del DNI electrónico.

    Lógica:
    - Intenta el crop exacto definido en coords_map (o _COORDS_DNI_ELECTRONICO).
    - Si el resultado no supera el validator, expande el recorte en pasos de
      ±2 %, ±5 % y ±8 % en los cuatro bordes hasta obtener un resultado válido.
    - Sin validator devuelve el primer resultado no vacío.
    - Si img_full es None o la clave no está en el mapa, devuelve ''.
    """
    if img_full is None:
        return ''
    mapa = coords_map if coords_map is not None else _COORDS_DNI_ELECTRONICO
    if clave not in mapa:
        return ''

    x1r, y1r, x2r, y2r = mapa[clave]
    primer_resultado = ''

    expansiones = (0.0, 0.02, 0.05, 0.08) if validator else (0.0,)
    for exp in expansiones:
        x1 = max(0.0, x1r - exp)
        y1 = max(0.0, y1r - exp)
        x2 = min(1.0, x2r + exp)
        y2 = min(1.0, y2r + exp)
        crop = _recortar(img_full, x1, y1, x2, y2)
        if crop is None or not crop.size:
            continue
        texto = _ocr_campo_combinado(crop, modo, psm, skip_easy=skip_easy)
        if not texto.strip():
            continue
        if not primer_resultado:
            primer_resultado = texto
        if validator is None or validator(texto):
            return texto

    return primer_resultado


def _extraer_campos_dni_electronico_segmentos(segmentos: dict, segmentos_reverso: dict | None,
                                              numero_pillow: str | None,
                                              cod_verif_zona: str | None,
                                              img_full=None,
                                              img_reverso_full=None) -> dict:
    campos = _campos_vacios()
    campos['numero_dni'] = numero_pillow
    campos['codigo_verificador'] = cod_verif_zona
    lecturas = {}

    def _leer(clave, modo, psm='6', validator=None):
        """Solo Tesseract por campo: EasyOCR corre a nivel de segmento en paralelo."""
        if img_full is not None:
            return _ocr_campo_multi_crop(img_full, clave, modo, psm, validator, skip_easy=True)
        return _ocr_campo_combinado(segmentos.get(clave), modo, psm, skip_easy=True)

    tareas_frente = {
        'apellido_paterno': ('apellido_paterno', 'letras', '6', lambda t: bool(_valor_nombre_campo(t, ()))),
        'apellido_materno': ('apellido_materno', 'letras', '6', lambda t: bool(_valor_nombre_campo(t, ()))),
        'nombres':          ('nombres_campo',    'letras', '6', lambda t: bool(_valor_nombre_campo(t, ()))),
        'sexo':             ('sexo',             'letras', '7', lambda t: bool(_normalizar_sexo(t))),
        'estado_civil':     ('estado_civil',     'letras', '7', lambda t: bool(_valor_estado_civil_campo(t))),
        'fecha_nacimiento': ('fecha_nacimiento', 'fecha',  '7', lambda t: bool(_valor_fecha_campo(t))),
        'ubigeo':           ('ubigeo',           'codigo', '7', lambda t: bool(re.search(r'\d{6}', _limpiar_ocr_num(t)))),
        'fecha_emision':    ('fecha_emision',    'fecha',  '7', lambda t: bool(_valor_fecha_campo(t))),
        'fecha_caducidad':  ('fecha_caducidad',  'fecha',  '7', lambda t: bool(_valor_fecha_campo(t))),
        'grupo_votacion':   ('grupo_votacion',   'codigo', '7', lambda t: bool(re.search(r'\d{6}', _limpiar_ocr_num(t)))),
        'donacion_organos': ('donacion_organos', 'letras', '7', None),
    }
    tareas_pendientes = {
        salida: tarea for salida, tarea in tareas_frente.items()
        if not campos.get(salida)
    }
    if tareas_pendientes:
        with ThreadPoolExecutor(max_workers=_OCR_MAX_WORKERS) as pool:
            futuros = {
                pool.submit(_leer, clave, modo, psm, validator): salida
                for salida, (clave, modo, psm, validator) in tareas_pendientes.items()
            }
            for fut in as_completed(futuros):
                try:
                    lecturas[futuros[fut]] = fut.result()
                except Exception:
                    lecturas[futuros[fut]] = ''

    if not campos.get('apellido_paterno'):
        campos['apellido_paterno'] = _valor_nombre_campo(lecturas.get('apellido_paterno', ''), ('Primer Apellido', 'Apellido Paterno'))
    if not campos.get('apellido_materno'):
        campos['apellido_materno'] = _valor_nombre_campo(lecturas.get('apellido_materno', ''), ('Segundo Apellido', 'Apellido Materno'))
    if not campos.get('nombres'):
        campos['nombres'] = _valor_nombre_campo(lecturas.get('nombres', ''), ('Prenombres', 'Nombres'))
    if not campos.get('sexo'):
        campos['sexo'] = _valor_sexo_campo(lecturas.get('sexo', ''))
    if not campos.get('estado_civil'):
        campos['estado_civil'] = _valor_estado_civil_campo(lecturas.get('estado_civil', ''))
    if not campos.get('fecha_nacimiento'):
        campos['fecha_nacimiento'] = _valor_fecha_campo(lecturas.get('fecha_nacimiento', ''))
    if not campos.get('ubigeo'):
        campos['ubigeo'] = _valor_codigo_campo(lecturas.get('ubigeo', ''), largo=6)
    if not campos.get('fecha_emision'):
        campos['fecha_emision'] = _valor_fecha_campo(lecturas.get('fecha_emision', ''))
    if not campos.get('fecha_caducidad'):
        campos['fecha_caducidad'] = _valor_fecha_campo(lecturas.get('fecha_caducidad', ''))
    # Campos del frente inferior (usados como fuente primaria antes que el reverso)
    if not campos.get('grupo_votacion'):
        campos['grupo_votacion'] = _valor_codigo_campo(lecturas.get('grupo_votacion', ''), largo=6)
    if not campos.get('donacion_organos'):
        campos['donacion_organos'] = _valor_si_no(lecturas.get('donacion_organos', ''))

    if _score_campos(campos) < 12:
        img_bloque_frente = segmentos.get('bloque_frente') if segmentos else None
        if img_full is not None:
            img_bloque_frente = _recortar(img_full, 0.25, 0.10, 0.80, 0.94)
        texto_bloque_frente = _ocr_campo_tesseract(img_bloque_frente, modo='texto', psm='6')
        campos_bloque_frente = _extraer_frente_electronico_por_etiquetas(texto_bloque_frente)
        for k in (
            'numero_dni', 'codigo_verificador', 'fecha_nacimiento', 'sexo',
            'estado_civil', 'ubigeo', 'fecha_emision', 'fecha_caducidad',
            'grupo_votacion', 'donacion_organos',
        ):
            if not campos.get(k) and campos_bloque_frente.get(k):
                campos[k] = campos_bloque_frente[k]
        if texto_bloque_frente:
            lecturas['bloque_frente_fallback'] = texto_bloque_frente

    # Coherencia de fechas: si fecha_emision == fecha_nacimiento el OCR leyó la
    # zona incorrecta (ambas zonas se solapan visualmente en algunos DNI).
    if (campos.get('fecha_emision') and campos.get('fecha_nacimiento')
            and campos['fecha_emision'] == campos['fecha_nacimiento']):
        campos['fecha_emision'] = None

    def _leer_rev(clave, modo, psm='6', validator=None):
        if img_reverso_full is not None:
            return _ocr_campo_multi_crop(img_reverso_full, clave, modo, psm,
                                         validator, coords_map=_COORDS_REVERSO_ELECTRONICO,
                                         skip_easy=True)
        return _ocr_campo_combinado(segmentos_reverso.get(clave) if segmentos_reverso else None,
                                    modo, psm, skip_easy=True)

    def _leer_rev_texto(clave):
        """Lectura de texto libre del reverso con preprocessing top-hat anti-guilloche."""
        if img_reverso_full is not None:
            coords = _COORDS_REVERSO_ELECTRONICO.get(clave)
            if coords:
                x1r, y1r, x2r, y2r = coords
                for exp in (0.0, 0.02, 0.05, 0.08):
                    x1, y1 = max(0.0, x1r - exp), max(0.0, y1r - exp)
                    x2, y2 = min(1.0, x2r + exp), min(1.0, y2r + exp)
                    crop = _recortar(img_reverso_full, x1, y1, x2, y2)
                    if crop is None or not crop.size:
                        continue
                    texto = _ocr_campo_reverso_texto(crop)
                    if texto.strip():
                        return texto
            return ''
        img_seg = segmentos_reverso.get(clave) if segmentos_reverso else None
        return _ocr_campo_reverso_texto(img_seg) if img_seg is not None and img_seg.size else ''

    if segmentos_reverso:
        img_bloque_reverso = None
        if img_reverso_full is not None:
            img_bloque_reverso = _recortar(img_reverso_full, 0.27, 0.04, 0.68, 0.61)
        elif segmentos_reverso:
            img_bloque_reverso = segmentos_reverso.get('datos')
        texto_bloque_reverso = _ocr_campo_reverso_texto(img_bloque_reverso)
        campos_reverso_bloque = _extraer_reverso_por_etiquetas(texto_bloque_reverso)

        tareas_reverso = {
            'direccion':        lambda: _leer_rev_texto('direccion'),
            'distrito':         lambda: _leer_rev_texto('distrito'),
            'cuarto_nivel':     lambda: _leer_rev('cuarto_nivel', 'codigo', psm='7'),
            'ubigeo':           lambda: _leer_rev('ubigeo', 'codigo', psm='7',
                                                  validator=lambda t: bool(re.search(r'\d{6}', _limpiar_ocr_num(t)))),
            'grupo_votacion':   lambda: _leer_rev('grupo_votacion', 'codigo', psm='7'),
            'donacion_organos': lambda: _leer_rev('donacion_organos', 'letras', psm='7'),
            'grupo_sanguineo':  lambda: _leer_rev('grupo_sanguineo', 'texto', psm='7'),
        }
        lecturas_reverso = {k: v for k, v in campos_reverso_bloque.items() if v}
        tareas_pendientes = {
            k: fn for k, fn in tareas_reverso.items()
            if not lecturas_reverso.get(k)
        }
        if tareas_pendientes:
            with ThreadPoolExecutor(max_workers=_OCR_MAX_WORKERS) as pool:
                futuros = {pool.submit(fn): clave for clave, fn in tareas_pendientes.items()}
                for fut in as_completed(futuros):
                    try:
                        lecturas_reverso[futuros[fut]] = fut.result()
                    except Exception:
                        lecturas_reverso[futuros[fut]] = ''
        ubigeo_rev = _valor_codigo_campo(
            lecturas_reverso.get('ubigeo', ''),
            largo=6,
        )
        grupo_rev = _valor_codigo_campo(
            lecturas_reverso.get('grupo_votacion', ''),
            largo=6,
        )
        if not campos.get('ubigeo') and ubigeo_rev:
            campos['ubigeo'] = ubigeo_rev
        campos['direccion'] = (
            campos_reverso_bloque.get('direccion')
            or _valor_texto_reverso(lecturas_reverso.get('direccion', ''), ('Dirección', 'Direccion'))
        )
        campos['distrito'] = _valor_texto_reverso(
            campos_reverso_bloque.get('distrito') or lecturas_reverso.get('distrito', ''),
            ('Departamento / Provincia / Distrito', 'Departamento', 'Provincia', 'Distrito'),
        )
        campos['cuarto_nivel'] = (
            campos_reverso_bloque.get('cuarto_nivel')
            or _valor_codigo_campo(lecturas_reverso.get('cuarto_nivel', ''), largo=9)
        )
        # Usar reverso como fallback: el frente ya asignó estos campos si los detectó
        if not campos.get('grupo_votacion') and grupo_rev:
            campos['grupo_votacion'] = grupo_rev
        don_rev = campos_reverso_bloque.get('donacion_organos') or _valor_si_no(lecturas_reverso.get('donacion_organos', ''))
        if not campos.get('donacion_organos') and don_rev:
            campos['donacion_organos'] = don_rev
        campos['grupo_sanguineo'] = (
            campos_reverso_bloque.get('grupo_sanguineo')
            or _valor_grupo_sanguineo(lecturas_reverso.get('grupo_sanguineo', ''))
        )

        if texto_bloque_reverso:
            lecturas_reverso['bloque'] = texto_bloque_reverso
        lecturas.update({f'reverso_{k}': v for k, v in lecturas_reverso.items()})

    campos['_texto_segmentos'] = '\n'.join(f'{k}: {v}' for k, v in lecturas.items() if v)
    campos_normalizados = _normalizar_campos_electronico(campos)
    campos_normalizados['_texto_segmentos'] = campos.get('_texto_segmentos')
    return campos_normalizados


def _extraer_numero_cui(texto: str) -> tuple[str | None, str | None]:
    texto = _limpiar_ocr_num(texto or '')
    m = re.search(r'\b(?:CUI|DNI)?\s*(\d{8})\s*[-\s]?\s*(\d{1,2})\b', texto, re.IGNORECASE)
    if m and not _parece_fecha(m.group(1)):
        return m.group(1), m.group(2)
    m = re.search(r'\b(\d{8})\b', texto)
    if m and not _parece_fecha(m.group(1)):
        return m.group(1), None
    return None, None


def _extraer_numero_segmentado(segmentos: dict, imagen_bytes: bytes, electronico=False):
    textos = []
    numero_img = segmentos.get('numero')
    if numero_img is not None and numero_img.size:
        numero_bin = _preprocesar_zona(numero_img)
        textos.append(pytesseract.image_to_string(
            numero_bin,
            config=_tess_config('6', lang='eng', whitelist='0123456789-CUIDNI')
        ))
        digitos = _ocr_digitos(numero_bin)
        if digitos:
            textos.append(digitos)
    if not electronico:
        numero = _extraer_numero_multi_variante(imagen_bytes)
        if numero:
            return numero, None
    numero, verificador = _extraer_numero_cui('\n'.join(textos))
    if numero:
        return numero, verificador
    return _extraer_numero_multi_variante(imagen_bytes), None


def _ocr_tesseract_segmentado(segmentos: dict, claves: tuple[str, ...]) -> list:
    img_segmentada = _unir_segmentos_vertical(segmentos, claves)
    if img_segmentada is None:
        return []
    img_bin = _preprocesar_zona(img_segmentada)
    img_bin = _deskew(img_bin)
    datos_ocr = _obtener_datos_ocr(img_bin)
    return _construir_palabras(datos_ocr)


def _campos_engine_easyocr_segmentado(segmentos: dict, claves: tuple[str, ...], mrz,
                                      numero_pillow, texto_pillow='') -> dict:
    img_segmentada = _unir_segmentos_vertical(segmentos, claves)
    if img_segmentada is None:
        return _campos_vacios()
    return _campos_engine_easyocr(img_segmentada, mrz, numero_pillow, texto_pillow)


def _campos_engine_doctr_segmentado(segmentos: dict, claves: tuple[str, ...], mrz,
                                    numero_pillow, texto_pillow='') -> dict:
    img_segmentada = _unir_segmentos_vertical(segmentos, claves)
    if img_segmentada is None:
        return _campos_vacios()
    return _campos_engine_doctr(img_segmentada, mrz, numero_pillow, texto_pillow)


def _votar_campos_multi(campos_lista: list) -> dict:
    """Fusiona resultados de múltiples engines OCR por votación de mayoría.
    - Si ≥2 engines coinciden en un valor, ese gana.
    - En empate: gana el valor del motor con mayor cobertura de campos.
    - Los campos que empiezan con '_' se copian tal cual del primer engine."""
    from collections import Counter
    mejor = _mejor_campos(campos_lista)
    all_keys: set = set()
    for c in campos_lista:
        all_keys.update(k for k in c if not k.startswith('_'))

    resultado: dict = {}
    for key in all_keys:
        valores = [c[key] for c in campos_lista if c.get(key)]
        if not valores:
            resultado[key] = None
            continue
        if len(set(valores)) == 1:
            resultado[key] = valores[0]
            continue
        conteo = Counter(valores)
        mas_comun, freq = conteo.most_common(1)[0]
        if freq > 1:
            resultado[key] = mas_comun
        else:
            valor_mejor = mejor.get(key)
            if valor_mejor:
                resultado[key] = valor_mejor
            elif key in ('numero_dni', 'ubigeo', 'codigo_verificador', 'cuarto_nivel',
                         'grupo_votacion'):
                resultado[key] = min(valores, key=len)
            else:
                resultado[key] = max(valores, key=len)

    for k, v in mejor.items():
        if not k.startswith('_') and v and not resultado.get(k):
            resultado[k] = v

    # Copiar campos internos del primer engine sin errores (_texto_segmentos, etc.)
    # NUNCA copiar _engine_error — el resultado votado no es un engine con fallo.
    for c in campos_lista:
        for k, v in c.items():
            if k.startswith('_') and k != '_engine_error' and k not in resultado:
                resultado[k] = v
    resultado['_engine_score'] = _score_campos(mejor)
    return resultado


def _fusionar_campos(base: dict, extra: dict) -> dict:
    combinado = dict(base)
    for k, v in (extra or {}).items():
        if k.startswith('_'):
            combinado[k] = v
        elif not combinado.get(k) and v:
            combinado[k] = v
    return combinado


_PESOS_CALIDAD_CAMPO = {
    'apellido_paterno': 4,
    'apellido_materno': 4,
    'nombres': 4,
    'fecha_nacimiento': 3,
    'sexo': 2,
    'estado_civil': 2,
    'ubigeo': 3,
    'fecha_emision': 2,
    'fecha_caducidad': 2,
    'codigo_verificador': 2,
    'numero_dni': 1,
    'direccion': 1,
    'distrito': 1,
    'cuarto_nivel': 1,
    'grupo_votacion': 1,
    'donacion_organos': 1,
    'grupo_sanguineo': 1,
}


def _score_campos(campos: dict) -> int:
    score = 0
    for k, peso in _PESOS_CALIDAD_CAMPO.items():
        v = campos.get(k)
        if not v:
            continue
        score += peso
        if k in ('apellido_paterno', 'apellido_materno', 'nombres') and _es_nombre_valido(str(v)):
            score += 1
        elif k.startswith('fecha') and _valor_fecha_campo(str(v)):
            score += 1
        elif k in ('ubigeo', 'grupo_votacion') and re.fullmatch(r'\d{6}', str(v)):
            score += 1
        elif k == 'numero_dni' and re.fullmatch(r'\d{8}', str(v)):
            score += 1
    return score


def _mejor_campos(campos_lista: list[dict]) -> dict:
    return max(campos_lista, key=_score_campos) if campos_lista else {}


def _extraer_mrz_documento(frente_bytes: bytes, reverso_bytes: bytes | None,
                           segmentos_frente: dict, segmentos_reverso: dict | None):
    for imagen_bytes in (reverso_bytes, frente_bytes):
        if not imagen_bytes:
            continue
        mrz = _parsear_mrz_fastmrz(imagen_bytes)
        if mrz:
            return mrz, ''

    textos = []
    for segmentos in (segmentos_reverso, segmentos_frente):
        if not segmentos or 'mrz' not in segmentos:
            continue
        img_mrz_n, img_mrz_i = _preparar_mrz_segmento(segmentos['mrz'])
        texto_mrz = _ocr_mrz_zona(img_mrz_n, img_mrz_i)
        textos.append(texto_mrz)
        mrz = _parsear_mrz(texto_mrz)
        if mrz:
            return mrz, texto_mrz
    return None, '\n'.join(textos)


def _procesar_dni(frente_bytes: bytes, reverso_bytes: bytes | None = None,
                  electronico: bool = False) -> dict:
    if reverso_bytes:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_frente = pool.submit(_preparar_documento, frente_bytes)
            fut_reverso = pool.submit(_preparar_documento, reverso_bytes)
            img_color = fut_frente.result()
            img_reverso = fut_reverso.result()
    else:
        img_color = _preparar_documento(frente_bytes)
        img_reverso = None

    if electronico:
        img_limpia = img_color
        segmentos = _segmentar_dni_electronico(img_limpia)
        segmentos_reverso = _segmentar_reverso_dni_electronico(img_reverso) if img_reverso is not None else None
    else:
        img_sin_azul = _eliminar_franja_azul(img_color)
        img_limpia = _eliminar_encabezado_naranja(img_sin_azul)
        segmentos = _segmentar_dni_azul(img_limpia)
        segmentos_reverso = _segmentar_dni_azul(img_reverso) if img_reverso is not None else None

    claves_texto = ('apellidos', 'nombres', 'datos', 'fechas')
    claves_ocr = ('apellidos', 'nombres', 'datos', 'fechas')

    numero_pillow, cod_verif_zona = _extraer_numero_segmentado(
        segmentos, frente_bytes, electronico=electronico
    )

    texto_frente = _texto_segmentos_pillow(segmentos, ('numero',) + claves_texto)
    texto_reverso = _texto_segmentos_pillow(segmentos_reverso, ('mrz',)) if segmentos_reverso else ''
    texto_pillow = '\n'.join(filter(None, [texto_frente, texto_reverso]))

    mrz, texto_mrz = _extraer_mrz_documento(frente_bytes, reverso_bytes, segmentos, segmentos_reverso)
    if not mrz and texto_pillow:
        mrz = _parsear_mrz(_mrz_desde_texto_general(texto_pillow) or '')

    palabras_tess = _ocr_tesseract_segmentado(segmentos, claves_ocr)

    if not numero_pillow:
        texto_esp = _texto_completo(palabras_tess)
        numero_pillow = _extraer_numero_dni_spatial(
            texto_esp, palabras_tess, _preprocesar_zona(segmentos['numero'])
        )
        if not numero_pillow and mrz:
            numero_pillow = mrz.get('numero_dni_mrz')

    # Tesseract ya corrió (palabras_tess); ahora lanzar EasyOCR + doctr en paralelo.
    # _extraer_campos_dni_electronico_segmentos (directos) corre solo Tesseract por campo
    # (skip_easy=True), por lo que puede ejecutarse en paralelo con EasyOCR y doctr.
    campos_tess = _extraer_campos_dni(palabras_tess, mrz, numero_pillow, texto_extra=texto_pillow)

    def _run_easy():
        return _campos_engine_easyocr_segmentado(segmentos, claves_ocr, mrz, numero_pillow, texto_pillow)

    def _run_doctr():
        return _campos_engine_doctr_segmentado(segmentos, claves_ocr, mrz, numero_pillow, texto_pillow)

    def _run_directos():
        if not electronico:
            return None
        return _extraer_campos_dni_electronico_segmentos(
            segmentos, segmentos_reverso, numero_pillow, cod_verif_zona,
            img_full=img_limpia,
            img_reverso_full=img_reverso,
        )

    with ThreadPoolExecutor(max_workers=3) as _pool:
        fut_easy     = _pool.submit(_run_easy)
        fut_doctr    = _pool.submit(_run_doctr)
        fut_directos = _pool.submit(_run_directos)
        campos_easy     = fut_easy.result()
        campos_doctr    = fut_doctr.result()
        campos_directos = fut_directos.result()

    if campos_directos is not None:
        campos_tess  = _fusionar_campos(campos_directos, campos_tess)
        campos_easy  = _fusionar_campos(campos_directos, campos_easy)
        campos_doctr = _fusionar_campos(campos_directos, campos_doctr)

    if electronico:
        campos_tess = _normalizar_campos_electronico(campos_tess)
        campos_easy = _normalizar_campos_electronico(campos_easy)
        campos_doctr = _normalizar_campos_electronico(campos_doctr)

    if cod_verif_zona:
        for campos in (campos_tess, campos_easy, campos_doctr):
            campos['codigo_verificador'] = campos.get('codigo_verificador') or cod_verif_zona

    if segmentos_reverso:
        reverso_texto = _texto_segmentos_pillow(segmentos_reverso, ('datos', 'fechas', 'mrz'))
        if reverso_texto:
            campos_reverso = _extraer_campos_dni([], mrz, numero_pillow, texto_extra=reverso_texto)
            campos_tess  = _fusionar_campos(campos_tess, campos_reverso)
            campos_easy  = _fusionar_campos(campos_easy, campos_reverso)
            campos_doctr = _fusionar_campos(campos_doctr, campos_reverso)

    if electronico:
        campos_tess = _normalizar_campos_electronico(campos_tess)
        campos_easy = _normalizar_campos_electronico(campos_easy)
        campos_doctr = _normalizar_campos_electronico(campos_doctr)

    # ── Votación multi-engine: campo ganado por mayoría de 3 engines ──────────
    campos_votados = _votar_campos_multi([campos_tess, campos_easy, campos_doctr])
    if electronico:
        campos_votados = _normalizar_campos_electronico(campos_votados)

    # ── RENIEC: usar número validado con dígito verificador cuando sea posible ─
    numero_final = campos_votados.get('numero_dni')
    if not numero_final:
        numero_final = (campos_tess.get('numero_dni')
                        or campos_easy.get('numero_dni')
                        or campos_doctr.get('numero_dni'))

    dv_final = (campos_votados.get('codigo_verificador')
                or cod_verif_zona
                or campos_tess.get('codigo_verificador'))

    # Validar número con dígito verificador RENIEC
    numero_valido = False
    dv_calculado = None
    if numero_final and len(numero_final) == 8 and numero_final.isdigit():
        dv_calculado = _calcular_digito_verificador(numero_final)
        if dv_final:
            numero_valido = _validar_digito_verificador(numero_final, dv_final)
        else:
            numero_valido = True

    reniec_data = None
    if numero_final and len(numero_final) == 8 and numero_final.isdigit():
        reniec_data = _consultar_reniec(numero_final)
        if reniec_data:
            for campos in (campos_tess, campos_easy, campos_doctr, campos_votados):
                _aplicar_reniec(campos, reniec_data)

    if dv_calculado and not dv_final:
        for campos in (campos_tess, campos_easy, campos_doctr, campos_votados):
            campos['codigo_verificador'] = campos.get('codigo_verificador') or dv_calculado['numerico']

    meta_validacion = {
        'numero_dni_valido':        numero_valido,
        'digito_verificador_calc':  dv_calculado['numerico'] if dv_calculado else None,
        'digito_verificador_alpha': dv_calculado['alfabetico'] if dv_calculado else None,
    }
    for campos in (campos_tess, campos_easy, campos_doctr, campos_votados):
        campos.update(meta_validacion)

    return {
        'tipo_documento': 'DNI_ELECTRONICO' if electronico else 'DNI',
        'votado':    campos_votados,
        'tesseract': campos_tess,
        'easyocr':   campos_easy,
        'doctr':     campos_doctr,
        'reniec':    reniec_data,
        'texto_raw': '\n'.join(filter(None, [
            texto_pillow,
            campos_directos.get('_texto_segmentos') if campos_directos else '',
            texto_mrz,
        ])),
    }


def _procesar_carnet(imagen_bytes: bytes) -> dict:
    img = Image.open(io.BytesIO(imagen_bytes)).convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    w, h = img.size
    if w < 800:
        img = img.resize((int(w * 800 / w), int(h * 800 / w)), Image.LANCZOS)

    texto = pytesseract.image_to_string(img, config=_tess_config('6'))
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


def detectar(imagen_bytes: bytes, tipo_documento: str, reverso_bytes: bytes | None = None) -> dict:
    if not OCR_DISPONIBLE:
        raise RuntimeError(
            'Faltan dependencias'
        )
    acquired = _OCR_REQUEST_SEMAPHORE.acquire(timeout=int(os.getenv('OCR_QUEUE_TIMEOUT', '180')))
    if not acquired:
        raise RuntimeError('El servicio OCR esta ocupado. Intenta nuevamente en unos minutos.')
    try:
        if tipo_documento == 'DNI_ELECTRONICO':
            return _procesar_dni(imagen_bytes, reverso_bytes, electronico=True)
        return _procesar_dni(imagen_bytes, reverso_bytes, electronico=False)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f'Error al procesar la imagen: {exc}. '
            'Verifica que Tesseract este instalado correctamente.'
        ) from exc
    finally:
        _OCR_REQUEST_SEMAPHORE.release()

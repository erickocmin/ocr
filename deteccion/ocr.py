import io
import os
import re
import threading
from time import perf_counter

import requests as _requests
from PIL import Image, ImageEnhance, ImageFilter

try:
    import cv2
    import numpy as np
    OCR_DISPONIBLE = True
    _IMPORT_ERROR = None
except ImportError as exc:
    cv2 = None
    np = None
    OCR_DISPONIBLE = False
    _IMPORT_ERROR = str(exc)

_RENIEC_TOKEN = os.getenv('RENIEC_TOKEN', 'apis-token-16099.nd0kCbthWLqfHqL04GbpyY3e8OE83L5G')
_RENIEC_URL = 'https://api.apis.net.pe/v2/reniec/dni'
_OCR_CONCURRENT_REQUESTS = max(1, int(os.getenv('OCR_CONCURRENT_REQUESTS', '1')))
_OCR_REQUEST_SEMAPHORE = threading.BoundedSemaphore(_OCR_CONCURRENT_REQUESTS)
_OCR_TARGET_WIDTH = int(os.getenv('OCR_TARGET_WIDTH', '960'))
_OCR_MAX_SECONDS = float(os.getenv('OCR_MAX_SECONDS', '10'))
_OCR_USE_PADDLE_FALLBACK = os.getenv('OCR_USE_PADDLE_FALLBACK', '0') == '1'
_OCR_MIN_SCORE_FAST = int(os.getenv('OCR_MIN_SCORE_FAST', '18'))
_OCR_FAST_DNI_KEYS = int(os.getenv('OCR_FAST_DNI_KEYS', '4'))

_paddle_model = None
_paddle_error = None
_paddle_lock = threading.Lock()
_doctr_model = None
_doctr_error = None
_doctr_lock = threading.Lock()

_PESOS_DV_RENIEC = [3, 2, 7, 6, 5, 4, 3, 2]
_TABLA_DV_NUMERICO = [6, 7, 8, 9, 0, 1, 1, 2, 3, 4, 5]
_TABLA_DV_ALFABETICO = ['K', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']

_FIELD_KEYS = (
    'numero_dni', 'codigo_verificador', 'apellido_paterno', 'apellido_materno',
    'nombres', 'fecha_nacimiento', 'sexo', 'estado_civil', 'ubigeo',
    'fecha_emision', 'fecha_caducidad', 'direccion', 'distrito',
    'cuarto_nivel', 'grupo_votacion', 'donacion_organos', 'grupo_sanguineo',
)

_COORDS_FRENTE_ELECTRONICO = {
    'numero_dni': (0.66, 0.05, 0.98, 0.22),
    'apellido_paterno': (0.27, 0.13, 0.72, 0.27),
    'apellido_materno': (0.27, 0.25, 0.72, 0.39),
    'nombres': (0.27, 0.36, 0.74, 0.52),
    'sexo': (0.27, 0.50, 0.50, 0.64),
    'estado_civil': (0.50, 0.50, 0.78, 0.64),
    'fecha_nacimiento': (0.27, 0.60, 0.50, 0.74),
    'ubigeo': (0.50, 0.60, 0.78, 0.74),
    'fecha_emision': (0.27, 0.69, 0.50, 0.84),
    'fecha_caducidad': (0.50, 0.69, 0.82, 0.84),
    'grupo_votacion': (0.27, 0.79, 0.53, 0.95),
    'donacion_organos': (0.50, 0.79, 0.82, 0.95),
}

_COORDS_REVERSO_ELECTRONICO = {
    'direccion': (0.25, 0.03, 0.73, 0.21),
    'distrito': (0.25, 0.18, 0.75, 0.33),
    'cuarto_nivel': (0.25, 0.29, 0.62, 0.40),
    'ubigeo': (0.25, 0.35, 0.62, 0.47),
    'grupo_votacion': (0.25, 0.41, 0.62, 0.53),
    'donacion_organos': (0.25, 0.46, 0.62, 0.58),
    'grupo_sanguineo': (0.25, 0.51, 0.62, 0.64),
}

_LABELS = {
    'apellido_paterno': (r'PRIMER\s+APELLIDO', r'APELLIDO\s+PATERNO'),
    'apellido_materno': (r'SEGUNDO\s+APELLIDO', r'APELLIDO\s+MATERNO'),
    'nombres': (r'PRENOMBRES?', r'NOMBRES?'),
    'fecha_nacimiento': (r'NACIMIENTO', r'F\.?\s*NAC'),
    'sexo': (r'\bSEXO\b',),
    'estado_civil': (r'ESTADO\s+CIVIL', r'EST\.?\s*CIVIL'),
    'ubigeo': (r'\bUBIGEO\b', r'\bUBIG\b'),
    'fecha_emision': (r'EMISI[OÓ]N', r'F\.?\s*EMIS'),
    'fecha_caducidad': (r'CADUCIDAD', r'VENCIMIENTO', r'F\.?\s*VENC'),
    'grupo_votacion': (r'VOTACI[OÓ]N', r'GR\.?\s*VOT'),
    'donacion_organos': (r'DONACI[OÓ]N', r'[OÓ]RGANOS?'),
    'direccion': (r'DIRECCI[OÓ]N',),
    'distrito': (r'DEPARTAMENTO', r'PROVINCIA', r'DISTRITO'),
    'cuarto_nivel': (r'CUARTO\s+NIVEL',),
    'grupo_sanguineo': (r'GRUPO\s+SANGU[IÍ]NEO', r'SANGU[IÍ]NEO'),
}
_ANY_LABEL_RE = re.compile('|'.join(p for pats in _LABELS.values() for p in pats), re.I)


def _campos_vacios() -> dict:
    return {k: None for k in _FIELD_KEYS}


def _calcular_digito_verificador(numero_8: str) -> dict | None:
    if not (numero_8 and re.fullmatch(r'\d{8}', str(numero_8))):
        return None
    suma = sum(int(d) * p for d, p in zip(numero_8, _PESOS_DV_RENIEC))
    idx = suma % 11
    return {'numerico': str(_TABLA_DV_NUMERICO[idx]), 'alfabetico': _TABLA_DV_ALFABETICO[idx]}


def _validar_digito_verificador(numero_8: str, digito: str) -> bool:
    res = _calcular_digito_verificador(numero_8)
    if not res:
        return False
    dv = str(digito or '').upper().strip()
    return dv in (res['numerico'], res['alfabetico'])


def _get_paddle():
    global _paddle_model, _paddle_error
    if _paddle_model is not None:
        return _paddle_model
    with _paddle_lock:
        if _paddle_model is not None:
            return _paddle_model
        try:
            # os.environ.setdefault('FLAGS_use_mkldnn', '0')
            # os.environ.setdefault('FLAGS_enable_pir_api', '0')
            os.environ["FLAGS_use_mkldnn"] = "0"
            os.environ["FLAGS_enable_pir_api"] = "0"
            os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
            from paddleocr import PaddleOCR  # noqa: PLC0415
            lang = os.getenv('OCR_PADDLE_LANG', 'es')
            configs = (
                {
                    'lang': lang,
                    'text_detection_model_name': os.getenv('OCR_PADDLE_DET_MODEL', 'PP-OCRv5_mobile_det'),
                    'text_recognition_model_name': os.getenv('OCR_PADDLE_REC_MODEL', 'latin_PP-OCRv5_mobile_rec'),
                    'use_doc_orientation_classify': False,
                    'use_doc_unwarping': False,
                    'use_textline_orientation': False,
                    'text_det_limit_side_len': _OCR_TARGET_WIDTH,
                },
                {'lang': lang, 'use_angle_cls': False, 'show_log': False},
                {'lang': lang},
                {},
            )
            last_exc = None
            for cfg in configs:
                try:
                    _paddle_model = PaddleOCR(**cfg)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
            if _paddle_model is None and last_exc is not None:
                raise last_exc
            _paddle_error = None
        except Exception as exc:
            _paddle_error = str(exc)[:240]
        return _paddle_model


def _get_doctr():
    global _doctr_model, _doctr_error
    if _doctr_model is not None:
        return _doctr_model
    with _doctr_lock:
        if _doctr_model is not None:
            return _doctr_model
        try:
            try:
                import torch  # noqa: PLC0415
                torch.set_num_threads(max(1, int(os.getenv('OCR_TORCH_THREADS', '2'))))
            except Exception:
                pass
            from doctr.models import ocr_predictor  # noqa: PLC0415
            _doctr_model = ocr_predictor(
                det_arch=os.getenv('OCR_DOCTR_DET_ARCH', 'db_mobilenet_v3_large'),
                reco_arch=os.getenv('OCR_DOCTR_RECO_ARCH', 'crnn_mobilenet_v3_small'),
                pretrained=True,
                assume_straight_pages=True,
            )
            _doctr_error = None
        except Exception as exc:
            _doctr_error = str(exc)[:240]
        return _doctr_model


if os.getenv('OCR_PRELOAD_DOCTR', '1') == '1' and OCR_DISPONIBLE:
    threading.Thread(target=_get_doctr, daemon=True).start()


def _bytes_a_bgr(imagen_bytes: bytes):
    arr = np.frombuffer(imagen_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError('No se pudo decodificar la imagen. Verifica el formato.')
    return img


def _orientar_horizontal(img_bgr):
    h, w = img_bgr.shape[:2]
    if h > w * 1.08:
        return cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
    return img_bgr


def _corregir_perspectiva(img_bgr):
    h, w = img_bgr.shape[:2]
    area_total = h * w
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=1)
    contornos, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in sorted(contornos, key=cv2.contourArea, reverse=True)[:6]:
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if len(approx) != 4 or cv2.contourArea(approx) < area_total * 0.35:
            continue
        pts = approx.reshape(4, 2).astype(np.float32)
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1)
        rect = np.array([pts[np.argmin(s)], pts[np.argmin(diff)], pts[np.argmax(s)], pts[np.argmax(diff)]], dtype=np.float32)
        ancho = max(int(np.linalg.norm(rect[1] - rect[0])), int(np.linalg.norm(rect[2] - rect[3])))
        alto = max(int(np.linalg.norm(rect[3] - rect[0])), int(np.linalg.norm(rect[2] - rect[1])))
        ratio = ancho / alto if alto else 0
        if 1.35 < ratio < 1.85 and ancho > 300 and alto > 180:
            dst = np.array([[0, 0], [ancho - 1, 0], [ancho - 1, alto - 1], [0, alto - 1]], dtype=np.float32)
            return cv2.warpPerspective(img_bgr, cv2.getPerspectiveTransform(rect, dst), (ancho, alto))
    return img_bgr


def _preparar_documento(imagen_bytes: bytes):
    img = _orientar_horizontal(_bytes_a_bgr(imagen_bytes))
    img = _corregir_perspectiva(img)
    img = _orientar_horizontal(img)
    h, w = img.shape[:2]
    if w > _OCR_TARGET_WIDTH:
        factor = _OCR_TARGET_WIDTH / w
        img = cv2.resize(img, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_AREA)
    elif w < 900:
        factor = 900 / w
        img = cv2.resize(img, (900, int(h * factor)), interpolation=cv2.INTER_CUBIC)
    h, w = img.shape[:2]
    lado_mayor = max(h, w)
    if lado_mayor > _OCR_TARGET_WIDTH:
        factor = _OCR_TARGET_WIDTH / lado_mayor
        img = cv2.resize(img, (max(1, int(w * factor)), max(1, int(h * factor))), interpolation=cv2.INTER_AREA)
    return img


def _preprocesar_ocr(img_bgr):
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def _recortar(img_bgr, coords):
    h, w = img_bgr.shape[:2]
    x1, y1, x2, y2 = coords
    return img_bgr[max(0, int(h * y1)):min(h, int(h * y2)), max(0, int(w * x1)):min(w, int(w * x2))]


def _normalizar_texto(txt: str) -> str:
    txt = (txt or '').replace('|', 'I').replace('`', '').replace('´', '')
    txt = re.sub(r'[_~^"“”]', ' ', txt)
    return re.sub(r'\s+', ' ', txt).strip()


def _limpiar_num(txt: str) -> str:
    return (txt or '').upper().replace('O', '0').replace('Q', '0').replace('I', '1').replace('L', '1')


def _normalizar_fecha(txt: str) -> str | None:
    t = _limpiar_num(txt)
    if re.search(r'NO\s*CADUCA|NO\s*EXPIRA', t, re.I):
        return 'NO CADUCA'
    m = re.search(r'(\d{1,2})[\/\-. ](\d{1,2})[\/\-. ](\d{2,4})', t)
    if not m:
        return None
    d, mth, y = m.groups()
    if len(y) == 2:
        y = ('20' if int(y) <= 30 else '19') + y
    try:
        dd, mm, yy = int(d), int(mth), int(y)
        if not (1 <= dd <= 31 and 1 <= mm <= 12 and 1900 <= yy <= 2100):
            return None
    except ValueError:
        return None
    return f'{dd:02d}/{mm:02d}/{yy:04d}'


def _normalizar_sexo(txt: str) -> str | None:
    t = _normalizar_texto(txt).upper()
    if re.search(r'\b(M|MASCULINO)\b', t):
        return 'MASCULINO'
    if re.search(r'\b(F|FEMENINO)\b', t):
        return 'FEMENINO'
    return None


def _normalizar_estado(txt: str) -> str | None:
    t = _normalizar_texto(txt).upper()
    for raw, val in (
        ('SOLTER', 'SOLTERO'), ('CASAD', 'CASADO'), ('VIUD', 'VIUDO'),
        ('DIVORCIAD', 'DIVORCIADO'), ('CONVIV', 'CONVIVIENTE'),
    ):
        if raw in t:
            return val
    return None


def _normalizar_si_no(txt: str) -> str | None:
    t = _normalizar_texto(txt).upper()
    if re.search(r'\b(SI|S[I1])\b', t):
        return 'SI'
    if re.search(r'\b(NO|N0)\b', t):
        return 'NO'
    return None


def _normalizar_nombre(txt: str) -> str | None:
    t = _normalizar_texto(txt).upper()
    t = re.sub(r'\b(PRIMER|SEGUNDO|APELLIDO|APELLIDOS|PATERNO|MATERNO|PRENOMBRES?|NOMBRES?)\b', ' ', t)
    t = t.translate(str.maketrans('015348672', 'OISAEBGZA'))
    t = re.sub(r'[^A-ZÁÉÍÓÚÜÑ ]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    if not t:
        return None
    tokens = [x for x in t.split() if len(x) > 1]
    if not tokens or len(tokens) > 6:
        return None
    if any(not re.search(r'[AEIOUÁÉÍÓÚÜ]', x) for x in tokens):
        return None
    return ' '.join(tokens)


def _normalizar_codigo(txt: str, largo: int) -> str | None:
    m = re.search(rf'\b(\d{{{largo}}})\b', _limpiar_num(txt))
    return m.group(1) if m else None


def _normalizar_grupo_sanguineo(txt: str) -> str | None:
    t = _normalizar_texto(txt).upper().replace('0', 'O')
    m = re.search(r'\b(O|A|B|AB)\s*([+-])\b', t)
    return f'{m.group(1)}{m.group(2)}' if m else None


def _extraer_numero_dni(texto: str) -> tuple[str | None, str | None]:
    t = _limpiar_num(texto)
    for pat in (
        r'\b(?:CUI|DNI)?\s*(\d{8})\s*[- ]\s*(\d{1,2})\b',
        r'\b(?:CUI|DNI)\s*(\d{8})\b',
        r'\b(\d{8})\b',
    ):
        m = re.search(pat, t, re.I)
        if m:
            numero = m.group(1)
            if not _normalizar_fecha(numero):
                return numero, m.group(2) if len(m.groups()) > 1 else None
    return None, None


def _lineas_desde_palabras(palabras):
    if not palabras:
        return []
    ordenadas = sorted(palabras, key=lambda p: (p['y'], p['x']))
    lineas = []
    actual = [ordenadas[0]]
    for p in ordenadas[1:]:
        tolerancia = max(12, int(max(actual[-1]['h'], p['h']) * 0.75))
        if abs(p['y'] - actual[-1]['y']) <= tolerancia:
            actual.append(p)
        else:
            lineas.append(sorted(actual, key=lambda x: x['x']))
            actual = [p]
    lineas.append(sorted(actual, key=lambda x: x['x']))
    return [' '.join(p['texto'] for p in linea) for linea in lineas]


def _texto_completo(palabras):
    return '\n'.join(_lineas_desde_palabras(palabras))


def _palabras_en_roi(palabras, coords, shape):
    h, w = shape[:2]
    x1, y1, x2, y2 = coords
    out = []
    for p in palabras:
        cx = (p['x'] + p['w'] / 2) / w
        cy = (p['y'] + p['h'] / 2) / h
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            out.append(p)
    return _normalizar_texto(_texto_completo(out))


def _valor_por_campo(campo: str, texto: str) -> str | None:
    if campo in ('apellido_paterno', 'apellido_materno', 'nombres'):
        return _normalizar_nombre(texto)
    if campo.startswith('fecha_'):
        return _normalizar_fecha(texto)
    if campo == 'sexo':
        return _normalizar_sexo(texto)
    if campo == 'estado_civil':
        return _normalizar_estado(texto)
    if campo in ('ubigeo', 'grupo_votacion'):
        return _normalizar_codigo(texto, 6)
    if campo == 'cuarto_nivel':
        return _normalizar_codigo(texto, 9)
    if campo == 'donacion_organos':
        return _normalizar_si_no(texto)
    if campo == 'grupo_sanguineo':
        return _normalizar_grupo_sanguineo(texto)
    if campo in ('direccion', 'distrito'):
        texto = _normalizar_texto(texto).upper()
        texto = _ANY_LABEL_RE.sub(' ', texto)
        texto = re.sub(r'\s+', ' ', texto).strip(' :-')
        return texto or None
    if campo == 'numero_dni':
        return _extraer_numero_dni(texto)[0]
    if campo == 'codigo_verificador':
        m = re.search(r'\b(\d{1,2})\b', _limpiar_num(texto))
        return m.group(1) if m else None
    return None


def _extraer_por_etiquetas(texto: str) -> dict:
    campos = {}
    lineas = [l.strip() for l in (texto or '').splitlines() if l.strip()]
    for idx, linea in enumerate(lineas):
        up = linea.upper()
        for campo, patrones in _LABELS.items():
            if campos.get(campo) or not any(re.search(p, up, re.I) for p in patrones):
                continue
            candidatos = [linea]
            candidatos.extend(lineas[idx + 1:idx + 4])
            for cand in candidatos:
                if cand != linea and _ANY_LABEL_RE.search(cand.upper()):
                    continue
                valor = _valor_por_campo(campo, cand)
                if valor:
                    campos[campo] = valor
                    break
    numero, dv = _extraer_numero_dni(texto)
    if numero:
        campos['numero_dni'] = numero
    if dv:
        campos['codigo_verificador'] = dv
    return campos


def _extraer_mrz(texto: str) -> dict:
    clean = []
    for linea in (texto or '').splitlines():
        l = re.sub(r'\s+', '', linea.upper())
        l = l.replace('O', '0').replace('|', '1').replace('!', '1')
        if len(l) >= 20 and ('<' in l or re.match(r'[I1][D0]', l)):
            clean.append(l)
    mrz_text = '\n'.join(clean)
    campos = {}
    m = re.search(r'(?:ID|1D)[A-Z<]{3}(\d{8})', mrz_text)
    if m:
        campos['numero_dni'] = m.group(1)
    m = re.search(r'(\d{6})\d?([MF<])(\d{6})', mrz_text)
    if m:
        campos['fecha_nacimiento'] = _fecha_mrz(m.group(1))
        campos['sexo'] = 'MASCULINO' if m.group(2) == 'M' else 'FEMENINO' if m.group(2) == 'F' else None
        campos['fecha_caducidad'] = _fecha_mrz(m.group(3))
    m = re.search(r'([A-ZÁÉÍÓÚÜÑ<]+)<<([A-ZÁÉÍÓÚÜÑ<]+)', mrz_text)
    if m:
        apellidos = [x for x in m.group(1).replace('<', ' ').split() if x]
        nombres = m.group(2).replace('<', ' ')
        if apellidos:
            campos['apellido_paterno'] = apellidos[0]
        if len(apellidos) > 1:
            campos['apellido_materno'] = apellidos[1]
        if nombres:
            campos['nombres'] = _normalizar_nombre(nombres)
    return {k: v for k, v in campos.items() if v}


def _fecha_mrz(raw: str) -> str | None:
    if not re.fullmatch(r'\d{6}', raw or ''):
        return None
    yy = int(raw[:2])
    year = 2000 + yy if yy <= 30 else 1900 + yy
    return _normalizar_fecha(f'{raw[4:6]}/{raw[2:4]}/{year}')


def _merge_preferido(*dicts) -> dict:
    out = _campos_vacios()
    for data in dicts:
        for k, v in (data or {}).items():
            if k.startswith('_'):
                out[k] = v
            elif k in out and not out.get(k) and v:
                out[k] = v
    return out


def _score_campos(campos: dict) -> int:
    pesos = {
        'apellido_paterno': 4, 'apellido_materno': 4, 'nombres': 4,
        'fecha_nacimiento': 3, 'numero_dni': 3, 'sexo': 2, 'ubigeo': 2,
        'fecha_emision': 2, 'fecha_caducidad': 2, 'estado_civil': 2,
        'codigo_verificador': 1, 'direccion': 1, 'distrito': 1,
        'grupo_votacion': 1, 'donacion_organos': 1, 'grupo_sanguineo': 1,
    }
    return sum(p for k, p in pesos.items() if campos.get(k))


def _dni_numero_confiable(campos: dict) -> bool:
    numero = campos.get('numero_dni')
    return bool(numero and re.fullmatch(r'\d{8}', numero))


def _dni_cobertura_rapida(campos: dict, electronico: bool = False) -> bool:
    if not _dni_numero_confiable(campos):
        return False
    claves = (
        'apellido_paterno', 'apellido_materno', 'nombres', 'fecha_nacimiento',
        'sexo', 'estado_civil', 'ubigeo', 'fecha_emision', 'fecha_caducidad',
    )
    presentes = sum(1 for k in claves if campos.get(k))
    if electronico:
        return presentes >= max(3, _OCR_FAST_DNI_KEYS - 1)
    return presentes >= _OCR_FAST_DNI_KEYS


def _dni_necesita_reverso(campos: dict, electronico: bool = False) -> bool:
    if _dni_cobertura_rapida(campos, electronico):
        return False
    if not campos.get('numero_dni'):
        return True
    faltantes_clave = ('apellido_paterno', 'apellido_materno', 'nombres', 'sexo', 'ubigeo')
    return sum(1 for k in faltantes_clave if campos.get(k)) < 3


def _normalizar_campos(campos: dict) -> dict:
    out = _campos_vacios()
    for k in out:
        out[k] = campos.get(k)
    for k in ('apellido_paterno', 'apellido_materno', 'nombres'):
        out[k] = _normalizar_nombre(out[k] or '')
    for k in ('fecha_nacimiento', 'fecha_emision', 'fecha_caducidad'):
        out[k] = _normalizar_fecha(out[k] or '')
    out['sexo'] = _normalizar_sexo(out['sexo'] or '')
    out['estado_civil'] = _normalizar_estado(out['estado_civil'] or '')
    out['ubigeo'] = _normalizar_codigo(out['ubigeo'] or '', 6)
    out['grupo_votacion'] = _normalizar_codigo(out['grupo_votacion'] or '', 6)
    out['cuarto_nivel'] = _normalizar_codigo(out['cuarto_nivel'] or '', 9)
    out['donacion_organos'] = _normalizar_si_no(out['donacion_organos'] or '')
    out['grupo_sanguineo'] = _normalizar_grupo_sanguineo(out['grupo_sanguineo'] or '')
    if out['fecha_emision'] and out['fecha_emision'] == out['fecha_nacimiento']:
        out['fecha_emision'] = None
    if out['fecha_caducidad'] and out['fecha_caducidad'] == out['fecha_nacimiento']:
        out['fecha_caducidad'] = None
    return out


def _parse_paddle_result(result, img_shape):
    palabras = []

    def add_item(bbox, text, conf):
        text = _normalizar_texto(str(text))
        if not text or float(conf or 0) < 0.20:
            return
        xs = [float(p[0]) for p in bbox]
        ys = [float(p[1]) for p in bbox]
        palabras.append({
            'texto': text,
            'x': int(min(xs)), 'y': int(min(ys)),
            'w': max(1, int(max(xs) - min(xs))), 'h': max(1, int(max(ys) - min(ys))),
            'conf': float(conf) * 100,
        })

    if isinstance(result, list):
        pages = result
        if pages and isinstance(pages[0], list) and pages[0] and isinstance(pages[0][0], (list, tuple)):
            if len(pages[0]) == 2 and isinstance(pages[0][1], tuple):
                pages = [pages]
            elif pages and pages[0] and len(pages[0][0]) == 2:
                pages = pages[0]
        for item in pages or []:
            try:
                bbox, rec = item
                text, conf = rec
                add_item(bbox, text, conf)
            except Exception:
                continue
    elif isinstance(result, dict):
        texts = result.get('rec_texts') or result.get('texts') or []
        scores = result.get('rec_scores') or result.get('scores') or [1.0] * len(texts)
        boxes = result.get('dt_polys') or result.get('rec_polys') or result.get('boxes') or []
        for bbox, text, conf in zip(boxes, texts, scores):
            add_item(bbox, text, conf)
    return palabras


def _ocr_paddle_palabras(img_bgr):
    model = _get_paddle()
    if model is None:
        raise RuntimeError(_paddle_error or 'paddleocr no esta instalado')
    img = _preprocesar_ocr(img_bgr)
    try:
        result = model.ocr(img)
    except AttributeError:
        result = model.predict(img)
    return _parse_paddle_result(result, img.shape)


def _ocr_doctr_palabras(img_bgr):
    model = _get_doctr()
    if model is None:
        raise RuntimeError(_doctr_error or 'python-doctr no esta instalado')
    from doctr.io import DocumentFile  # noqa: PLC0415
    h, w = img_bgr.shape[:2]
    ok, buf = cv2.imencode('.jpg', img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError('No se pudo codificar la imagen para doctr')
    result = model(DocumentFile.from_images([buf.tobytes()]))
    palabras = []
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    texto = _normalizar_texto(word.value)
                    conf = float(getattr(word, 'confidence', 1.0))
                    if not texto or conf < 0.25:
                        continue
                    (x1n, y1n), (x2n, y2n) = word.geometry
                    palabras.append({
                        'texto': texto,
                        'x': int(x1n * w), 'y': int(y1n * h),
                        'w': max(1, int((x2n - x1n) * w)),
                        'h': max(1, int((y2n - y1n) * h)),
                        'conf': conf * 100,
                    })
    return palabras


def _campos_desde_lectura(palabras_frente, img_frente, palabras_reverso=None, img_reverso=None,
                          electronico=True) -> dict:
    texto_frente = _texto_completo(palabras_frente)
    texto_reverso = _texto_completo(palabras_reverso or [])
    por_texto = _merge_preferido(
        _extraer_por_etiquetas(texto_frente),
        _extraer_por_etiquetas(texto_reverso),
        # _extraer_mrz('\n'.join((texto_reverso, texto_frente))),
    )
    por_roi = {}
    if electronico:
        for campo, coords in _COORDS_FRENTE_ELECTRONICO.items():
            valor = _valor_por_campo(campo, _palabras_en_roi(palabras_frente, coords, img_frente.shape))
            if valor:
                por_roi[campo] = valor
        if img_reverso is not None:
            for campo, coords in _COORDS_REVERSO_ELECTRONICO.items():
                valor = _valor_por_campo(campo, _palabras_en_roi(palabras_reverso or [], coords, img_reverso.shape))
                if valor:
                    por_roi[campo] = valor
    campos = _merge_preferido(por_roi, por_texto)
    if not campos.get('numero_dni'):
        numero, dv = _extraer_numero_dni('\n'.join((texto_frente, texto_reverso)))
        campos['numero_dni'] = numero
        campos['codigo_verificador'] = campos.get('codigo_verificador') or dv
    return _normalizar_campos(campos)


def _ocr_crop_fallback(campos, img_frente, img_reverso=None):
    faltantes = [
        k for k in ('apellido_paterno', 'apellido_materno', 'nombres', 'fecha_nacimiento', 'sexo',
                    'fecha_emision', 'fecha_caducidad', 'numero_dni')
        if not campos.get(k) and k in _COORDS_FRENTE_ELECTRONICO
    ]
    for campo in faltantes[:5]:
        try:
            palabras = _ocr_paddle_palabras(_recortar(img_frente, _COORDS_FRENTE_ELECTRONICO[campo]))
            valor = _valor_por_campo(campo, _texto_completo(palabras))
            if valor:
                campos[campo] = valor
        except Exception:
            continue
    if img_reverso is not None and (not campos.get('direccion') or not campos.get('distrito')):
        for campo in ('direccion', 'distrito'):
            if campos.get(campo):
                continue
            try:
                palabras = _ocr_paddle_palabras(_recortar(img_reverso, _COORDS_REVERSO_ELECTRONICO[campo]))
                valor = _valor_por_campo(campo, _texto_completo(palabras))
                if valor:
                    campos[campo] = valor
            except Exception:
                continue
    return _normalizar_campos(campos)


def _consultar_reniec(numero_dni: str) -> dict | None:
    if os.getenv('OCR_RENIEC_ENABLED', '0') == '0':
        return None
    try:
        r = _requests.get(_RENIEC_URL, params={'numero': numero_dni, 'token': _RENIEC_TOKEN}, timeout=2.5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _aplicar_reniec(campos: dict, reniec: dict) -> None:
    if not reniec:
        return
    if reniec.get('apellidoPaterno'):
        campos['apellido_paterno'] = reniec['apellidoPaterno']
    if reniec.get('apellidoMaterno'):
        campos['apellido_materno'] = reniec['apellidoMaterno']
    if reniec.get('nombres'):
        campos['nombres'] = reniec['nombres']
    if not campos.get('codigo_verificador') and reniec.get('digitoVerificador') is not None:
        campos['codigo_verificador'] = str(reniec['digitoVerificador'])


def _meta_validacion(campos):
    numero = campos.get('numero_dni')
    dv = campos.get('codigo_verificador')
    calc = _calcular_digito_verificador(numero) if numero else None
    return {
        'numero_dni_valido': bool(numero and re.fullmatch(r'\d{8}', numero) and (not dv or _validar_digito_verificador(numero, dv))),
        'digito_verificador_calc': calc['numerico'] if calc else None,
        'digito_verificador_alpha': calc['alfabetico'] if calc else None,
    }


def _tiempo_restante(t0: float) -> float:
    return _OCR_MAX_SECONDS - (perf_counter() - t0)


def _procesar_dni(frente_bytes: bytes, reverso_bytes: bytes | None = None, electronico: bool = False) -> dict:
    t0 = perf_counter()
    img_frente = _preparar_documento(frente_bytes)
    img_reverso = None
    palabras_reverso = []
    campos_paddle = _campos_vacios()
    campos_paddle['_engine_info'] = 'omitido: doctr es el motor principal rapido'
    campos_doctr = _campos_vacios()
    doctr_usado = True

    try:
        palabras_frente = _ocr_doctr_palabras(img_frente)
        campos_doctr = _campos_desde_lectura(palabras_frente, img_frente, [], None, electronico)
    except Exception as exc:
        palabras_frente = []
        campos_doctr['_engine_error'] = str(exc)[:160]

    if reverso_bytes and _dni_necesita_reverso(campos_doctr, electronico) and _tiempo_restante(t0) > 3:
        img_reverso = _preparar_documento(reverso_bytes)
        try:
            palabras_reverso = _ocr_doctr_palabras(img_reverso)
            campos_doctr = _campos_desde_lectura(palabras_frente, img_frente, palabras_reverso, img_reverso, electronico)
        except Exception as exc:
            campos_doctr['_engine_error'] = str(exc)[:160]

    if (
        _OCR_USE_PADDLE_FALLBACK
        and not _dni_cobertura_rapida(campos_doctr, electronico)
        and _score_campos(campos_doctr) < _OCR_MIN_SCORE_FAST
        and _tiempo_restante(t0) > 4
    ):
        try:
            palabras_paddle_f = _ocr_paddle_palabras(img_frente)
            campos_paddle = _campos_desde_lectura(palabras_paddle_f, img_frente, [], None, electronico)
        except Exception as exc:
            campos_paddle['_engine_error'] = str(exc)[:160]

    campos_votados = _merge_preferido(campos_doctr, campos_paddle)
    reniec_data = None
    numero = campos_votados.get('numero_dni')
    if os.getenv('OCR_RENIEC_ENABLED', '0') == '1' and numero and re.fullmatch(r'\d{8}', numero) and _tiempo_restante(t0) > 3:
        reniec_data = _consultar_reniec(numero)
        for c in (campos_paddle, campos_doctr, campos_votados):
            _aplicar_reniec(c, reniec_data)

    meta = _meta_validacion(campos_votados)
    if meta['digito_verificador_calc'] and not campos_votados.get('codigo_verificador'):
        for c in (campos_paddle, campos_doctr, campos_votados):
            c['codigo_verificador'] = meta['digito_verificador_calc']
        meta = _meta_validacion(campos_votados)

    for c in (campos_paddle, campos_doctr, campos_votados):
        c.update(meta)

    return {
        'tipo_documento': 'DNI_ELECTRONICO' if electronico else 'DNI',
        'votado': campos_votados,
        'paddleocr': campos_paddle,
        'doctr': campos_doctr,
        'reniec': reniec_data,
        'texto_raw': '\n'.join(filter(None, [_texto_completo(palabras_frente), _texto_completo(palabras_reverso)])),
        'meta': {
            'elapsed_seconds': round(perf_counter() - t0, 2),
            'doctr_usado': doctr_usado,
            'score_paddle': _score_campos(campos_paddle),
            'score_doctr': _score_campos(campos_doctr),
            'motor_principal': 'doctr',
            'limite_segundos': _OCR_MAX_SECONDS,
        },
    }


def _procesar_carnet(imagen_bytes: bytes) -> dict:
    img = Image.open(io.BytesIO(imagen_bytes)).convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    arr = cv2.cvtColor(np.array(img.convert('RGB')), cv2.COLOR_RGB2BGR)
    palabras = _ocr_doctr_palabras(_preparar_documento(cv2.imencode('.jpg', arr)[1].tobytes()))
    texto = _texto_completo(palabras)
    return {'tipo_documento': 'CARNET_EXTRANJERIA', 'campos': _extraer_por_etiquetas(texto), 'texto_raw': texto}


def detectar(imagen_bytes: bytes, tipo_documento: str, reverso_bytes: bytes | None = None) -> dict:
    if not OCR_DISPONIBLE:
        raise RuntimeError(f'OCR no disponible. Instala las dependencias del proyecto: {_IMPORT_ERROR}')
    acquired = _OCR_REQUEST_SEMAPHORE.acquire(timeout=int(os.getenv('OCR_QUEUE_TIMEOUT', '10')))
    if not acquired:
        raise RuntimeError('El servicio OCR esta ocupado. Intenta nuevamente en unos minutos.')
    try:
        if tipo_documento == 'DNI_ELECTRONICO':
            return _procesar_dni(imagen_bytes, reverso_bytes, electronico=True)
        if tipo_documento == 'DNI':
            return _procesar_dni(imagen_bytes, reverso_bytes, electronico=False)
        return _procesar_carnet(imagen_bytes)
    finally:
        _OCR_REQUEST_SEMAPHORE.release()

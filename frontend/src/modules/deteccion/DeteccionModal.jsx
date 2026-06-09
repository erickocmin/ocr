import { useState, useEffect, useRef } from 'react';
import { Modal } from '../../components/Modal';

const TOKEN_KEY = 'deteccion_ocr_token';

const LABELS_DNI = {
  numero_dni:         'N° DNI',
  codigo_verificador: 'Cód. Verificador',
  apellido_paterno:   'Apellido Paterno',
  apellido_materno:   'Apellido Materno',
  nombres:            'Nombre(s)',
  fecha_nacimiento:   'Fecha de Nacimiento',
  sexo:               'Sexo',
  estado_civil:       'Estado Civil',
  ubigeo:             'Ubigeo',
  fecha_emision:      'Fecha de Emisión',
  fecha_caducidad:    'Fecha de Caducidad',
};

const LABELS_DNI_ELECTRONICO = {
  ...LABELS_DNI,
  direccion:        'Dirección',
  distrito:         'Departamento/Provincia/Distrito',
  cuarto_nivel:     'Cuarto Nivel',
  grupo_votacion:   'Grupo de Votación',
  donacion_organos: 'Donación de Órganos',
  grupo_sanguineo:  'Grupo Sanguíneo',
};

const INITIAL_LOGIN = { username: '', password: '' };

const MOTORES = [
  { key: 'votado',    label: 'Votado',    color: '#1a4fa0', descripcion: 'Consenso de los motores' },
  { key: 'tesseract', label: 'Tesseract', color: '#555',    descripcion: null },
  { key: 'easyocr',   label: 'EasyOCR',  color: '#1a7a4a', descripcion: null },
  { key: 'doctr',     label: 'doctr',    color: '#8b1fa0', descripcion: null },
];

// Fases de progreso con duración estimada acumulada en segundos
const FASES_PROGRESO = [
  { hasta: 5,   pct: 5,  label: 'Subiendo y decodificando imágenes...' },
  { hasta: 18,  pct: 20, label: 'OCR base con Tesseract...' },
  { hasta: 45,  pct: 55, label: 'Motores de IA en paralelo (EasyOCR + doctr)...' },
  { hasta: 65,  pct: 80, label: 'Extracción campo a campo y coherencia...' },
  { hasta: 80,  pct: 92, label: 'Combinando resultados y validando...' },
  { hasta: Infinity, pct: 97, label: 'Finalizando detección...' },
];

function getFase(elapsed) {
  return FASES_PROGRESO.find((f) => elapsed < f.hasta) ?? FASES_PROGRESO[FASES_PROGRESO.length - 1];
}

function getStoredToken() {
  return sessionStorage.getItem(TOKEN_KEY) || '';
}

function thStyle(color, width) {
  return {
    textAlign: 'left', padding: '6px 10px', color, fontWeight: 600,
    width, fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.04em',
  };
}
function cellStyle(val) {
  return { padding: '7px 10px', color: val ? 'inherit' : '#bbb', fontSize: '0.85rem' };
}

/** Comprime y redimensiona una imagen usando Canvas API antes de subirla. */
async function comprimirImagen(file, maxWidth = 1800, quality = 0.88) {
  // Si ya es pequeña y es JPEG/WebP, no recomprimir
  if (file.size < 800_000 && (file.type === 'image/jpeg' || file.type === 'image/webp')) {
    return file;
  }
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      let { width, height } = img;
      if (width > maxWidth) {
        height = Math.round(height * maxWidth / width);
        width = maxWidth;
      }
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      canvas.getContext('2d').drawImage(img, 0, 0, width, height);
      canvas.toBlob(
        (blob) => {
          if (!blob) { resolve(file); return; }
          resolve(new File([blob], file.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg' }));
        },
        'image/jpeg',
        quality,
      );
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
    img.src = url;
  });
}

function LoaderDeteccion({ elapsed }) {
  const fase = getFase(elapsed);
  // Interpolar % dentro de la fase actual
  const idx = FASES_PROGRESO.indexOf(fase);
  const prev = FASES_PROGRESO[idx - 1];
  const pctInicio = prev?.pct ?? 0;
  const durInicio = prev?.hasta ?? 0;
  const progreso = idx === FASES_PROGRESO.length - 1
    ? fase.pct
    : pctInicio + (fase.pct - pctInicio) * Math.min(1, (elapsed - durInicio) / (fase.hasta - durInicio));

  return (
    <div style={{ textAlign: 'center', padding: '36px 20px 28px' }}>
      {/* Spinner */}
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '20px' }}>
        <div style={{
          width: '44px', height: '44px', borderRadius: '50%',
          border: '4px solid #e0e7ff', borderTopColor: '#1a4fa0',
          animation: 'spin 0.9s linear infinite',
        }} />
      </div>

      <p style={{ margin: '0 0 16px', fontWeight: 600, color: '#1a4fa0', fontSize: '1rem' }}>
        Detectando documento...
      </p>
      <p style={{ margin: '0 0 14px', color: '#555', fontSize: '0.88rem' }}>
        {fase.label}
      </p>

      {/* Barra de progreso */}
      <div style={{ background: '#e0e7ff', borderRadius: '8px', height: '8px', maxWidth: '420px', margin: '0 auto 10px' }}>
        <div style={{
          background: '#1a4fa0', height: '100%', borderRadius: '8px',
          width: `${progreso.toFixed(1)}%`, transition: 'width 1s ease-out',
        }} />
      </div>

      <p style={{ margin: 0, color: '#999', fontSize: '0.79rem' }}>
        {elapsed}s transcurridos · estimado: ~60–80s
      </p>
    </div>
  );
}

export function DeteccionModal({ isOpen, onClose, onApply }) {
  const [tipoDoc, setTipoDoc]     = useState('DNI');
  const [token, setToken]         = useState(getStoredToken);
  const [loginForm, setLoginForm] = useState(INITIAL_LOGIN);
  const [imagenFrente, setImagenFrente] = useState(null);
  const [imagenReverso, setImagenReverso] = useState(null);
  const [previewFrente, setPreviewFrente] = useState(null);
  const [previewReverso, setPreviewReverso] = useState(null);
  const [loading, setLoading]     = useState(false);
  const [elapsed, setElapsed]     = useState(0);
  const [error, setError]         = useState('');
  const [resultado, setResultado] = useState(null);
  const timerRef = useRef(null);

  // Gestionar el intervalo del contador según el estado de carga
  useEffect(() => {
    if (!loading) {
      clearInterval(timerRef.current);
      return;
    }
    timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(timerRef.current);
  }, [loading]);

  // Prevenir recarga/cierre de pestaña mientras detecta
  useEffect(() => {
    if (!loading) return;
    const handler = (e) => {
      e.preventDefault();
      e.returnValue = 'La detección está en curso. ¿Deseas salir igualmente?';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [loading]);

  // Añadir animación del spinner al <head> una sola vez
  useEffect(() => {
    if (document.getElementById('spin-style')) return;
    const style = document.createElement('style');
    style.id = 'spin-style';
    style.textContent = '@keyframes spin { to { transform: rotate(360deg); } }';
    document.head.appendChild(style);
  }, []);

  function reset() {
    setTipoDoc('DNI');
    setLoginForm(INITIAL_LOGIN);
    setImagenFrente(null);
    setImagenReverso(null);
    setPreviewFrente(null);
    setPreviewReverso(null);
    setLoading(false);
    setElapsed(0);
    setError('');
    setResultado(null);
  }

  function handleClose() {
    if (loading) return; // bloquear cierre durante detección
    reset();
    onClose();
  }

  function handleCerrarSesion() {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken('');
    setError('');
  }

  function handleImageChange(e, lado) {
    if (loading) return;
    const file = e.target.files[0] || null;
    if (lado === 'frente') {
      setImagenFrente(file);
      setPreviewFrente(file ? URL.createObjectURL(file) : null);
    } else {
      setImagenReverso(file);
      setPreviewReverso(file ? URL.createObjectURL(file) : null);
    }
    setError('');
  }

  async function handleLogin() {
    if (!loginForm.username || !loginForm.password) {
      setError('Ingresa usuario y contraseña.');
      return;
    }
    setElapsed(0);
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/deteccion/login/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(loginForm),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || data.detail || 'Credenciales incorrectas.');
      sessionStorage.setItem(TOKEN_KEY, data.token);
      setToken(data.token);
      setLoginForm(INITIAL_LOGIN);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDetectar() {
    if (!imagenFrente || !imagenReverso) {
      setError('Selecciona la imagen frontal y posterior del documento.');
      return;
    }

    setElapsed(0);
    setLoading(true);
    setError('');

    try {
      // Comprimir imágenes antes de enviar
      const [frenteOpt, reversoOpt] = await Promise.all([
        comprimirImagen(imagenFrente),
        comprimirImagen(imagenReverso),
      ]);

      const formData = new FormData();
      formData.append('imagen_frente', frenteOpt);
      formData.append('imagen_reverso', reversoOpt);
      formData.append('tipo_documento', tipoDoc);

      const res = await fetch('/api/deteccion/detectar/', {
        method: 'POST',
        headers: { Authorization: `Token ${token}` },
        body: formData,
      });

      if (res.status === 401) {
        sessionStorage.removeItem(TOKEN_KEY);
        setToken('');
        throw new Error('Sesión expirada. Por favor inicia sesión de nuevo.');
      }

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || data.detail || 'Error al detectar.');
      setResultado(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function handleUsarDatos(motor) {
    if (!resultado) return;
    const c = resultado[motor] || resultado.votado || {};
    const socioData = {};
    socioData.nombre   = c.nombres          || '';
    const ap           = c.apellido_paterno || '';
    const am           = c.apellido_materno || '';
    socioData.apellido = [ap, am].filter(Boolean).join(' ');
    onApply(socioData);
    handleClose();
  }

  const hasToken = !!token;
  const labelsResultado = tipoDoc === 'DNI_ELECTRONICO' ? LABELS_DNI_ELECTRONICO : LABELS_DNI;

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title="Detección OCR de Documento"
      size="lg"
      closeOnOverlay={false}
    >
      {/* ── Loader durante detección ── */}
      {loading && !resultado && (
        <LoaderDeteccion elapsed={elapsed} />
      )}

      {/* ── Formulario ── */}
      {!loading && !resultado && (
        <div className="form form-2col">

          {/* Tipo de documento */}
          <div className="form-group form-full">
            <label className="form-label">Tipo de documento</label>
            <div style={{ display: 'flex', gap: '24px', marginTop: '6px' }}>
              {[
                { value: 'DNI', label: 'DNI azul' },
                { value: 'DNI_ELECTRONICO', label: 'DNI electrónico' },
              ].map((t) => (
                <label key={t.value} style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.5 : 1 }}>
                  <input
                    type="radio"
                    name="tipo_documento"
                    value={t.value}
                    checked={tipoDoc === t.value}
                    disabled={loading}
                    onChange={() => { if (!loading) { setTipoDoc(t.value); setResultado(null); } }}
                  />
                  {t.label}
                </label>
              ))}
            </div>
          </div>

          {/* Sesión */}
          <div className="form-group form-full">
            {hasToken ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 14px', background: 'var(--success-bg, #eafaf1)', border: '1px solid var(--success-border, #a9dfbf)', borderRadius: '6px' }}>
                <span style={{ color: 'var(--success, #1e8449)', fontSize: '0.88rem', fontWeight: 600 }}>Sesión activa</span>
                <span style={{ color: 'var(--text-muted, #999)', fontSize: '0.8rem' }}>— guardada hasta cerrar el navegador</span>
                <button type="button" className="link-btn" style={{ fontSize: '0.8rem', marginLeft: 'auto', color: 'var(--text-muted, #888)' }} onClick={handleCerrarSesion} disabled={loading}>
                  Cerrar sesión
                </button>
              </div>
            ) : (
              <div>
                <label className="form-label">Iniciar sesión (administradores)</label>
                <div style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', background: 'var(--bg-muted, #f8f8f8)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <input className="form-control" value={loginForm.username} onChange={(e) => setLoginForm((f) => ({ ...f, username: e.target.value }))} placeholder="Usuario administrador" autoComplete="username" disabled={loading} />
                  <input className="form-control" type="password" value={loginForm.password} onChange={(e) => setLoginForm((f) => ({ ...f, password: e.target.value }))} placeholder="Contraseña" autoComplete="current-password" onKeyDown={(e) => e.key === 'Enter' && handleLogin()} disabled={loading} />
                  <button type="button" className="btn btn-sm btn-primary" onClick={handleLogin} disabled={loading} style={{ alignSelf: 'flex-start' }}>
                    {loading ? 'Autenticando...' : 'Iniciar sesión'}
                  </button>
                </div>
                <span className="field-hint" style={{ display: 'block', marginTop: '4px' }}>La sesión se guarda automáticamente hasta que cierres el navegador.</span>
              </div>
            )}
          </div>

          {/* Imágenes */}
          {hasToken && (
            <>
              <div className="form-group">
                <label className="form-label">Cara frontal</label>
                <input
                  className="form-control"
                  type="file"
                  accept="image/jpeg,image/png,image/webp,image/bmp,image/tiff"
                  disabled={loading}
                  onChange={(e) => handleImageChange(e, 'frente')}
                />
                <span className="field-hint">Se comprime automáticamente. Máx 10 MB.</span>
                {previewFrente && (
                  <img src={previewFrente} alt="Vista previa frontal" style={{ marginTop: '10px', width: '100%', maxHeight: '180px', borderRadius: '6px', border: '1px solid var(--border)', objectFit: 'contain' }} />
                )}
              </div>
              <div className="form-group">
                <label className="form-label">Cara posterior</label>
                <input
                  className="form-control"
                  type="file"
                  accept="image/jpeg,image/png,image/webp,image/bmp,image/tiff"
                  disabled={loading}
                  onChange={(e) => handleImageChange(e, 'reverso')}
                />
                <span className="field-hint">Incluye la zona MRZ/código posterior.</span>
                {previewReverso && (
                  <img src={previewReverso} alt="Vista previa posterior" style={{ marginTop: '10px', width: '100%', maxHeight: '180px', borderRadius: '6px', border: '1px solid var(--border)', objectFit: 'contain' }} />
                )}
              </div>
            </>
          )}

          {error && (
            <div className="form-full" style={{ color: 'var(--danger, #c0392b)', fontSize: '0.88rem', padding: '8px 12px', background: 'var(--danger-bg, #fdecea)', borderRadius: '6px', border: '1px solid var(--danger-border, #f5c6cb)' }}>
              {error}
            </div>
          )}

          <div className="form-actions form-full">
            <button type="button" className="btn btn-ghost" onClick={handleClose} disabled={loading}>Cancelar</button>
            <button type="button" className="btn btn-primary" onClick={handleDetectar} disabled={loading || !imagenFrente || !imagenReverso || !hasToken}>
              Detectar documento
            </button>
          </div>
        </div>
      )}

      {/* ── Resultados ── */}
      {!loading && resultado && (
        <div>
          <p style={{ margin: '0 0 12px', color: 'var(--text-muted, #666)', fontSize: '0.83rem' }}>
            Compara los motores y usa los datos del que mejor detectó.
          </p>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border, #e0e0e0)' }}>
                  <th style={thStyle('#888', '16%')}>Campo</th>
                  {MOTORES.map((m) => {
                    const engineError = resultado[m.key]?._engine_error || null;
                    const esVotado = m.key === 'votado';
                    return (
                      <th key={m.key} style={{ ...thStyle(m.color, '21%'), position: 'relative', background: esVotado ? '#f0f4ff' : 'transparent', borderLeft: esVotado ? `2px solid ${m.color}` : undefined }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
                          <div>
                            <span>{m.label}</span>
                            {m.descripcion && (
                              <div style={{ fontSize: '0.62rem', color: m.color, fontWeight: 400, textTransform: 'none', marginTop: '1px', opacity: 0.8 }}>{m.descripcion}</div>
                            )}
                            {engineError && (
                              <div style={{ fontSize: '0.62rem', color: '#999', fontWeight: 400, textTransform: 'none', marginTop: '2px' }}>No disponible</div>
                            )}
                          </div>
                          {!engineError && (
                            <button type="button" onClick={() => handleUsarDatos(m.key)} style={{ fontSize: '0.7rem', padding: '2px 8px', border: `1px solid ${m.color}`, borderRadius: '10px', background: esVotado ? m.color : 'transparent', color: esVotado ? '#fff' : m.color, cursor: 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}>
                              Usar
                            </button>
                          )}
                        </div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {Object.entries(labelsResultado).map(([key, label]) => (
                  <tr key={key} style={{ borderBottom: '1px solid var(--border, #eee)' }}>
                    <td style={{ padding: '7px 10px', color: '#888', whiteSpace: 'nowrap', fontSize: '0.82rem' }}>{label}</td>
                    {MOTORES.map((m) => {
                      const engineError = resultado[m.key]?._engine_error || null;
                      const v = engineError ? null : (resultado[m.key]?.[key] || null);
                      const esVotado = m.key === 'votado';
                      return (
                        <td key={m.key} style={{ ...cellStyle(v), color: engineError ? '#ddd' : cellStyle(v).color, background: esVotado ? '#f0f4ff' : 'transparent', borderLeft: esVotado ? '2px solid #1a4fa0' : undefined, fontWeight: esVotado && v ? 600 : undefined }}>
                          {engineError ? '—' : (v || 'No detectado')}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {error && (
            <div style={{ color: 'var(--danger, #c0392b)', fontSize: '0.88rem', marginTop: '12px' }}>{error}</div>
          )}

          <div className="form-actions" style={{ marginTop: '20px' }}>
            <button type="button" className="btn btn-ghost" onClick={() => { setResultado(null); setError(''); }}>
              Detectar otra imagen
            </button>
            <button type="button" className="btn btn-ghost" onClick={handleClose}>
              Cerrar
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

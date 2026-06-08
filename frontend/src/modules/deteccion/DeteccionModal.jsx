import { useState } from 'react';
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

const LABELS_CARNET = {
  numero_carnet:    'N° Carnet',
  apellidos:        'Apellidos',
  nombre:           'Nombre(s)',
  nacionalidad:     'Nacionalidad',
  fecha_nacimiento: 'Fecha de Nacimiento',
  sexo:             'Sexo',
};

// RENIEC_MAP — deshabilitado en UI por ahora, preservado para implementación futura
const RENIEC_MAP = {
  apellido_paterno:   (r) => r?.apellidoPaterno   || null,
  apellido_materno:   (r) => r?.apellidoMaterno   || null,
  nombres:            (r) => r?.nombres            || null,
  codigo_verificador: (r) => r?.digitoVerificador != null ? String(r.digitoVerificador) : null,
};

const INITIAL_LOGIN = { username: '', password: '' };

const MOTORES = [
  { key: 'tesseract', label: 'Tesseract',  color: '#555' },
  { key: 'easyocr',   label: 'EasyOCR',   color: '#1a7a4a' },
  { key: 'paddleocr', label: 'PaddleOCR', color: '#8b1fa0' },
];

function getStoredToken() {
  return sessionStorage.getItem(TOKEN_KEY) || '';
}

function thStyle(color, width) {
  return {
    textAlign: 'left',
    padding: '6px 10px',
    color,
    fontWeight: 600,
    width,
    fontSize: '0.78rem',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  };
}

function cellStyle(val) {
  return {
    padding: '7px 10px',
    color: val ? 'inherit' : '#bbb',
    fontSize: '0.85rem',
  };
}

export function DeteccionModal({ isOpen, onClose, onApply }) {
  const [tipoDoc, setTipoDoc]     = useState('DNI');
  const [token, setToken]         = useState(getStoredToken);
  const [loginForm, setLoginForm] = useState(INITIAL_LOGIN);
  const [imagen, setImagen]       = useState(null);
  const [preview, setPreview]     = useState(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState('');
  const [resultado, setResultado] = useState(null);

  function reset() {
    setTipoDoc('DNI');
    setLoginForm(INITIAL_LOGIN);
    setImagen(null);
    setPreview(null);
    setLoading(false);
    setError('');
    setResultado(null);
    // token no se resetea — persiste entre usos del modal
  }

  function handleClose() {
    reset();
    onClose();
  }

  function handleCerrarSesion() {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken('');
    setError('');
  }

  function handleImageChange(e) {
    const file = e.target.files[0] || null;
    setImagen(file);
    setPreview(file ? URL.createObjectURL(file) : null);
    setError('');
  }

  async function handleLogin() {
    if (!loginForm.username || !loginForm.password) {
      setError('Ingresa usuario y contraseña.');
      return;
    }
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
    if (!imagen) { setError('Selecciona una imagen del documento.'); return; }

    setLoading(true);
    setError('');
    const formData = new FormData();
    formData.append('imagen', imagen);
    formData.append('tipo_documento', tipoDoc);

    try {
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

  // motor: 'tesseract' | 'easyocr' | 'paddleocr'  (DNI)
  // motor: null  (Carnet — usa resultado.campos)
  function handleUsarDatos(motor) {
    if (!resultado) return;
    const c = motor ? (resultado[motor] || {}) : (resultado.campos || {});
    const socioData = {};

    if (tipoDoc === 'DNI') {
      socioData.nombre   = c.nombres          || '';
      const ap           = c.apellido_paterno || '';
      const am           = c.apellido_materno || '';
      socioData.apellido = [ap, am].filter(Boolean).join(' ');
    } else {
      if (c.nombre)    socioData.nombre   = c.nombre;
      if (c.apellidos) socioData.apellido = c.apellidos;
    }

    onApply(socioData);
    handleClose();
  }

  const hasToken = !!token;

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Detección OCR de Documento" size="lg">
      {!resultado ? (
        <div className="form form-2col">

          {/* Tipo de documento */}
          <div className="form-group form-full">
            <label className="form-label">Tipo de documento</label>
            <div style={{ display: 'flex', gap: '24px', marginTop: '6px' }}>
              {[
                { value: 'DNI',               label: 'DNI Nacional' },
                { value: 'CARNET_EXTRANJERIA', label: 'Carnet de Extranjería' },
              ].map((t) => (
                <label key={t.value} style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="tipo_documento"
                    value={t.value}
                    checked={tipoDoc === t.value}
                    onChange={() => { setTipoDoc(t.value); setResultado(null); }}
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
                <span style={{ color: 'var(--success, #1e8449)', fontSize: '0.88rem', fontWeight: 600 }}>
                  Sesión activa
                </span>
                <span style={{ color: 'var(--text-muted, #999)', fontSize: '0.8rem' }}>
                  — guardada hasta cerrar el navegador
                </span>
                <button
                  type="button"
                  className="link-btn"
                  style={{ fontSize: '0.8rem', marginLeft: 'auto', color: 'var(--text-muted, #888)' }}
                  onClick={handleCerrarSesion}
                >
                  Cerrar sesión
                </button>
              </div>
            ) : (
              <div>
                <label className="form-label">Iniciar sesión (administradores)</label>
                <div style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', background: 'var(--bg-muted, #f8f8f8)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <input
                    className="form-control"
                    value={loginForm.username}
                    onChange={(e) => setLoginForm((f) => ({ ...f, username: e.target.value }))}
                    placeholder="Usuario administrador"
                    autoComplete="username"
                  />
                  <input
                    className="form-control"
                    type="password"
                    value={loginForm.password}
                    onChange={(e) => setLoginForm((f) => ({ ...f, password: e.target.value }))}
                    placeholder="Contraseña"
                    autoComplete="current-password"
                    onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                  />
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    onClick={handleLogin}
                    disabled={loading}
                    style={{ alignSelf: 'flex-start' }}
                  >
                    {loading ? 'Autenticando...' : 'Iniciar sesión'}
                  </button>
                </div>
                <span className="field-hint" style={{ display: 'block', marginTop: '4px' }}>
                  La sesión se guarda automáticamente hasta que cierres el navegador.
                </span>
              </div>
            )}
          </div>

          {/* Imagen — solo si hay sesión activa */}
          {hasToken && (
            <div className="form-group form-full">
              <label className="form-label">Imagen del documento</label>
              <input
                className="form-control"
                type="file"
                accept="image/jpeg,image/png,image/webp,image/bmp,image/tiff"
                onChange={handleImageChange}
              />
              <span className="field-hint">Foto clara y sin reflejos. Máx 10 MB.</span>
              {preview && (
                <img
                  src={preview}
                  alt="Vista previa del documento"
                  style={{ marginTop: '10px', maxHeight: '180px', borderRadius: '6px', border: '1px solid var(--border)', objectFit: 'contain' }}
                />
              )}
            </div>
          )}

          {error && (
            <div className="form-full" style={{ color: 'var(--danger, #c0392b)', fontSize: '0.88rem', padding: '8px 12px', background: 'var(--danger-bg, #fdecea)', borderRadius: '6px', border: '1px solid var(--danger-border, #f5c6cb)' }}>
              {error}
            </div>
          )}

          <div className="form-actions form-full">
            <button type="button" className="btn btn-ghost" onClick={handleClose}>Cancelar</button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleDetectar}
              disabled={loading || !imagen || !hasToken}
            >
              {loading ? 'Detectando...' : 'Detectar documento'}
            </button>
          </div>
        </div>
      ) : (
        /* Resultados */
        <div>
          {tipoDoc === 'DNI' ? (
            /* DNI — 3 columnas: Tesseract | EasyOCR | PaddleOCR */
            <>
              <p style={{ margin: '0 0 12px', color: 'var(--text-muted, #666)', fontSize: '0.83rem' }}>
                Compara los 3 motores y usa los datos del que mejor detectó.
              </p>

              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--border, #e0e0e0)' }}>
                      <th style={thStyle('#888', '18%')}>Campo</th>
                      {MOTORES.map((m) => {
                        const engineError = resultado[m.key]?._engine_error || null;
                        return (
                          <th key={m.key} style={{ ...thStyle(m.color, '27%'), position: 'relative' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
                              <div>
                                <span>{m.label}</span>
                                {engineError && (
                                  <div style={{ fontSize: '0.62rem', color: '#999', fontWeight: 400, textTransform: 'none', marginTop: '2px' }}>
                                    No disponible en este sistema
                                  </div>
                                )}
                              </div>
                              {!engineError && (
                                <button
                                  type="button"
                                  onClick={() => handleUsarDatos(m.key)}
                                  style={{
                                    fontSize: '0.7rem',
                                    padding: '2px 8px',
                                    border: `1px solid ${m.color}`,
                                    borderRadius: '10px',
                                    background: 'transparent',
                                    color: m.color,
                                    cursor: 'pointer',
                                    fontWeight: 600,
                                    whiteSpace: 'nowrap',
                                  }}
                                >
                                  Usar
                                </button>
                              )}
                            </div>
                          </th>
                        );
                      })}
                      {/* Columna RENIEC deshabilitada — preservada para uso futuro
                      <th style={thStyle('#1a6fa0', '0%')}>
                        RENIEC
                        {resultado.reniec && (
                          <span style={{ fontSize: '0.68rem', marginLeft: '6px', padding: '1px 7px', borderRadius: '10px', background: '#e8f4fd', color: '#1a6fa0', border: '1px solid #b3d9f5', fontWeight: 400 }}>
                            verificado
                          </span>
                        )}
                      </th>
                      */}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(LABELS_DNI).map(([key, label]) => {
                      // const reniecVal = RENIEC_MAP[key]?.(resultado.reniec) || null;  // deshabilitado
                      return (
                        <tr key={key} style={{ borderBottom: '1px solid var(--border, #eee)' }}>
                          <td style={{ padding: '7px 10px', color: '#888', whiteSpace: 'nowrap', fontSize: '0.82rem' }}>
                            {label}
                          </td>
                          {MOTORES.map((m) => {
                            const engineError = resultado[m.key]?._engine_error || null;
                            const v = engineError ? null : (resultado[m.key]?.[key] || null);
                            return (
                              <td key={m.key} style={{ ...cellStyle(v), color: engineError ? '#ddd' : cellStyle(v).color }}>
                                {engineError ? '—' : (v || 'No detectado')}
                              </td>
                            );
                          })}
                          {/* Celda RENIEC deshabilitada — preservada para uso futuro
                          <td style={{ display: 'none', ...cellStyle(reniecVal) }}>
                            {reniecVal || (resultado.reniec ? '—' : 'Sin consulta')}
                          </td>
                          */}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            /* Carnet — columna única OCR */
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border, #e0e0e0)' }}>
                    <th style={thStyle('#888', '35%')}>Campo</th>
                    <th style={thStyle('#555', '65%')}>OCR (imagen)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(LABELS_CARNET).map(([key, label]) => {
                    const v = resultado.campos?.[key] || null;
                    return (
                      <tr key={key} style={{ borderBottom: '1px solid var(--border, #eee)' }}>
                        <td style={{ padding: '7px 10px', color: '#888', whiteSpace: 'nowrap' }}>{label}</td>
                        <td style={cellStyle(v)}>{v || 'No detectado'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {error && (
            <div style={{ color: 'var(--danger, #c0392b)', fontSize: '0.88rem', marginTop: '12px' }}>
              {error}
            </div>
          )}

          <div className="form-actions" style={{ marginTop: '20px' }}>
            <button type="button" className="btn btn-ghost" onClick={() => { setResultado(null); setError(''); }}>
              Detectar otra imagen
            </button>
            {tipoDoc !== 'DNI' && (
              <button type="button" className="btn btn-primary" onClick={() => handleUsarDatos(null)}>
                Usar datos para nuevo socio
              </button>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

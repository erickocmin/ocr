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

// Extrae el campo RENIEC equivalente para cada campo OCR
const RENIEC_MAP = {
  apellido_paterno:   (r) => r?.apellidoPaterno   || null,
  apellido_materno:   (r) => r?.apellidoMaterno   || null,
  nombres:            (r) => r?.nombres            || null,
  codigo_verificador: (r) => r?.digitoVerificador != null ? String(r.digitoVerificador) : null,
};

const INITIAL_LOGIN = { username: '', password: '' };

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

  function handleUsarDatos() {
    if (!resultado) return;
    const c = resultado.campos;
    const r = resultado.reniec;
    const socioData = {};

    if (tipoDoc === 'DNI') {
      // RENIEC tiene prioridad para datos personales; OCR para el resto
      socioData.nombre   = r?.nombres         || c.nombres         || '';
      const ap           = r?.apellidoPaterno || c.apellido_paterno || '';
      const am           = r?.apellidoMaterno || c.apellido_materno || '';
      socioData.apellido = [ap, am].filter(Boolean).join(' ');
    } else {
      if (c.nombre)    socioData.nombre   = c.nombre;
      if (c.apellidos) socioData.apellido = c.apellidos;
    }

    onApply(socioData);
    handleClose();
  }

  const labels   = tipoDoc === 'DNI' ? LABELS_DNI : LABELS_CARNET;
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
        /* Resultados con columnas OCR | RENIEC */
        <div>
          <p style={{ margin: '0 0 14px', color: 'var(--text-muted, #666)', fontSize: '0.85rem' }}>
            Al usar los datos, los campos personales (apellidos y nombre) se toman de RENIEC cuando están disponibles.
          </p>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border, #e0e0e0)' }}>
                  <th style={thStyle('#888', '25%')}>Campo</th>
                  <th style={thStyle('#555', '37%')}>OCR (imagen)</th>
                  <th style={thStyle('#1a6fa0', '38%')}>
                    RENIEC
                    {resultado.reniec && (
                      <span style={{ fontSize: '0.68rem', marginLeft: '6px', padding: '1px 7px', borderRadius: '10px', background: '#e8f4fd', color: '#1a6fa0', border: '1px solid #b3d9f5', fontWeight: 400 }}>
                        verificado
                      </span>
                    )}
                  </th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(labels).map(([key, label]) => {
                  const ocrVal    = resultado.campos[key] || null;
                  const reniecVal = RENIEC_MAP[key]?.(resultado.reniec) || null;
                  return (
                    <tr key={key} style={{ borderBottom: '1px solid var(--border, #eee)' }}>
                      <td style={{ padding: '7px 10px', color: '#888', whiteSpace: 'nowrap' }}>{label}</td>
                      <td style={{ padding: '7px 10px', color: ocrVal ? 'inherit' : '#bbb' }}>
                        {ocrVal || 'No detectado'}
                      </td>
                      <td style={{ padding: '7px 10px', color: reniecVal ? '#1558a0' : '#bbb', fontWeight: reniecVal ? 600 : 400 }}>
                        {reniecVal || (resultado.reniec ? '—' : 'Sin consulta')}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {error && (
            <div style={{ color: 'var(--danger, #c0392b)', fontSize: '0.88rem', marginTop: '12px' }}>
              {error}
            </div>
          )}

          <div className="form-actions" style={{ marginTop: '20px' }}>
            <button type="button" className="btn btn-ghost" onClick={() => { setResultado(null); setError(''); }}>
              Detectar otra imagen
            </button>
            <button type="button" className="btn btn-primary" onClick={handleUsarDatos}>
              Usar datos para nuevo socio
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

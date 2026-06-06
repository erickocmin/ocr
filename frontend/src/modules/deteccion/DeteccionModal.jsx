import { useState } from 'react';
import { Modal } from '../../components/Modal';

const LABELS_DNI = {
  numero_dni: 'N° DNI',
  apellido_paterno: 'Apellido Paterno',
  apellido_materno: 'Apellido Materno',
  nombre: 'Nombre(s)',
  fecha_nacimiento: 'Fecha de Nacimiento',
  sexo: 'Sexo',
};

const LABELS_CARNET = {
  numero_carnet: 'N° Carnet',
  apellidos: 'Apellidos',
  nombre: 'Nombre(s)',
  nacionalidad: 'Nacionalidad',
  fecha_nacimiento: 'Fecha de Nacimiento',
  sexo: 'Sexo',
};

const INITIAL_LOGIN = { username: '', password: '' };

export function DeteccionModal({ isOpen, onClose, onApply }) {
  const [tipoDoc, setTipoDoc] = useState('DNI');
  const [token, setToken] = useState('');
  const [loginForm, setLoginForm] = useState(INITIAL_LOGIN);
  const [loginMode, setLoginMode] = useState(false);
  const [imagen, setImagen] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [resultado, setResultado] = useState(null);

  function reset() {
    setTipoDoc('DNI');
    setToken('');
    setLoginForm(INITIAL_LOGIN);
    setLoginMode(false);
    setImagen(null);
    setPreview(null);
    setLoading(false);
    setError('');
    setResultado(null);
  }

  function handleClose() {
    reset();
    onClose();
  }

  function handleImageChange(e) {
    const file = e.target.files[0] || null;
    setImagen(file);
    setPreview(file ? URL.createObjectURL(file) : null);
    setError('');
  }

  async function handleObtenerToken() {
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
      if (!res.ok) throw new Error(data.error || data.detail || 'Error al autenticar.');
      setToken(data.token);
      setLoginMode(false);
      setLoginForm(INITIAL_LOGIN);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDetectar() {
    if (!imagen) { setError('Selecciona una imagen del documento.'); return; }
    if (!token.trim()) { setError('Ingresa tu token o inicia sesión para obtenerlo.'); return; }

    setLoading(true);
    setError('');
    const formData = new FormData();
    formData.append('imagen', imagen);
    formData.append('tipo_documento', tipoDoc);

    try {
      const res = await fetch('/api/deteccion/detectar/', {
        method: 'POST',
        headers: { Authorization: `Token ${token.trim()}` },
        body: formData,
      });
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
    const socioData = {};

    if (tipoDoc === 'DNI') {
      if (c.nombre) socioData.nombre = c.nombre;
      const partes = [c.apellido_paterno, c.apellido_materno].filter(Boolean);
      if (partes.length) socioData.apellido = partes.join(' ');
    } else {
      if (c.nombre) socioData.nombre = c.nombre;
      if (c.apellidos) socioData.apellido = c.apellidos;
    }

    onApply(socioData);
    handleClose();
  }

  const labels = tipoDoc === 'DNI' ? LABELS_DNI : LABELS_CARNET;

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Detección OCR de Documento" size="lg">
      {!resultado ? (
        <div className="form form-2col">

          {/* Tipo de documento */}
          <div className="form-group form-full">
            <label className="form-label">Tipo de documento</label>
            <div style={{ display: 'flex', gap: '24px', marginTop: '6px' }}>
              {[
                { value: 'DNI', label: 'DNI Nacional' },
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

          {/* Autenticación */}
          <div className="form-group form-full">
            <label className="form-label">Token de autenticación</label>
            {!loginMode ? (
              <>
                <input
                  className="form-control"
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="Pega aquí tu token de acceso"
                  autoComplete="off"
                />
                <button
                  type="button"
                  className="link-btn"
                  style={{ fontSize: '0.82rem', marginTop: '5px' }}
                  onClick={() => { setLoginMode(true); setError(''); }}
                >
                  ¿No tienes token? Iniciar sesión para obtenerlo
                </button>
              </>
            ) : (
              <div style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', background: 'var(--bg-muted, #f8f8f8)' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
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
                    onKeyDown={(e) => e.key === 'Enter' && handleObtenerToken()}
                  />
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      onClick={handleObtenerToken}
                      disabled={loading}
                    >
                      {loading ? 'Autenticando...' : 'Obtener token'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      onClick={() => { setLoginMode(false); setError(''); }}
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Imagen */}
          <div className="form-group form-full">
            <label className="form-label">Imagen del documento</label>
            <input
              className="form-control"
              type="file"
              accept="image/jpeg,image/png,image/webp,image/bmp,image/tiff"
              onChange={handleImageChange}
            />
            <span className="field-hint">Foto clara y sin reflejos. Máx 10 MB. Formatos: JPG, PNG, WEBP.</span>
            {preview && (
              <img
                src={preview}
                alt="Vista previa del documento"
                style={{ marginTop: '10px', maxHeight: '180px', borderRadius: '6px', border: '1px solid var(--border)', objectFit: 'contain' }}
              />
            )}
          </div>

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
              disabled={loading || !imagen || !token.trim()}
            >
              {loading ? 'Detectando...' : 'Detectar documento'}
            </button>
          </div>
        </div>
      ) : (
        /* Resultado */
        <div>
          <p style={{ marginBottom: '12px', color: 'var(--text-muted, #666)', fontSize: '0.9rem' }}>
            Campos detectados en el documento. Revisa antes de usar.
          </p>
          <div className="detalle-grid">
            {Object.entries(resultado.campos).map(([key, value]) => (
              <div key={key} className="detalle-row">
                <span>{labels[key] || key}</span>
                <strong style={{ color: value ? 'inherit' : 'var(--text-muted, #aaa)' }}>
                  {value || 'No detectado'}
                </strong>
              </div>
            ))}
          </div>

          {error && (
            <div style={{ color: 'var(--danger, #c0392b)', fontSize: '0.88rem', marginTop: '12px' }}>
              {error}
            </div>
          )}

          <div className="form-actions" style={{ marginTop: '20px' }}>
            <button type="button" className="btn btn-ghost" onClick={() => { setResultado(null); setError(''); }}>
              Volver
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

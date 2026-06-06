import { useEffect, useState } from 'react';
import { api, withQuery } from '../../api/client';
import { Modal } from '../../components/Modal';
import { Pagination } from '../../components/Pagination';
import { SearchBar } from '../../components/SearchBar';
import { BoolPill, StatusPill } from '../../components/StatusPill';
import { Timestamp } from '../../components/Timestamp';
import { DeteccionModal } from '../deteccion/DeteccionModal';

function SocioForm({ initial = {}, onSubmit, onCancel, loading }) {
  const [form, setForm] = useState({
    nombre:    initial.nombre    || '',
    apellido:  initial.apellido  || '',
    correo:    initial.correo    || '',
    telefono:  initial.telefono  || '',
    direccion: initial.direccion || '',
    notas:     initial.notas     || '',
  });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function handleSubmit(e) {
    e.preventDefault();
    onSubmit(form);
  }

  return (
    <form onSubmit={handleSubmit} className="form form-2col">
      <div className="form-group">
        <label className="form-label">Nombre *</label>
        <input className="form-control" value={form.nombre} onChange={set('nombre')} placeholder="Nombre(s)" required autoFocus />
        <span className="field-hint">Solo letras y espacios.</span>
      </div>
      <div className="form-group">
        <label className="form-label">Apellido</label>
        <input className="form-control" value={form.apellido} onChange={set('apellido')} placeholder="Apellido(s)" />
      </div>
      <div className="form-group">
        <label className="form-label">Correo electrónico *</label>
        <input className="form-control" type="email" value={form.correo} onChange={set('correo')} placeholder="correo@ejemplo.com" required />
      </div>
      <div className="form-group">
        <label className="form-label">Teléfono</label>
        <input className="form-control" value={form.telefono} onChange={set('telefono')} placeholder="Ej. 987 654 321" />
        <span className="field-hint">7 a 15 dígitos. Puede incluir espacios y guiones.</span>
      </div>
      <div className="form-group form-full">
        <label className="form-label">Dirección</label>
        <input className="form-control" value={form.direccion} onChange={set('direccion')} placeholder="Dirección del socio (opcional)" />
      </div>
      <div className="form-group form-full">
        <label className="form-label">Notas</label>
        <textarea className="form-control" rows={3} value={form.notas} onChange={set('notas')} placeholder="Observaciones relevantes sobre el socio..." />
      </div>
      <div className="form-actions form-full">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancelar</button>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? 'Guardando...' : 'Guardar'}
        </button>
      </div>
    </form>
  );
}

function SocioDetalle({ socio }) {
  return (
    <div className="detalle-grid">
      <div className="detalle-row"><span>Nombre completo</span><strong>{socio.nombre_completo}</strong></div>
      <div className="detalle-row"><span>Correo</span><strong>{socio.correo}</strong></div>
      <div className="detalle-row"><span>Teléfono</span><strong>{socio.telefono || '—'}</strong></div>
      <div className="detalle-row"><span>Dirección</span><strong>{socio.direccion || '—'}</strong></div>
      <div className="detalle-row"><span>Estado</span><BoolPill value={socio.activo} trueLabel="Activo" falseLabel="Inactivo" /></div>
      <div className="detalle-row"><span>Préstamos activos</span><strong>{socio.prestamos_activos_count}</strong></div>
      <div className="detalle-row">
        <span>Préstamos vencidos</span>
        {socio.tiene_prestamos_vencidos
          ? <StatusPill variant="danger">Tiene vencidos</StatusPill>
          : <StatusPill variant="success">Sin vencidos</StatusPill>}
      </div>
      <div className="detalle-row"><span>Registrado</span><strong><Timestamp value={socio.created_at} /></strong></div>
      <div className="detalle-row"><span>Última modificación</span><strong><Timestamp value={socio.updated_at} /></strong></div>
      {socio.notas && (
        <div className="detalle-notas"><span>Notas</span><p>{socio.notas}</p></div>
      )}
    </div>
  );
}

export function Socios({ onSuccess, onError }) {
  const [socios, setSocios] = useState([]);
  const [search, setSearch] = useState('');
  const [filterActivo, setFilterActivo] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [meta, setMeta] = useState(null);
  const [modal, setModal] = useState(null);
  const [saving, setSaving] = useState(false);
  const [showDeteccion, setShowDeteccion] = useState(false);
  const [prefilledData, setPrefilledData] = useState({});

  async function load() {
    const data = await api.getPage(withQuery('socios/', {
      page,
      page_size: pageSize,
      q: search,
      activo: filterActivo,
    }));
    setSocios(data.results);
    setMeta(data);
  }

  useEffect(() => { load(); }, [page, pageSize, search, filterActivo]);

  function handleSearch(value) {
    setSearch(value);
    setPage(1);
  }

  function handleActivo(value) {
    setFilterActivo(value);
    setPage(1);
  }

  function handlePageSize(value) {
    setPageSize(value);
    setPage(1);
  }

  async function handleAdd(data) {
    setSaving(true);
    try {
      await api.post('socios/', data);
      onSuccess('Socio registrado correctamente.');
      setModal(null);
      await load();
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleEdit(data) {
    setSaving(true);
    try {
      await api.patch(`socios/${modal.id}/`, data);
      onSuccess('Socio actualizado correctamente.');
      setModal(null);
      await load();
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function toggleActivo(socio) {
    const accion = socio.activo ? 'desactivar' : 'activar';
    if (!confirm(`¿Deseas ${accion} al socio "${socio.nombre_completo}"?`)) return;
    try {
      await api.patch(`socios/${socio.id}/`, { activo: !socio.activo });
      onSuccess(`Socio ${socio.activo ? 'desactivado' : 'activado'}.`);
      await load();
    } catch (e) {
      onError(e.message);
    }
  }

  function handleOcrApply(datos) {
    setPrefilledData(datos);
    setModal('add');
  }

  const isEditing = modal && typeof modal === 'object' && !modal.view;
  const isViewing = modal && typeof modal === 'object' && modal.view;

  return (
    <div className="module">
      <div className="module-header">
        <h2 className="module-title">Socios</h2>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn btn-ghost" onClick={() => setShowDeteccion(true)}>
            Detección OCR
          </button>
          <button className="btn btn-primary" onClick={() => { setPrefilledData({}); setModal('add'); }}>
            Agregar socio
          </button>
        </div>
      </div>

      <div className="module-toolbar">
        <SearchBar value={search} onChange={handleSearch} placeholder="Buscar por nombre, correo o teléfono..." />
        <select className="filter-select" value={filterActivo} onChange={(e) => handleActivo(e.target.value)}>
          <option value="">Todos</option>
          <option value="true">Solo activos</option>
          <option value="false">Solo inactivos</option>
        </select>
      </div>

      <div className="table-wrap">
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Correo</th>
                <th>Teléfono</th>
                <th>Estado</th>
                <th>Activos</th>
                <th>Vencidos</th>
                <th>Registrado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {socios.length === 0 && (
                <tr><td colSpan={8} className="empty-row">No se encontraron socios.</td></tr>
              )}
              {socios.map((s) => (
                <tr key={s.id} className={s.tiene_prestamos_vencidos ? 'row-warning' : ''}>
                  <td>
                    <button className="link-btn" onClick={() => setModal({ view: s })}>
                      {s.nombre_completo}
                    </button>
                  </td>
                  <td>{s.correo}</td>
                  <td>{s.telefono || '—'}</td>
                  <td><BoolPill value={s.activo} trueLabel="Activo" falseLabel="Inactivo" /></td>
                  <td className="text-center">{s.prestamos_activos_count}</td>
                  <td className="text-center">
                    {s.tiene_prestamos_vencidos
                      ? <StatusPill variant="danger">Sí</StatusPill>
                      : <StatusPill variant="success">No</StatusPill>}
                  </td>
                  <td><Timestamp value={s.created_at} /></td>
                  <td className="actions-cell">
                    <button className="btn btn-sm btn-ghost" onClick={() => setModal(s)}>Editar</button>
                    <button
                      className={`btn btn-sm ${s.activo ? 'btn-warning-ghost' : 'btn-ghost'}`}
                      onClick={() => toggleActivo(s)}
                    >
                      {s.activo ? 'Desactivar' : 'Activar'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <Pagination
        meta={meta}
        pageSize={pageSize}
        onPageChange={setPage}
        onPageSizeChange={handlePageSize}
      />

      <Modal isOpen={modal === 'add'} onClose={() => setModal(null)} title="Nuevo socio" size="lg">
        <SocioForm initial={prefilledData} onSubmit={handleAdd} onCancel={() => setModal(null)} loading={saving} />
      </Modal>

      <DeteccionModal
        isOpen={showDeteccion}
        onClose={() => setShowDeteccion(false)}
        onApply={handleOcrApply}
      />

      <Modal isOpen={isEditing} onClose={() => setModal(null)} title={`Editar: ${modal?.nombre_completo}`} size="lg">
        <SocioForm initial={modal || {}} onSubmit={handleEdit} onCancel={() => setModal(null)} loading={saving} />
      </Modal>

      <Modal isOpen={!!isViewing} onClose={() => setModal(null)} title={modal?.view?.nombre_completo} size="md">
        {isViewing && <SocioDetalle socio={modal.view} />}
      </Modal>
    </div>
  );
}

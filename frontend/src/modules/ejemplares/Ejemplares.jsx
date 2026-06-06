import { useEffect, useState } from 'react';
import { api, withQuery } from '../../api/client';
import { Modal } from '../../components/Modal';
import { Pagination } from '../../components/Pagination';
import { SearchBar } from '../../components/SearchBar';
import { BoolPill, StatusPill } from '../../components/StatusPill';
import { Timestamp } from '../../components/Timestamp';

const ESTADOS = ['NUEVO', 'BUENO', 'REGULAR', 'MALO', 'DETERIORADO'];
const ESTADO_LABEL = {
  NUEVO: 'Nuevo', BUENO: 'Bueno', REGULAR: 'Regular', MALO: 'Malo', DETERIORADO: 'Deteriorado',
};
const ESTADO_VARIANT = {
  NUEVO: 'success', BUENO: 'success', REGULAR: 'warning', MALO: 'danger', DETERIORADO: 'danger',
};

function EjemplarForm({ initial = {}, libros, onSubmit, onCancel, loading, isEdit }) {
  const [form, setForm] = useState({
    libro:  initial.libro  || '',
    codigo: initial.codigo || '',
    estado: initial.estado || 'BUENO',
    notas:  initial.notas  || '',
  });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function handleSubmit(e) {
    e.preventDefault();
    const payload = { ...form };
    if (isEdit) delete payload.libro;
    onSubmit(payload);
  }

  const libroActual = isEdit ? libros.find((l) => l.id === initial.libro) : null;
  const libroNombre = libroActual?.titulo || (isEdit ? `ID ${initial.libro}` : '');

  const codigoTieneHistorial = isEdit && initial.prestamos_count > 0;

  return (
    <form onSubmit={handleSubmit} className="form form-2col">
      <div className="form-group">
        <label className="form-label">Libro *</label>
        {isEdit ? (
          <input className="form-control" value={libroNombre} disabled />
        ) : (
          <select className="form-control" value={form.libro} onChange={set('libro')} required>
            <option value="">Seleccionar libro</option>
            {libros.filter((l) => !l.retirado).map((l) => (
              <option key={l.id} value={l.id}>{l.titulo}</option>
            ))}
          </select>
        )}
        {isEdit && (
          <span className="field-hint">El libro no se puede cambiar una vez creado el ejemplar.</span>
        )}
      </div>

      <div className="form-group">
        <label className="form-label">Código *</label>
        <input
          className="form-control"
          value={form.codigo}
          onChange={set('codigo')}
          placeholder="Ej. 01, A-01, EJ001"
          required
          disabled={codigoTieneHistorial}
        />
        {codigoTieneHistorial ? (
          <span className="field-hint">No se puede modificar: tiene historial de préstamos.</span>
        ) : (
          <span className="field-hint">El código debe ser único dentro del mismo libro.</span>
        )}
      </div>

      <div className="form-group">
        <label className="form-label">Estado físico</label>
        <select className="form-control" value={form.estado} onChange={set('estado')}>
          {ESTADOS.map((e) => (
            <option key={e} value={e}>{ESTADO_LABEL[e]}</option>
          ))}
        </select>
      </div>

      <div className="form-group form-full">
        <label className="form-label">Notas del ejemplar</label>
        <textarea
          className="form-control"
          rows={3}
          value={form.notas}
          onChange={set('notas')}
          placeholder="Estado físico detallado, marcas, daños, historial de reparaciones..."
        />
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

export function Ejemplares({ onSuccess, onError }) {
  const [ejemplares, setEjemplares] = useState([]);
  const [libros, setLibros] = useState([]);
  const [search, setSearch] = useState('');
  const [filterRetirado, setFilterRetirado] = useState('false');
  const [filterEstado, setFilterEstado] = useState('');
  const [filterDisponible, setFilterDisponible] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [meta, setMeta] = useState(null);
  const [modal, setModal] = useState(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    const data = await api.getPage(withQuery('ejemplares/', {
      page,
      page_size: pageSize,
      q: search,
      estado: filterEstado,
      retirado: filterRetirado,
      disponibles: filterDisponible,
    }));
    setEjemplares(data.results);
    setMeta(data);
  }

  async function loadCatalogs() {
    const l = await api.get('libros/?page_size=100');
    setLibros(l);
  }

  useEffect(() => { load(); }, [page, pageSize, search, filterEstado, filterRetirado, filterDisponible]);
  useEffect(() => { loadCatalogs(); }, []);

  function resetPageWith(setter) {
    return (value) => {
      setter(value);
      setPage(1);
    };
  }

  function handlePageSize(value) {
    setPageSize(value);
    setPage(1);
  }

  async function handleAdd(data) {
    setSaving(true);
    try {
      await api.post('ejemplares/', data);
      onSuccess('Ejemplar registrado correctamente.');
      setModal(null);
      await load();
      await loadCatalogs();
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleEdit(data) {
    setSaving(true);
    try {
      await api.patch(`ejemplares/${modal.id}/`, data);
      onSuccess('Ejemplar actualizado correctamente.');
      setModal(null);
      await load();
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function toggleRetirado(ej) {
    const accion = ej.retirado ? 'restaurar' : 'retirar';
    if (!confirm(`¿Deseas ${accion} el ejemplar "${ej.codigo}" del libro "${ej.libro_titulo}"?`)) return;
    try {
      await api.patch(`ejemplares/${ej.id}/`, { retirado: !ej.retirado });
      onSuccess(`Ejemplar ${ej.retirado ? 'restaurado' : 'retirado'}.`);
      await load();
    } catch (e) {
      onError(e.message);
    }
  }

  const isEditing = modal && typeof modal === 'object';

  return (
    <div className="module">
      <div className="module-header">
        <h2 className="module-title">Ejemplares</h2>
        <button className="btn btn-primary" onClick={() => setModal('add')}>Agregar ejemplar</button>
      </div>

      <div className="module-toolbar">
        <SearchBar value={search} onChange={resetPageWith(setSearch)} placeholder="Buscar por código o título de libro..." />
        <select className="filter-select" value={filterEstado} onChange={(e) => resetPageWith(setFilterEstado)(e.target.value)}>
          <option value="">Todos los estados</option>
          {ESTADOS.map((e) => <option key={e} value={e}>{ESTADO_LABEL[e]}</option>)}
        </select>
        <select className="filter-select" value={filterDisponible} onChange={(e) => resetPageWith(setFilterDisponible)(e.target.value)}>
          <option value="">Disponibilidad</option>
          <option value="true">Disponibles</option>
          <option value="false">No disponibles</option>
        </select>
        <select className="filter-select" value={filterRetirado} onChange={(e) => resetPageWith(setFilterRetirado)(e.target.value)}>
          <option value="">Todos</option>
          <option value="false">Solo activos</option>
          <option value="true">Solo retirados</option>
        </select>
      </div>

      <div className="table-wrap">
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Código</th>
                <th>Libro</th>
                <th>Estado físico</th>
                <th>Disponible</th>
                <th>Activo</th>
                <th>Registrado</th>
                <th>Modificado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {ejemplares.length === 0 && (
                <tr><td colSpan={8} className="empty-row">No se encontraron ejemplares.</td></tr>
              )}
              {ejemplares.map((e) => (
                <tr key={e.id} className={e.retirado ? 'row-muted' : ''}>
                  <td><code>{e.codigo}</code></td>
                  <td>{e.libro_titulo}</td>
                  <td>
                    <StatusPill variant={ESTADO_VARIANT[e.estado] || 'secondary'}>
                      {e.estado_display || e.estado}
                    </StatusPill>
                  </td>
                  <td>
                    <BoolPill value={e.disponible} trueLabel="Disponible" falseLabel="En préstamo" />
                  </td>
                  <td><BoolPill value={!e.retirado} trueLabel="Activo" falseLabel="Retirado" /></td>
                  <td><Timestamp value={e.created_at} /></td>
                  <td><Timestamp value={e.updated_at} /></td>
                  <td className="actions-cell">
                    <button className="btn btn-sm btn-ghost" onClick={() => setModal(e)}>Editar</button>
                    <button
                      className={`btn btn-sm ${e.retirado ? 'btn-ghost' : 'btn-warning-ghost'}`}
                      onClick={() => toggleRetirado(e)}
                    >
                      {e.retirado ? 'Restaurar' : 'Retirar'}
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

      <Modal isOpen={modal === 'add'} onClose={() => setModal(null)} title="Nuevo ejemplar" size="lg">
        <EjemplarForm libros={libros} onSubmit={handleAdd} onCancel={() => setModal(null)} loading={saving} isEdit={false} />
      </Modal>

      <Modal isOpen={isEditing} onClose={() => setModal(null)} title={`Editar ejemplar: ${modal?.codigo}`} size="lg">
        <EjemplarForm
          initial={modal || {}}
          libros={libros}
          onSubmit={handleEdit}
          onCancel={() => setModal(null)}
          loading={saving}
          isEdit
        />
      </Modal>
    </div>
  );
}

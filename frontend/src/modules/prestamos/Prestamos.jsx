import { useEffect, useState } from 'react';
import { api, withQuery } from '../../api/client';
import { Modal } from '../../components/Modal';
import { Pagination } from '../../components/Pagination';
import { SearchBar } from '../../components/SearchBar';
import { SearchableSelect } from '../../components/SearchableSelect';
import { StatusPill } from '../../components/StatusPill';
import { DateOnly, Timestamp } from '../../components/Timestamp';

function today() {
  return new Date().toISOString().split('T')[0];
}

function todayPlus(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().split('T')[0];
}

function PrestamoForm({ socios, libros, onSubmit, onCancel, loading }) {
  const [form, setForm] = useState({
    socio: '',
    libro: '',
    ejemplar: '',
    fecha_vencimiento: todayPlus(14),
    notas: '',
  });
  const [modoEjemplar, setModoEjemplar] = useState(false);
  const [ejemplares, setEjemplares] = useState([]);

  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const setE = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function handleLibroChange(val) {
    setForm((f) => ({ ...f, libro: val, ejemplar: '' }));
    if (val && modoEjemplar) {
      const data = await api.get(`ejemplares/?libro=${val}&disponibles=true`);
      setEjemplares(data);
    }
  }

  async function toggleModo() {
    const next = !modoEjemplar;
    setModoEjemplar(next);
    if (next && form.libro) {
      const data = await api.get(`ejemplares/?libro=${form.libro}&disponibles=true`);
      setEjemplares(data);
    } else if (!next) {
      setForm((f) => ({ ...f, ejemplar: '' }));
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    const payload = {
      socio: Number(form.socio),
      fecha_vencimiento: form.fecha_vencimiento,
      notas: form.notas,
    };
    if (modoEjemplar && form.ejemplar) {
      payload.ejemplar = Number(form.ejemplar);
    } else {
      payload.libro = Number(form.libro);
    }
    onSubmit(payload);
  }

  const sociosOpts = socios
    .filter((s) => s.activo)
    .map((s) => ({
      value: s.id,
      label: s.nombre_completo,
      sub: s.correo + (s.tiene_prestamos_vencidos ? ' — tiene vencidos' : ''),
    }));

  const librosOpts = libros
    .filter((l) => !l.retirado && l.ejemplares_disponibles > 0)
    .map((l) => ({
      value: l.id,
      label: l.titulo,
      sub: `${l.ejemplares_disponibles} disponible${l.ejemplares_disponibles !== 1 ? 's' : ''}`,
    }));

  const ejemplaresOpts = ejemplares.map((e) => ({
    value: e.id,
    label: e.codigo,
    sub: e.estado_display || e.estado,
  }));

  return (
    <form onSubmit={handleSubmit} className="form form-2col">
      <div className="form-group form-full">
        <label className="form-label">Socio *</label>
        <SearchableSelect
          options={sociosOpts}
          value={form.socio}
          onChange={set('socio')}
          placeholder="Buscar socio por nombre o correo..."
          required
        />
        {sociosOpts.length === 0 && (
          <span className="field-hint text-danger">No hay socios activos registrados.</span>
        )}
      </div>

      <div className="form-group form-full">
        <label className="form-label">Libro *</label>
        <SearchableSelect
          options={librosOpts}
          value={form.libro}
          onChange={handleLibroChange}
          placeholder="Buscar libro por título o autor..."
          required
        />
        {librosOpts.length === 0 && (
          <span className="field-hint text-danger">No hay libros con ejemplares disponibles.</span>
        )}
      </div>

      <div className="form-group form-full">
        <label className="checkbox-toggle">
          <input type="checkbox" checked={modoEjemplar} onChange={toggleModo} />
          Seleccionar un ejemplar específico
        </label>
      </div>

      {modoEjemplar && (
        <div className="form-group form-full">
          <label className="form-label">Ejemplar *</label>
          <SearchableSelect
            options={ejemplaresOpts}
            value={form.ejemplar}
            onChange={(v) => setForm((f) => ({ ...f, ejemplar: v }))}
            placeholder="Seleccionar ejemplar..."
            required
          />
          {form.libro && ejemplaresOpts.length === 0 && (
            <span className="field-hint text-danger">No hay ejemplares disponibles para este libro.</span>
          )}
        </div>
      )}

      <div className="form-group">
        <label className="form-label">Fecha de vencimiento *</label>
        <input
          className="form-control"
          type="date"
          value={form.fecha_vencimiento}
          min={today()}
          max={todayPlus(60)}
          onChange={setE('fecha_vencimiento')}
          required
        />
        <span className="field-hint">Desde hoy hasta máximo 60 días.</span>
      </div>

      <div className="form-group form-full">
        <label className="form-label">Notas</label>
        <textarea
          className="form-control"
          rows={2}
          value={form.notas}
          onChange={setE('notas')}
          placeholder="Estado del ejemplar al salir, observaciones, acuerdos..."
        />
      </div>

      <div className="form-actions form-full">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancelar</button>
        <button type="submit" className="btn btn-primary" disabled={loading || !form.socio || !form.libro}>
          {loading ? 'Registrando...' : 'Registrar préstamo'}
        </button>
      </div>
    </form>
  );
}

function NotasForm({ prestamo, onSubmit, onCancel, loading }) {
  const [notas, setNotas] = useState(prestamo.notas || '');
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit({ notas }); }} className="form">
      <div className="form-group">
        <label className="form-label">Notas del préstamo</label>
        <textarea
          className="form-control"
          rows={5}
          value={notas}
          onChange={(e) => setNotas(e.target.value)}
          placeholder="Observaciones, estado al devolver, incidencias..."
          autoFocus
        />
      </div>
      <div className="form-actions">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancelar</button>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? 'Guardando...' : 'Guardar notas'}
        </button>
      </div>
    </form>
  );
}

function estadoPrestamo(p) {
  if (p.fecha_devolucion) return { label: 'Devuelto', variant: 'success' };
  if (p.vencido)          return { label: 'Vencido',  variant: 'danger' };
  return { label: 'Activo', variant: 'info' };
}

export function Prestamos({ onSuccess, onError }) {
  const [prestamos, setPrestamos] = useState([]);
  const [socios, setSocios] = useState([]);
  const [libros, setLibros] = useState([]);
  const [search, setSearch] = useState('');
  const [filterEstado, setFilterEstado] = useState('activos');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [meta, setMeta] = useState(null);
  const [modal, setModal] = useState(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    const params = {
      page,
      page_size: pageSize,
      q: search,
    };
    if (filterEstado === 'activos') params.activos = 'true';
    if (filterEstado === 'devueltos') params.activos = 'false';
    if (filterEstado === 'vencidos') params.vencidos = 'true';

    const data = await api.getPage(withQuery('prestamos/', params));
    setPrestamos(data.results);
    setMeta(data);
  }

  async function loadCatalogs() {
    const [s, l] = await Promise.all([
      api.get('socios/?page_size=100'),
      api.get('libros/?page_size=100'),
    ]);
    setSocios(s);
    setLibros(l);
  }

  useEffect(() => { load(); }, [page, pageSize, search, filterEstado]);
  useEffect(() => { loadCatalogs(); }, []);

  function handleSearch(value) {
    setSearch(value);
    setPage(1);
  }

  function handleEstado(value) {
    setFilterEstado(value);
    setPage(1);
  }

  function handlePageSize(value) {
    setPageSize(value);
    setPage(1);
  }

  async function handleAdd(data) {
    setSaving(true);
    try {
      await api.post('prestamos/', data);
      onSuccess('Préstamo registrado correctamente.');
      setModal(null);
      await load();
      await loadCatalogs();
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function devolver(prestamo) {
    if (!confirm(`Confirmar devolución:\n"${prestamo.libro_titulo}" — ${prestamo.socio_nombre}`)) return;
    try {
      await api.post(`prestamos/${prestamo.id}/devolver/`, {});
      onSuccess('Devolución registrada correctamente.');
      await load();
      await loadCatalogs();
    } catch (e) {
      onError(e.message);
    }
  }

  async function handleEditNotas(data) {
    setSaving(true);
    try {
      await api.patch(`prestamos/${modal.id}/`, data);
      onSuccess('Notas actualizadas.');
      setModal(null);
      await load();
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }

  const isEditNotas = modal && typeof modal === 'object' && modal.editNotas;

  return (
    <div className="module">
      <div className="module-header">
        <h2 className="module-title">Préstamos</h2>
        <button className="btn btn-primary" onClick={() => setModal('add')}>Nuevo préstamo</button>
      </div>

      <div className="module-toolbar">
        <SearchBar value={search} onChange={handleSearch} placeholder="Buscar por socio, libro o código de ejemplar..." />
        <select className="filter-select" value={filterEstado} onChange={(e) => handleEstado(e.target.value)}>
          <option value="activos">Activos</option>
          <option value="vencidos">Vencidos</option>
          <option value="devueltos">Devueltos</option>
          <option value="">Todos</option>
        </select>
      </div>

      <div className="table-wrap">
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Socio</th>
                <th>Libro</th>
                <th>Ejemplar</th>
                <th>Préstamo</th>
                <th>Vencimiento</th>
                <th>Devolución</th>
                <th>Estado</th>
                <th>Notas</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {prestamos.length === 0 && (
                <tr><td colSpan={9} className="empty-row">Sin resultados para el filtro seleccionado.</td></tr>
              )}
              {prestamos.map((p) => {
                const estado = estadoPrestamo(p);
                return (
                  <tr key={p.id} className={p.vencido ? 'row-danger' : p.fecha_devolucion ? 'row-muted' : ''}>
                    <td>
                      <div style={{ fontWeight: 500, color: 'var(--ink)' }}>{p.socio_nombre}</div>
                      <div style={{ fontSize: '.77rem', color: 'var(--ink-light)' }}>{p.socio_correo}</div>
                    </td>
                    <td>{p.libro_titulo}</td>
                    <td><code>{p.ejemplar_codigo}</code></td>
                    <td><Timestamp value={p.fecha_prestamo} /></td>
                    <td><DateOnly value={p.fecha_vencimiento} /></td>
                    <td>
                      {p.fecha_devolucion
                        ? <Timestamp value={p.fecha_devolucion} />
                        : <span className="text-muted">Pendiente</span>}
                    </td>
                    <td><StatusPill variant={estado.variant}>{estado.label}</StatusPill></td>
                    <td className="notas-cell" title={p.notas || ''}>{p.notas || '—'}</td>
                    <td className="actions-cell">
                      {!p.fecha_devolucion && (
                        <button className="btn btn-sm btn-primary" onClick={() => devolver(p)}>
                          Devolver
                        </button>
                      )}
                      <button className="btn btn-sm btn-ghost" onClick={() => setModal({ ...p, editNotas: true })}>
                        Notas
                      </button>
                    </td>
                  </tr>
                );
              })}
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

      <Modal isOpen={modal === 'add'} onClose={() => setModal(null)} title="Nuevo préstamo" size="lg">
        <PrestamoForm
          socios={socios}
          libros={libros}
          onSubmit={handleAdd}
          onCancel={() => setModal(null)}
          loading={saving}
        />
      </Modal>

      <Modal isOpen={!!isEditNotas} onClose={() => setModal(null)} title={`Notas — ${modal?.libro_titulo}`}>
        {isEditNotas && (
          <NotasForm
            prestamo={modal}
            onSubmit={handleEditNotas}
            onCancel={() => setModal(null)}
            loading={saving}
          />
        )}
      </Modal>
    </div>
  );
}

import { useEffect, useState } from 'react';
import { api, withQuery } from '../../api/client';
import { Modal } from '../../components/Modal';
import { Pagination } from '../../components/Pagination';
import { SearchBar } from '../../components/SearchBar';
import { Timestamp } from '../../components/Timestamp';

function AutorForm({ initial = {}, onSubmit, onCancel, loading }) {
  const [nombre, setNombre] = useState(initial.nombre || '');

  function handleSubmit(e) {
    e.preventDefault();
    onSubmit({ nombre });
  }

  return (
    <form onSubmit={handleSubmit} className="form">
      <div className="form-group">
        <label className="form-label">Nombre completo *</label>
        <input
          className="form-control"
          value={nombre}
          onChange={(e) => setNombre(e.target.value)}
          placeholder="Nombre del autor o autora"
          required
          autoFocus
        />
        <span className="field-hint">Solo letras, espacios, guiones y apóstrofes.</span>
      </div>
      <div className="form-actions">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancelar</button>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? 'Guardando...' : 'Guardar'}
        </button>
      </div>
    </form>
  );
}

export function Autores({ onSuccess, onError }) {
  const [autores, setAutores] = useState([]);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [meta, setMeta] = useState(null);
  const [modal, setModal] = useState(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    const data = await api.getPage(withQuery('autores/', {
      page,
      page_size: pageSize,
      q: search,
    }));
    setAutores(data.results);
    setMeta(data);
  }

  useEffect(() => { load(); }, [page, pageSize, search]);

  function handleSearch(value) {
    setSearch(value);
    setPage(1);
  }

  function handlePageSize(value) {
    setPageSize(value);
    setPage(1);
  }

  async function handleAdd(data) {
    setSaving(true);
    try {
      await api.post('autores/', data);
      onSuccess('Autor registrado correctamente.');
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
      await api.patch(`autores/${modal.id}/`, data);
      onSuccess('Autor actualizado correctamente.');
      setModal(null);
      await load();
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(autor) {
    if (!confirm(`Eliminar a "${autor.nombre}"?\n\nEsta acción solo es posible si el autor no tiene libros asociados.`)) return;
    try {
      await api.delete(`autores/${autor.id}/`);
      onSuccess('Autor eliminado.');
      await load();
    } catch (e) {
      onError(e.message);
    }
  }

  const isEditing = modal && typeof modal === 'object';

  return (
    <div className="module">
      <div className="module-header">
        <h2 className="module-title">Autores</h2>
        <button className="btn btn-primary" onClick={() => setModal('add')}>Agregar autor</button>
      </div>

      <div className="module-toolbar">
        <SearchBar value={search} onChange={handleSearch} placeholder="Buscar por nombre..." />
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Libros</th>
              <th>Registrado</th>
              <th>Modificado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {autores.length === 0 && (
              <tr><td colSpan={5} className="empty-row">No se encontraron autores.</td></tr>
            )}
            {autores.map((a) => (
              <tr key={a.id}>
                <td style={{ fontWeight: 500 }}>{a.nombre}</td>
                <td>{a.libros_count}</td>
                <td><Timestamp value={a.created_at} /></td>
                <td><Timestamp value={a.updated_at} /></td>
                <td className="actions-cell">
                  <button className="btn btn-sm btn-ghost" onClick={() => setModal(a)}>Editar</button>
                  {a.libros_count === 0 && (
                    <button className="btn btn-sm btn-danger-ghost" onClick={() => handleDelete(a)}>
                      Eliminar
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination
        meta={meta}
        pageSize={pageSize}
        onPageChange={setPage}
        onPageSizeChange={handlePageSize}
      />

      <Modal isOpen={modal === 'add'} onClose={() => setModal(null)} title="Nuevo autor">
        <AutorForm onSubmit={handleAdd} onCancel={() => setModal(null)} loading={saving} />
      </Modal>

      <Modal isOpen={isEditing} onClose={() => setModal(null)} title={`Editar: ${modal?.nombre}`}>
        <AutorForm
          initial={modal || {}}
          onSubmit={handleEdit}
          onCancel={() => setModal(null)}
          loading={saving}
        />
      </Modal>
    </div>
  );
}

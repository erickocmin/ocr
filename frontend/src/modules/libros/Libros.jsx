import { useEffect, useState } from "react";
import { api, withQuery } from "../../api/client";
import { Modal } from "../../components/Modal";
import { Pagination } from "../../components/Pagination";
import { SearchBar } from "../../components/SearchBar";
import { BoolPill, StatusPill } from "../../components/StatusPill";
import { Timestamp } from "../../components/Timestamp";

const ANIO_MIN = 1000;
const ANIO_MAX = new Date().getFullYear();

const GENEROS = [
  "Arte",
  "Astronomía",
  "Autobiografía",
  "Aventura",
  "Biología",
  "Biografía",
  "Ciencia",
  "Ciencia ficción",
  "Cómic",
  "Crónica",
  "Cuento",
  "Derecho",
  "Diccionario",
  "Economía",
  "Educación",
  "Enciclopedia",
  "Ensayo",
  "Fantasía",
  "Filosofía",
  "Física",
  "Gastronomía",
  "Geografía",
  "Historia",
  "Humor",
  "Informática",
  "Ingeniería",
  "Literatura infantil",
  "Literatura juvenil",
  "Matemáticas",
  "Medicina",
  "Memorias",
  "Misterio",
  "Música",
  "Naturaleza",
  "Novela",
  "Novela gráfica",
  "Pedagogía",
  "Poesía",
  "Política",
  "Psicología",
  "Química",
  "Referencia",
  "Religión",
  "Romance",
  "Salud",
  "Sociología",
  "Teatro",
  "Tecnología",
  "Terror",
  "Thriller",
  "Viajes",
];

function AutoresSearch({ autores, selected, onToggle }) {
  const [q, setQ] = useState("");
  const filtrados = q
    ? autores.filter((a) => a.nombre.toLowerCase().includes(q.toLowerCase()))
    : autores;

  return (
    <div>
      {autores.length > 6 && (
        <input
          className="form-control"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filtrar autores..."
          style={{ marginBottom: 8 }}
        />
      )}
      <div className="checkbox-group">
        {autores.length === 0 && (
          <span className="text-muted" style={{ padding: "4px 6px" }}>
            No hay autores. Agrégate en el módulo Autores.
          </span>
        )}
        {filtrados.map((a) => (
          <label key={a.id} className="checkbox-item">
            <input
              type="checkbox"
              checked={selected.includes(a.id)}
              onChange={() => onToggle(a.id)}
            />
            {a.nombre}
          </label>
        ))}
        {q && filtrados.length === 0 && (
          <span className="text-muted" style={{ padding: "4px 6px" }}>
            Sin resultados para "{q}"
          </span>
        )}
      </div>
    </div>
  );
}

function LibroForm({ initial = {}, autores, onSubmit, onCancel, loading }) {
  const [form, setForm] = useState({
    titulo: initial.titulo || "",
    autores_ids: initial.autores ? initial.autores.map((a) => a.id) : [],
    isbn: initial.isbn || "",
    genero: initial.genero || "",
    anio_publicacion: initial.anio_publicacion || "",
    notas: initial.notas || "",
  });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function toggleAutor(id) {
    setForm((f) => ({
      ...f,
      autores_ids: f.autores_ids.includes(id)
        ? f.autores_ids.filter((x) => x !== id)
        : [...f.autores_ids, id],
    }));
  }

  function handleSubmit(e) {
    e.preventDefault();
    const payload = { ...form };
    if (!payload.isbn) delete payload.isbn;
    if (!payload.anio_publicacion) {
      delete payload.anio_publicacion;
    } else {
      payload.anio_publicacion = Number(payload.anio_publicacion);
    }
    onSubmit(payload);
  }

  return (
    <form onSubmit={handleSubmit} className="form form-2col">
      <div className="form-group form-full">
        <label className="form-label">Título *</label>
        <input
          className="form-control"
          value={form.titulo}
          onChange={set("titulo")}
          placeholder="Título del libro"
          required
          autoFocus
        />
      </div>

      <div className="form-group form-full">
        <label className="form-label">
          Autores *{" "}
          <span className="label-hint">— selecciona al menos uno</span>
        </label>
        <AutoresSearch
          autores={autores}
          selected={form.autores_ids}
          onToggle={toggleAutor}
        />
        {form.autores_ids.length > 0 && (
          <span className="field-hint">
            {form.autores_ids.length} autor(es) seleccionado(s)
          </span>
        )}
      </div>

      <div className="form-group">
        <label className="form-label">Género</label>
        <input
          className="form-control"
          list="lista-generos"
          value={form.genero}
          onChange={set("genero")}
          placeholder="Seleccionar o escribir..."
          autoComplete="off"
        />
        <datalist id="lista-generos">
          {GENEROS.map((g) => (
            <option key={g} value={g} />
          ))}
        </datalist>
        <span className="field-hint">
          Selecciona de la lista o escribe uno personalizado.
        </span>
      </div>

      <div className="form-group">
        <label className="form-label">Año de publicación</label>
        <input
          className="form-control"
          list="lista-anios"
          value={form.anio_publicacion}
          onChange={set("anio_publicacion")}
          placeholder={`Escribe o selecciona (${ANIO_MIN}–${ANIO_MAX})`}
          autoComplete="off"
        />
        <datalist id="lista-anios">
          {Array.from({ length: ANIO_MAX - 1899 }, (_, i) => ANIO_MAX - i).map(
            (a) => (
              <option key={a} value={a} />
            ),
          )}
        </datalist>
        <span className="field-hint">Puedes escribir el año directamente.</span>
      </div>

      <div className="form-group">
        <label className="form-label">ISBN</label>
        <input
          className="form-control"
          value={form.isbn}
          onChange={set("isbn")}
          placeholder="10 o 13 dígitos (opcional)"
        />
        <span className="field-hint">
          Solo dígitos. Los guiones son opcionales.
        </span>
      </div>

      <div className="form-group form-full">
        <label className="form-label">Notas</label>
        <textarea
          className="form-control"
          rows={3}
          value={form.notas}
          onChange={set("notas")}
          placeholder="Descripción, edición especial, observaciones..."
        />
      </div>

      <div className="form-actions form-full">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          Cancelar
        </button>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? "Guardando..." : "Guardar"}
        </button>
      </div>
    </form>
  );
}

function LibroDetalle({ libro }) {
  return (
    <div className="detalle-grid">
      <div className="detalle-row">
        <span>Título</span>
        <strong>{libro.titulo}</strong>
      </div>
      <div className="detalle-row">
        <span>Autores</span>
        <strong>
          {(libro.autores || []).map((a) => a.nombre).join(", ") || "—"}
        </strong>
      </div>
      <div className="detalle-row">
        <span>ISBN</span>
        <strong>{libro.isbn || "—"}</strong>
      </div>
      <div className="detalle-row">
        <span>Género</span>
        <strong>{libro.genero || "—"}</strong>
      </div>
      <div className="detalle-row">
        <span>Año de publicación</span>
        <strong>{libro.anio_publicacion || "—"}</strong>
      </div>
      <div className="detalle-row">
        <span>Estado</span>
        <BoolPill
          value={!libro.retirado}
          trueLabel="Activo"
          falseLabel="Retirado"
        />
      </div>
      <div className="detalle-row">
        <span>Ejemplares totales</span>
        <strong>{libro.total_ejemplares}</strong>
      </div>
      <div className="detalle-row">
        <span>Ejemplares disponibles</span>
        <strong>{libro.ejemplares_disponibles}</strong>
      </div>
      <div className="detalle-row">
        <span>Registrado</span>
        <strong>
          <Timestamp value={libro.created_at} />
        </strong>
      </div>
      <div className="detalle-row">
        <span>Última modificación</span>
        <strong>
          <Timestamp value={libro.updated_at} />
        </strong>
      </div>
      {libro.fecha_retiro && (
        <div className="detalle-row">
          <span>Fecha de retiro</span>
          <strong>
            <Timestamp value={libro.fecha_retiro} />
          </strong>
        </div>
      )}
      {libro.notas && (
        <div className="detalle-notas">
          <span>Notas</span>
          <p>{libro.notas}</p>
        </div>
      )}
    </div>
  );
}

export function Libros({ onSuccess, onError }) {
  const [libros, setLibros] = useState([]);
  const [catalogoLibros, setCatalogoLibros] = useState([]);
  const [autores, setAutores] = useState([]);
  const [search, setSearch] = useState("");
  const [filterRetirado, setFilterRetirado] = useState("false");
  const [filterGenero, setFilterGenero] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [meta, setMeta] = useState(null);
  const [modal, setModal] = useState(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    const data = await api.getPage(
      withQuery("libros/", {
        page,
        page_size: pageSize,
        q: search,
        retirado: filterRetirado,
        genero: filterGenero,
      }),
    );
    setLibros(data.results);
    setMeta(data);
  }

  async function loadCatalogs() {
    const [l, a] = await Promise.all([
      api.get("libros/?page_size=10"),
      api.get("autores/?page_size=10"),
    ]);
    setCatalogoLibros(l);
    setAutores(a);
  }

  useEffect(() => {
    load();
  }, [page, pageSize, search, filterRetirado, filterGenero]);
  useEffect(() => {
    loadCatalogs();
  }, []);

  const generosSistema = [
    ...new Set(catalogoLibros.map((l) => l.genero).filter(Boolean)),
  ].sort();

  function handleSearch(value) {
    setSearch(value);
    setPage(1);
  }

  function handleRetirado(value) {
    setFilterRetirado(value);
    setPage(1);
  }

  function handleGenero(value) {
    setFilterGenero(value);
    setPage(1);
  }

  function handlePageSize(value) {
    setPageSize(value);
    setPage(1);
  }

  async function handleAdd(data) {
    setSaving(true);
    try {
      await api.post("libros/", data);
      onSuccess("Libro registrado correctamente.");
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
      await api.patch(`libros/${modal.id}/`, data);
      onSuccess("Libro actualizado correctamente.");
      setModal(null);
      await load();
      await loadCatalogs();
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function toggleRetirado(libro) {
    const accion = libro.retirado ? "restaurar" : "retirar";
    if (
      !confirm(
        `¿${accion.charAt(0).toUpperCase() + accion.slice(1)} el libro "${libro.titulo}"?`,
      )
    )
      return;
    try {
      await api.patch(`libros/${libro.id}/`, { retirado: !libro.retirado });
      onSuccess(
        `Libro ${libro.retirado ? "restaurado" : "retirado"} del catálogo.`,
      );
      await load();
      await loadCatalogs();
    } catch (e) {
      onError(e.message);
    }
  }

  const isEditing = modal && typeof modal === "object" && !modal.view;
  const isViewing = modal && typeof modal === "object" && modal.view;

  return (
    <div className="module">
      <div className="module-header">
        <h2 className="module-title">Libros</h2>
        <button className="btn btn-primary" onClick={() => setModal("add")}>
          Agregar libro
        </button>
      </div>

      <div className="module-toolbar">
        <SearchBar
          value={search}
          onChange={handleSearch}
          placeholder="Buscar por título, autor, ISBN o género..."
        />
        {generosSistema.length > 0 && (
          <select
            className="filter-select"
            value={filterGenero}
            onChange={(e) => handleGenero(e.target.value)}
          >
            <option value="">Todos los géneros</option>
            {generosSistema.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        )}
        <select
          className="filter-select"
          value={filterRetirado}
          onChange={(e) => handleRetirado(e.target.value)}
        >
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
                <th>Título</th>
                <th>Autores</th>
                <th>Género</th>
                <th>Año</th>
                <th>ISBN</th>
                <th>Ejemplares</th>
                <th>Disponibles</th>
                <th>Estado</th>
                <th>Registrado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {libros.length === 0 && (
                <tr>
                  <td colSpan={10} className="empty-row">
                    No se encontraron libros.
                  </td>
                </tr>
              )}
              {libros.map((l) => (
                <tr key={l.id} className={l.retirado ? "row-muted" : ""}>
                  <td>
                    <button
                      className="link-btn"
                      onClick={() => setModal({ view: l })}
                    >
                      {l.titulo}
                    </button>
                  </td>
                  <td>{(l.autores || []).map((a) => a.nombre).join(", ")}</td>
                  <td>{l.genero || "—"}</td>
                  <td>{l.anio_publicacion || "—"}</td>
                  <td>{l.isbn || "—"}</td>
                  <td className="text-center">{l.total_ejemplares}</td>
                  <td className="text-center">
                    <StatusPill
                      variant={
                        l.ejemplares_disponibles > 0 ? "success" : "secondary"
                      }
                    >
                      {l.ejemplares_disponibles}
                    </StatusPill>
                  </td>
                  <td>
                    <BoolPill
                      value={!l.retirado}
                      trueLabel="Activo"
                      falseLabel="Retirado"
                    />
                  </td>
                  <td>
                    <Timestamp value={l.created_at} />
                  </td>
                  <td className="actions-cell">
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={() => setModal(l)}
                    >
                      Editar
                    </button>
                    <button
                      className={`btn btn-sm ${l.retirado ? "btn-ghost" : "btn-warning-ghost"}`}
                      onClick={() => toggleRetirado(l)}
                    >
                      {l.retirado ? "Restaurar" : "Retirar"}
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

      <Modal
        isOpen={modal === "add"}
        onClose={() => setModal(null)}
        title="Nuevo libro"
        size="lg"
      >
        <LibroForm
          autores={autores}
          onSubmit={handleAdd}
          onCancel={() => setModal(null)}
          loading={saving}
        />
      </Modal>

      <Modal
        isOpen={isEditing}
        onClose={() => setModal(null)}
        title={`Editar: ${modal?.titulo}`}
        size="lg"
      >
        <LibroForm
          initial={modal || {}}
          autores={autores}
          onSubmit={handleEdit}
          onCancel={() => setModal(null)}
          loading={saving}
        />
      </Modal>

      <Modal
        isOpen={!!isViewing}
        onClose={() => setModal(null)}
        title={modal?.view?.titulo}
        size="md"
      >
        {isViewing && <LibroDetalle libro={modal.view} />}
      </Modal>
    </div>
  );
}

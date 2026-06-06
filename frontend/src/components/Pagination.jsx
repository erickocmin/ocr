const PAGE_SIZES = [10, 20, 50];

export function Pagination({ meta, pageSize, onPageChange, onPageSizeChange }) {
  if (!meta || meta.count === 0) return null;

  const from = (meta.page - 1) * meta.page_size + 1;
  const to = Math.min(meta.page * meta.page_size, meta.count);
  const totalPages = meta.total_pages || 1;

  return (
    <div className="pagination-bar">
      <div className="pagination-summary">
        {from}-{to} de {meta.count}
      </div>

      <div className="pagination-controls">
        <select
          className="filter-select pagination-size"
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          aria-label="Filas por página"
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>{size} por página</option>
          ))}
        </select>

        <button
          type="button"
          className="btn btn-sm btn-ghost"
          onClick={() => onPageChange(meta.page - 1)}
          disabled={!meta.previous}
        >
          Anterior
        </button>

        <span className="pagination-page">
          Página {meta.page} de {totalPages}
        </span>

        <button
          type="button"
          className="btn btn-sm btn-ghost"
          onClick={() => onPageChange(meta.page + 1)}
          disabled={!meta.next}
        >
          Siguiente
        </button>
      </div>
    </div>
  );
}

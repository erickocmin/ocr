import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { DateOnly, Timestamp } from '../../components/Timestamp';
import { StatusPill } from '../../components/StatusPill';

function StatCard({ label, value, detail, variant }) {
  return (
    <div className={`stat-card stat-${variant || 'neutral'}`}>
      <div className="stat-val">{value ?? '—'}</div>
      <div className="stat-label">{label}</div>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}

function SectionTitle({ children }) {
  return <h3 className="dash-section-title">{children}</h3>;
}

function hoy() {
  return new Date().toISOString().split('T')[0];
}

function enDias(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().split('T')[0];
}

function mesActual() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

export function Dashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [libros, socios, prestamos, ejemplares] = await Promise.all([
          api.get('libros/'),
          api.get('socios/'),
          api.get('prestamos/'),
          api.get('ejemplares/'),
        ]);

        const hoyStr   = hoy();
        const en7Str   = enDias(7);
        const mesStr   = mesActual();

        const activos      = prestamos.filter((p) => !p.fecha_devolucion);
        const vencidos     = activos.filter((p) => p.vencido);
        const porVencer    = activos.filter((p) => !p.vencido && p.fecha_vencimiento <= en7Str);
        const devueltosHoy = prestamos.filter((p) => p.fecha_devolucion && p.fecha_devolucion.startsWith(hoyStr.slice(0, 10)));
        const esteMes      = prestamos.filter((p) => p.fecha_prestamo && p.fecha_prestamo.startsWith(mesStr));
        const disponibles  = ejemplares.filter((e) => e.disponible);

        const sociosConVencidos = socios.filter((s) => s.tiene_prestamos_vencidos);

        const ultimosPrestamos = [...prestamos]
          .sort((a, b) => new Date(b.fecha_prestamo) - new Date(a.fecha_prestamo))
          .slice(0, 6);

        const proximosVencer = porVencer
          .sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento))
          .slice(0, 8);

        setData({
          totalLibros: libros.length,
          librosActivos: libros.filter((l) => !l.retirado).length,
          totalSocios: socios.length,
          sociosActivos: socios.filter((s) => s.activo).length,
          sociosConVencidos: sociosConVencidos.length,
          totalEjemplares: ejemplares.length,
          disponibles: disponibles.length,
          prestamosActivos: activos.length,
          prestamosVencidos: vencidos.length,
          proximosVencer: proximosVencer.length,
          devueltosHoy: devueltosHoy.length,
          prestamosEsteMes: esteMes.length,
          ultimosPrestamos,
          proximosVencerList: proximosVencer,
          vencidosList: vencidos.sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento)).slice(0, 6),
        });
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <div className="loading">Cargando datos del sistema...</div>;
  if (!data) return null;

  return (
    <div className="dashboard">
      <div className="module-header">
        <h2 className="module-title">Panel general</h2>
        <span className="dash-date">
          {new Date().toLocaleDateString('es-PE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
        </span>
      </div>

      {(data.prestamosVencidos > 0 || data.sociosConVencidos > 0) && (
        <div className="dash-alert-bar">
          <span className="dash-alert-dot" />
          <span>
            <strong>Requiere atención:</strong>{' '}
            {data.prestamosVencidos > 0 && (
              <span>{data.prestamosVencidos} préstamo{data.prestamosVencidos !== 1 ? 's' : ''} vencido{data.prestamosVencidos !== 1 ? 's' : ''}. </span>
            )}
            {data.sociosConVencidos > 0 && (
              <span>{data.sociosConVencidos} socio{data.sociosConVencidos !== 1 ? 's' : ''} con deuda pendiente.</span>
            )}
          </span>
        </div>
      )}

      <div className="stat-grid">
        <StatCard
          label="Libros en catálogo"
          value={data.librosActivos}
          detail={data.totalLibros !== data.librosActivos ? `${data.totalLibros - data.librosActivos} retirados` : 'Todos activos'}
          variant="blue"
        />
        <StatCard
          label="Socios activos"
          value={data.sociosActivos}
          detail={`${data.totalSocios} registrados en total`}
          variant="teal"
        />
        <StatCard
          label="Préstamos activos"
          value={data.prestamosActivos}
          detail={`${data.prestamosEsteMes} registrados este mes`}
          variant="indigo"
        />
        <StatCard
          label="Ejemplares disponibles"
          value={data.disponibles}
          detail={`de ${data.totalEjemplares} ejemplares totales`}
          variant="emerald"
        />
        <StatCard
          label="Préstamos vencidos"
          value={data.prestamosVencidos}
          detail={data.prestamosVencidos > 0 ? 'Pendientes de devolución' : 'Sin vencidos'}
          variant={data.prestamosVencidos > 0 ? 'red' : 'neutral'}
        />
        <StatCard
          label="Vencen en 7 días"
          value={data.proximosVencer}
          detail={data.devueltosHoy > 0 ? `${data.devueltosHoy} devueltos hoy` : 'Sin devoluciones hoy'}
          variant={data.proximosVencer > 0 ? 'amber' : 'neutral'}
        />
      </div>

      <div className="dash-tables">
        <div className="dash-panel">
          <SectionTitle>
            Vencimientos próximos
            {data.proximosVencerList.length > 0 && (
              <span className="dash-badge dash-badge-amber">{data.proximosVencerList.length}</span>
            )}
          </SectionTitle>
          {data.proximosVencerList.length === 0 ? (
            <div className="dash-empty">No hay préstamos próximos a vencer en los próximos 7 días.</div>
          ) : (
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Socio</th>
                  <th>Libro</th>
                  <th>Vence</th>
                </tr>
              </thead>
              <tbody>
                {data.proximosVencerList.map((p) => (
                  <tr key={p.id}>
                    <td>{p.socio_nombre}</td>
                    <td>{p.libro_titulo}</td>
                    <td><DateOnly value={p.fecha_vencimiento} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="dash-panel">
          <SectionTitle>
            Préstamos vencidos
            {data.vencidosList.length > 0 && (
              <span className="dash-badge dash-badge-red">{data.vencidosList.length}</span>
            )}
          </SectionTitle>
          {data.vencidosList.length === 0 ? (
            <div className="dash-empty">No hay préstamos vencidos pendientes.</div>
          ) : (
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Socio</th>
                  <th>Libro</th>
                  <th>Venció</th>
                </tr>
              </thead>
              <tbody>
                {data.vencidosList.map((p) => (
                  <tr key={p.id} className="dash-row-danger">
                    <td>{p.socio_nombre}</td>
                    <td>{p.libro_titulo}</td>
                    <td><DateOnly value={p.fecha_vencimiento} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="dash-panel dash-panel-full">
          <SectionTitle>Últimos préstamos registrados</SectionTitle>
          {data.ultimosPrestamos.length === 0 ? (
            <div className="dash-empty">No hay préstamos registrados aún.</div>
          ) : (
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Socio</th>
                  <th>Libro</th>
                  <th>Ejemplar</th>
                  <th>Registrado</th>
                  <th>Vencimiento</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {data.ultimosPrestamos.map((p) => (
                  <tr key={p.id}>
                    <td>{p.socio_nombre}</td>
                    <td>{p.libro_titulo}</td>
                    <td><code>{p.ejemplar_codigo}</code></td>
                    <td><Timestamp value={p.fecha_prestamo} /></td>
                    <td><DateOnly value={p.fecha_vencimiento} /></td>
                    <td>
                      {p.fecha_devolucion ? (
                        <StatusPill variant="success">Devuelto</StatusPill>
                      ) : p.vencido ? (
                        <StatusPill variant="danger">Vencido</StatusPill>
                      ) : (
                        <StatusPill variant="info">Activo</StatusPill>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

import './App.css';
import { useState } from 'react';
import { AlertContainer } from './components/Alert';
import { useAlerts } from './hooks/useAlerts';
import { Dashboard } from './modules/dashboard/Dashboard';
import { Libros } from './modules/libros/Libros';
import { Socios } from './modules/socios/Socios';
import { Prestamos } from './modules/prestamos/Prestamos';
import { Ejemplares } from './modules/ejemplares/Ejemplares';
import { Autores } from './modules/autores/Autores';

const TABS = [
  { id: 'dashboard', label: 'Panel' },
  { id: 'libros',    label: 'Libros' },
  { id: 'socios',    label: 'Socios' },
  { id: 'prestamos', label: 'Préstamos' },
  { id: 'ejemplares',label: 'Ejemplares' },
  { id: 'autores',   label: 'Autores' },
];

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const { alerts, removeAlert, success, error, warning } = useAlerts();
  const alertProps = { onSuccess: success, onError: error, onWarning: warning };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-logo">
          <div className="header-logo-mark">BIB</div>
          <span className="header-name">Biblioteca Comunitaria</span>
          <div className="header-divider" />
          <span className="header-sub">Sistema de gestión</span>
        </div>
      </header>

      <nav className="nav-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab-btn ${activeTab === t.id ? 'tab-active' : ''}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="main-content">
        {activeTab === 'dashboard'  && <Dashboard />}
        {activeTab === 'libros'     && <Libros {...alertProps} />}
        {activeTab === 'socios'     && <Socios {...alertProps} />}
        {activeTab === 'prestamos'  && <Prestamos {...alertProps} />}
        {activeTab === 'ejemplares' && <Ejemplares {...alertProps} />}
        {activeTab === 'autores'    && <Autores {...alertProps} />}
      </main>

      <AlertContainer alerts={alerts} onDismiss={removeAlert} />
    </div>
  );
}

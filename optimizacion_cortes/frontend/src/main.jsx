import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api.js";
import { Despiece, Parametros } from "./Configuracion.jsx";
import Inventario from "./Inventario.jsx";
import Planeacion, { RunView } from "./Planeacion.jsx";
import { fmt, pct } from "./ui.jsx";

function Historial() {
  const [runs, setRuns] = useState([]);
  const [sel, setSel] = useState(null);
  useEffect(() => { api.corridas().then(setRuns); }, []);
  if (sel) return (
    <>
      <button className="btn" onClick={() => setSel(null)} style={{ marginBottom: 12 }}>← Volver al historial</button>
      <RunView run={sel} />
    </>);
  return (
    <div className="card">
      <h2>Historial de corridas</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Corrida</th><th>Fecha (UTC)</th><th>Estado</th><th className="num">Hojas</th>
            <th className="num">Aprovechamiento</th><th className="num">Merma</th><th className="num">Órdenes cubiertas</th><th /></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td><strong>{r.etiqueta}</strong></td><td>{r.creado}</td>
                <td><span className={`badge ${r.estado === "confirmada" ? "ok" : r.estado === "simulada" ? "warn" : "off"}`}>{r.estado}</span></td>
                <td className="num">{fmt(r.metricas.total_hojas, 0)}</td><td className="num">{pct(r.metricas.aprovechamiento)}</td>
                <td className="num">{pct(r.metricas.merma_neta)}</td>
                <td className="num">{r.metricas.ordenes_cubiertas} / {r.metricas.ordenes_total}</td>
                <td><button className="btn sm" onClick={() => api.corrida(r.id).then(setSel)}>Ver planos</button></td>
              </tr>))}
            {!runs.length && <tr><td colSpan="8" className="empty">Todavía no hay corridas.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>);
}

const TABS = [
  ["plan", "Planeación"], ["inv", "Inventario"], ["hist", "Historial"], ["desp", "Despiece"], ["param", "Parámetros"],
];

function App() {
  const [tab, setTab] = useState("plan");
  const [stock, setStock] = useState(null);
  const refresh = useCallback(() => api.estado().then(setStock).catch(() => {}), []);
  useEffect(() => { refresh(); }, [refresh, tab]);
  return (
    <>
      <header className="top">
        <h1>SprintWindow<small>Optimización de corte de PVC</small></h1>
        <nav className="tabs">
          {TABS.map(([k, l]) => <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>)}
        </nav>
        {stock && <span className="stock-pill">{stock.hojas} hojas · {stock.retazos} retazos · {stock.ordenes} órdenes en cola</span>}
      </header>
      <main>
        {tab === "plan" && <Planeacion onStockChanged={refresh} />}
        {tab === "inv" && <Inventario onStockChanged={refresh} />}
        {tab === "hist" && <Historial />}
        {tab === "desp" && <Despiece />}
        {tab === "param" && <Parametros />}
      </main>
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);

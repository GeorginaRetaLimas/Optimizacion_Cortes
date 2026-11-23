import { useEffect, useState } from "react";
import { api, getPin, setPin } from "./api.js";

export const fmt = (v, d = 1) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : Number(v).toLocaleString("es-MX", { maximumFractionDigits: d, minimumFractionDigits: 0 });

export const pct = (v) => `${fmt(v, 1)} %`;

export function Modal({ title, onClose, children, wide }) {
  useEffect(() => {
    const h = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-label={title}>
        <div className="row">
          <h2 style={{ margin: 0 }}>{title}</h2>
          <span className="spacer" />
          <button className="btn icon" onClick={onClose} aria-label="Cerrar">✕</button>
        </div>
        <div style={{ marginTop: 14 }}>{children}</div>
      </div>
    </div>
  );
}

export function Errors({ list }) {
  if (!list || !list.length) return null;
  const [head, ...rest] = list;
  return (
    <div className="alert err">
      <strong>{head}</strong>
      {rest.length > 0 && <ul>{rest.map((x, i) => <li key={i}>{x}</li>)}</ul>}
    </div>
  );
}

/** Pide el PIN de administrador una vez por sesión del navegador. */
export function AdminGate({ children }) {
  const [ok, setOk] = useState(false);
  const [pin, setPinState] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    const p = getPin();
    if (p) api.verificarPin(p).then((r) => setOk(r.ok)).catch(() => {});
  }, []);
  if (ok) return children;
  const submit = async (e) => {
    e.preventDefault();
    const r = await api.verificarPin(pin);
    if (r.ok) { setPin(pin); setOk(true); } else setErr("PIN incorrecto");
  };
  return (
    <div className="card" style={{ maxWidth: 420 }}>
      <h2>Acceso de administrador</h2>
      <p className="muted">Esta sección modifica la configuración del proceso. Ingrese el PIN de administrador.</p>
      <form onSubmit={submit} className="row">
        <input type="password" value={pin} onChange={(e) => setPinState(e.target.value)} placeholder="PIN"
          autoFocus style={{ padding: 8, border: "1px solid #c7ced6", borderRadius: 6 }} />
        <button className="btn primary">Entrar</button>
      </form>
      {err && <div className="alert err">{err}</div>}
    </div>
  );
}

/** Mini gráfica de convergencia del algoritmo genético. */
export function Sparkline({ values, width = 220, height = 46 }) {
  if (!values || values.length < 2) return null;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) =>
    `${(i / (values.length - 1)) * (width - 4) + 2},${height - 2 - ((v - min) / span) * (height - 4)}`);
  return (
    <svg className="spark" width={width} height={height} role="img" aria-label="Convergencia de la aptitud">
      <polyline points={pts.join(" ")} fill="none" stroke="#457b9d" strokeWidth="2" />
    </svg>
  );
}

/** Selector de archivo + validación previa + carga (RF-02).
 *  Con autoLoad el servidor valida y, solo si no hay errores, carga en el
 *  mismo paso (un solo clic, RNF-03). */
export function Importer({ kind, label, onDone, autoLoad = false }) {
  const [file, setFile] = useState(null);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const run = async (f, confirmar) => {
    setBusy(true); setErr(null);
    try {
      const r = await api.importar(kind, f, confirmar);
      setRes(r);
      if (r.cargado) onDone && onDone(r);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div>
      <div className="row">
        <label className="btn primary">
          {label}
          <input type="file" accept=".csv,.xlsx" hidden onChange={(e) => {
            const f = e.target.files[0];
            e.target.value = "";
            if (f) { setFile(f); setRes(null); run(f, autoLoad); }
          }} />
        </label>
        <a className="btn sm" href={`/api/plantillas/${kind}.xlsx`}>Plantilla .xlsx</a>
        <a className="btn sm" href={`/api/plantillas/${kind}.csv`}>Plantilla .csv</a>
        {busy && <span className="muted">Validando…</span>}
      </div>
      {err && <div className="alert err">{err}</div>}
      {res && !res.cargado && (
        res.errores.length ? (
          <div className="alert err">
            <strong>{file?.name}: {res.errores.length} error(es). Corrija el archivo; no se cargó nada.</strong>
            <div className="table-wrap" style={{ maxHeight: 220, marginTop: 8 }}>
              <table>
                <thead><tr><th>Fila</th><th>Campo</th><th>Problema</th></tr></thead>
                <tbody>{res.errores.map((x, i) => (
                  <tr key={i}><td>{x.fila || "—"}</td><td>{x.campo}</td><td>{x.mensaje}</td></tr>))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="alert ok row">
            <span><strong>{file?.name}</strong>: {res.validas} fila(s) válidas, sin errores.</span>
            <span className="spacer" />
            <button className="btn ok" disabled={busy} onClick={() => run(file, true)}>Cargar al sistema</button>
          </div>
        )
      )}
      {res && res.cargado && (
        <div className="alert ok">
          Carga completa: {res.nuevos !== undefined ? `${res.nuevos} nuevo(s), ${res.actualizados} actualizado(s)` : `${res.validas} registro(s)`}.
        </div>
      )}
    </div>
  );
}

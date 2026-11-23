import { useEffect, useState } from "react";
import { api, errorList } from "./api.js";
import { AdminGate, Errors, fmt } from "./ui.jsx";

const FIELDS = [
  { legend: "Proceso de corte", items: [
    ["kerf", "Grosor de corte / kerf (mm)", "Separación mínima entre piezas (RN-03)"],
    ["refilado", "Margen de refilado por lado (mm)", "Debe ser ≥ kerf"],
    ["retazo_min_largo", "Retazo aprovechable: lado largo mínimo (mm)", "L_min (RN-06)"],
    ["retazo_min_ancho", "Retazo aprovechable: lado corto mínimo (mm)", "A_min (RN-06)"],
    ["modo_corte", "Tipo de corte", "RN-05", ["guillotina", "libre"]],
  ] },
  { legend: "Función de aptitud", items: [
    ["w1", "w1 · peso de la merma", ""],
    ["w2", "w2 · peso de la prioridad de cola frente al ahorro", ""],
    ["w3", "w3 · bonificación de retazos grandes", ""],
    ["w4", "w4 · peso del consumo de material", "Evita fragmentar en muchas hojas"],
    ["ventana_tolerancia", "Ventana de tolerancia de la cola (posiciones)", "RN-04"],
    ["peso_urgente", "Peso P_i de una orden urgente", "Normal = 1"],
  ] },
  { legend: "Algoritmo genético", items: [
    ["poblacion", "Tamaño de población", ""],
    ["generaciones", "Generaciones máximas (G_max)", ""],
    ["estancamiento", "Generaciones sin mejora para parar (X)", ""],
    ["tiempo_max", "Tiempo límite (T_max, s)", "RNF-01: ≤ 30 s"],
    ["cruce", "Operador de cruce", "", ["OX", "PMX"]],
    ["prob_cruce", "Probabilidad de cruce", "0 – 1"],
    ["prob_mutacion", "Probabilidad de mutación", "0 – 1"],
    ["semilla", "Semilla aleatoria (vacío = aleatoria)", "Para resultados reproducibles"],
  ] },
];

/** RF-09: parámetros configurables sin tocar código. */
export function Parametros() {
  const [p, setP] = useState(null);
  const [errs, setErrs] = useState(null);
  const [ok, setOk] = useState(false);
  useEffect(() => { api.parametros().then(setP); }, []);
  if (!p) return null;
  const save = async (e) => {
    e.preventDefault(); setErrs(null); setOk(false);
    try { setP(await api.guardarParametros(p)); setOk(true); } catch (err) { setErrs(errorList(err)); }
  };
  return (
    <AdminGate>
      <form className="card" onSubmit={save}>
        <h2>Parámetros de proceso y del motor</h2>
        {FIELDS.map((g) => (
          <fieldset key={g.legend}>
            <legend>{g.legend}</legend>
            <div className="form">
              {g.items.map(([k, label, hint, opts]) => (
                <label key={k}>{label}{hint && <span className="hint">{hint}</span>}
                  {opts ? (
                    <select value={p[k]} onChange={(e) => setP({ ...p, [k]: e.target.value })}>
                      {opts.map((o) => <option key={o} value={o}>{o === "libre" ? "Anidamiento libre (CNC)" : o === "guillotina" ? "Guillotina (sierra)" : o}</option>)}
                    </select>
                  ) : (
                    <input type="number" step="any" value={p[k] ?? ""} onChange={(e) => setP({ ...p, [k]: e.target.value })} />
                  )}
                </label>))}
            </div>
          </fieldset>))}
        <Errors list={errs} />
        {ok && <div className="alert ok">Parámetros guardados. Las simulaciones previas quedaron obsoletas.</div>}
        <div className="row"><span className="spacer" /><button className="btn primary">Guardar parámetros</button></div>
      </form>
    </AdminGate>
  );
}

/** RF-06: reglas de despiece por tipo de persiana. */
export function Despiece() {
  const [tipos, setTipos] = useState([]);
  const [sel, setSel] = useState(null);
  const [t, setT] = useState(null);
  const [test, setTest] = useState({ W: 1500, H: 1800 });
  const [preview, setPreview] = useState(null);
  const [errs, setErrs] = useState(null);
  const [ok, setOk] = useState(false);
  const load = (pick) => api.tipos().then((ts) => {
    setTipos(ts);
    const s = ts.find((x) => x.nombre === pick) || ts[0];
    if (s) { setSel(s.nombre); setT(structuredClone(s)); } else { setSel(null); setT(null); }
  });
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!t) return;
    const h = setTimeout(() => api.despiece({ tipo: t, ancho_final: test.W, alto_final: test.H, cantidad: 1 })
      .then((r) => setPreview(r)).catch((e) => setPreview({ error: e.message })), 300);
    return () => clearTimeout(h);
  }, [t, test]);

  const holg = t ? Object.entries(t.holguras || {}) : [];
  const setHolg = (entries) => setT({ ...t, holguras: Object.fromEntries(entries) });
  const setComp = (i, k, v) => setT({ ...t, componentes: t.componentes.map((c, j) => (j === i ? { ...c, [k]: v } : c)) });
  const save = async () => {
    setErrs(null); setOk(false);
    try {
      const clean = { ...t, holguras: Object.fromEntries(holg.filter(([k]) => k).map(([k, v]) => [k, Number(v)])) };
      await api.guardarTipo(clean); setOk(true); load(clean.nombre);
    } catch (e) { setErrs(errorList(e)); }
  };
  const nuevo = () => {
    const nombre = window.prompt("Nombre del nuevo tipo de persiana:");
    if (!nombre) return;
    setSel(nombre);
    setT({ nombre, descripcion: "", holguras: {}, componentes: [{ nombre: "Pieza", ancho: "W", alto: "H", cantidad: "1", veta: "ancho" }] });
  };
  const borrar = async () => {
    if (!window.confirm(`¿Eliminar el tipo ${t.nombre}? Las órdenes ya capturadas conservan sus piezas.`)) return;
    await api.borrarTipo(t.nombre); load();
  };

  return (
    <AdminGate>
      <div className="card">
        <div className="row">
          <h2 style={{ margin: 0 }}>Despiece por tipo de persiana</h2>
          <span className="spacer" />
          <div className="subtabs" style={{ margin: 0 }}>
            {tipos.map((x) => <button key={x.nombre} className={sel === x.nombre ? "active" : ""}
              onClick={() => { setSel(x.nombre); setT(structuredClone(x)); setOk(false); setErrs(null); }}>{x.nombre}</button>)}
          </div>
          <button className="btn sm" onClick={nuevo}>+ Tipo</button>
        </div>
        <div className="alert warn">Las fórmulas iniciales son de referencia. Ingeniería de Procesos debe capturar aquí las medidas y holguras reales de SprintWindow.</div>
        {t && <>
          <p className="muted">Variables disponibles: <code>W</code> (ancho final), <code>H</code> (alto final), las holguras
            de abajo y las funciones <code>ceil floor round min max</code>.</p>
          <div className="form">
            <label className="full">Descripción<input value={t.descripcion || ""} onChange={(e) => setT({ ...t, descripcion: e.target.value })} /></label>
          </div>
          <h3>Holguras de ensamble (mm)</h3>
          <table style={{ maxWidth: 520 }}>
            <thead><tr><th>Nombre</th><th>Valor</th><th /></tr></thead>
            <tbody>{holg.map(([k, v], i) => (
              <tr key={i}>
                <td><input value={k} onChange={(e) => setHolg(holg.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))} /></td>
                <td><input type="number" step="any" value={v} onChange={(e) => setHolg(holg.map((x, j) => (j === i ? [x[0], e.target.value] : x)))} /></td>
                <td><button className="btn icon danger" onClick={() => setHolg(holg.filter((_, j) => j !== i))}>✕</button></td>
              </tr>))}</tbody>
          </table>
          <button className="btn sm" style={{ marginTop: 6 }} onClick={() => setHolg([...holg, [`holgura_${holg.length + 1}`, 0]])}>+ Holgura</button>
          <h3>Componentes</h3>
          <table>
            <thead><tr><th>Componente</th><th>Ancho =</th><th>Alto =</th><th>Cantidad por persiana =</th><th>Veta paralela a</th><th /></tr></thead>
            <tbody>{t.componentes.map((c, i) => (
              <tr key={i}>
                <td><input value={c.nombre} onChange={(e) => setComp(i, "nombre", e.target.value)} /></td>
                <td><input value={c.ancho} onChange={(e) => setComp(i, "ancho", e.target.value)} /></td>
                <td><input value={c.alto} onChange={(e) => setComp(i, "alto", e.target.value)} /></td>
                <td><input value={c.cantidad} onChange={(e) => setComp(i, "cantidad", e.target.value)} /></td>
                <td><select value={c.veta || "ancho"} onChange={(e) => setComp(i, "veta", e.target.value)}>
                  <option value="ancho">Ancho</option><option value="alto">Alto</option></select></td>
                <td><button className="btn icon danger" disabled={t.componentes.length === 1}
                  onClick={() => setT({ ...t, componentes: t.componentes.filter((_, j) => j !== i) })}>✕</button></td>
              </tr>))}</tbody>
          </table>
          <button className="btn sm" style={{ marginTop: 6 }}
            onClick={() => setT({ ...t, componentes: [...t.componentes, { nombre: "", ancho: "W", alto: "H", cantidad: "1", veta: "ancho" }] })}>+ Componente</button>
          <h3>Prueba</h3>
          <div className="row">
            <label className="f">W (mm)<input type="number" value={test.W} onChange={(e) => setTest({ ...test, W: e.target.value })} /></label>
            <label className="f">H (mm)<input type="number" value={test.H} onChange={(e) => setTest({ ...test, H: e.target.value })} /></label>
          </div>
          {preview && (preview.error ? <div className="alert err">{preview.error}</div> : (
            <table style={{ marginTop: 8, maxWidth: 700 }}>
              <thead><tr><th>Componente</th><th className="num">Ancho</th><th className="num">Alto</th><th className="num">Cantidad</th></tr></thead>
              <tbody>{preview.map((p, i) => <tr key={i}><td>{p.componente}</td><td className="num">{fmt(p.ancho)}</td>
                <td className="num">{fmt(p.alto)}</td><td className="num">{p.cantidad}</td></tr>)}</tbody>
            </table>))}
          <Errors list={errs} />
          {ok && <div className="alert ok">Tipo guardado.</div>}
          <div className="row" style={{ marginTop: 14 }}>
            {tipos.some((x) => x.nombre === t.nombre) && <button className="btn danger" onClick={borrar}>Eliminar tipo</button>}
            <span className="spacer" />
            <button className="btn primary" onClick={save}>Guardar tipo</button>
          </div>
        </>}
      </div>
    </AdminGate>
  );
}

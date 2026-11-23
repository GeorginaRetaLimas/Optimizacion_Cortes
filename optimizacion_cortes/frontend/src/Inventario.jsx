import { useCallback, useEffect, useState } from "react";
import { api, errorList } from "./api.js";
import { Errors, Importer, Modal, fmt } from "./ui.jsx";

const EMPTY = { codigo: "", ancho: "", alto: "", espesor: "", color: "", textura: "", veta_direccional: false,
  cantidad: 1, costo_unitario: "" };

function LotForm({ initial, retazo, onClose, onSaved }) {
  const [l, setL] = useState(initial ? { ...initial, veta_direccional: !!initial.veta_direccional,
    costo_unitario: initial.costo_unitario ?? "" } : { ...EMPTY });
  const [errs, setErrs] = useState(null);
  const set = (k) => (e) => setL({ ...l, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const save = async (e) => {
    e.preventDefault();
    setErrs(null);
    try {
      const body = { ...l, es_retazo: retazo };
      onSaved(initial ? await api.editarLote(initial.id, body) : await api.crearLote(body));
    } catch (err) { setErrs(errorList(err)); }
  };
  const what = retazo ? "retazo" : "lote de hojas";
  return (
    <Modal title={initial ? `Editar ${what} ${initial.codigo}` : `Nuevo ${what}`} onClose={onClose}>
      <form onSubmit={save}>
        <div className="form">
          <label>Código de lote<input required value={l.codigo} onChange={set("codigo")} autoFocus /></label>
          <label>Ancho (mm)<input required type="number" min="1" step="0.1" value={l.ancho} onChange={set("ancho")} /></label>
          <label>Alto (mm)<input required type="number" min="1" step="0.1" value={l.alto} onChange={set("alto")} /></label>
          <label>Espesor (mm)<input required type="number" min="0.1" step="0.1" value={l.espesor} onChange={set("espesor")} /></label>
          <label>Color<input required value={l.color} onChange={set("color")} /></label>
          <label>Textura<input required value={l.textura} onChange={set("textura")} /></label>
          <label>Cantidad disponible<input required type="number" min="0" step="1" value={l.cantidad} onChange={set("cantidad")} /></label>
          <label>Costo unitario (opcional)<input type="number" min="0" step="0.01" value={l.costo_unitario} onChange={set("costo_unitario")} /></label>
          <label className="check full"><input type="checkbox" checked={l.veta_direccional} onChange={set("veta_direccional")} />
            Textura con veta direccional (la veta corre a lo largo del <strong>ancho</strong>; las piezas no se rotan)</label>
        </div>
        <Errors list={errs} />
        <div className="row" style={{ marginTop: 16 }}>
          <span className="spacer" />
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary">Guardar</button>
        </div>
      </form>
    </Modal>
  );
}

export default function Inventario({ onStockChanged }) {
  const [tab, setTab] = useState("hojas");
  const [lotes, setLotes] = useState([]);
  const [form, setForm] = useState(null);
  const [err, setErr] = useState(null);
  const retazo = tab === "retazos";
  const load = useCallback(() => api.lotes().then(setLotes).catch((e) => setErr(e.message)), []);
  useEffect(() => { load(); }, [load]);
  const changed = () => { load(); onStockChanged && onStockChanged(); };
  const list = lotes.filter((l) => !!l.es_retazo === retazo);
  const remove = async (l) => {
    if (!window.confirm(`¿Eliminar ${l.codigo} del inventario?`)) return;
    await api.borrarLote(l.id);
    changed();
  };
  return (
    <>
      <div className="card">
        <div className="row">
          <h2 style={{ margin: 0 }}>Inventario de PVC</h2>
          <span className="spacer" />
          <div className="subtabs" style={{ margin: 0 }}>
            <button className={tab === "hojas" ? "active" : ""} onClick={() => setTab("hojas")}>Hojas</button>
            <button className={tab === "retazos" ? "active" : ""} onClick={() => setTab("retazos")}>Retazos</button>
          </div>
        </div>
        {retazo && <p className="muted">Los retazos se consumen antes de abrir hojas nuevas (RF-03). Los retazos recuperables de cada corte confirmado se dan de alta aquí automáticamente.</p>}
        <div className="toolbar" style={{ marginTop: 12 }}>
          <button className="btn primary" onClick={() => setForm("new")}>+ {retazo ? "Registrar retazo" : "Nuevo lote"}</button>
        </div>
        {err && <div className="alert err">{err}</div>}
        <div className="table-wrap">
          <table>
            <thead><tr><th>Código</th><th className="num">Ancho</th><th className="num">Alto</th><th className="num">Espesor</th>
              <th>Color</th><th>Textura</th><th>Veta</th><th className="num">Cantidad</th><th className="num">Costo unit.</th>
              <th>Origen</th><th /></tr></thead>
            <tbody>
              {list.map((l) => (
                <tr key={l.id}>
                  <td><strong>{l.codigo}</strong></td><td className="num">{fmt(l.ancho)}</td><td className="num">{fmt(l.alto)}</td>
                  <td className="num">{fmt(l.espesor)}</td><td>{l.color}</td><td>{l.textura}</td>
                  <td>{l.veta_direccional ? <span className="badge veta">Direccional</span> : "—"}</td>
                  <td className="num">{l.cantidad}</td><td className="num">{l.costo_unitario ? `$${fmt(l.costo_unitario, 2)}` : "—"}</td>
                  <td className="muted">{l.origen}</td>
                  <td className="row" style={{ flexWrap: "nowrap" }}>
                    <button className="btn icon" onClick={() => setForm(l)} aria-label="Editar">✎</button>
                    <button className="btn icon danger" onClick={() => remove(l)} aria-label="Eliminar">✕</button>
                  </td>
                </tr>))}
              {!list.length && <tr><td colSpan="11" className="empty">Sin registros.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      {!retazo && (
        <div className="card">
          <h2>Carga masiva (.csv / .xlsx)</h2>
          <p className="muted">Columnas: codigo, ancho, alto, espesor, color, textura, veta_direccional (sí/no), cantidad, costo_unitario.
            El archivo se valida completo antes de cargar; si un código ya existe, se actualiza.</p>
          <Importer kind="lotes" label="Seleccionar archivo…" onDone={changed} />
        </div>)}
      {form && <LotForm initial={form === "new" ? null : form} retazo={retazo} onClose={() => setForm(null)}
        onSaved={() => { setForm(null); changed(); }} />}
    </>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorList } from "./api.js";
import { Errors, Modal, fmt } from "./ui.jsx";

const EMPTY = {
  numero: "", cliente: "", tipo_persiana: "", ancho_final: "", alto_final: "", cantidad: 1,
  color: "", textura: "", espesor: "", prioridad: "Normal",
};

/** RF-04 / RF-06: captura de una orden con despiece automático o piezas manuales. */
export function OrderForm({ initial, tipos, lotes, onSaved, onClose }) {
  const [o, setO] = useState(() => initial ? { ...initial } : { ...EMPTY, tipo_persiana: tipos[0]?.nombre || "Manual" });
  const [piezas, setPiezas] = useState(() =>
    initial && initial.tipo_persiana === "Manual"
      ? initial.piezas.map(({ componente, ancho, alto, cantidad, veta }) => ({ componente, ancho, alto, cantidad, veta }))
      : [{ componente: "Pieza 1", ancho: "", alto: "", cantidad: 1, veta: "ancho" }]);
  const [preview, setPreview] = useState(null);
  const [errs, setErrs] = useState(null);
  const [busy, setBusy] = useState(false);
  const manual = o.tipo_persiana === "Manual";
  const set = (k) => (e) => setO({ ...o, [k]: e.target.value });
  const locked = initial && initial.piezas?.some((p) => p.cortadas > 0);

  const mats = useMemo(() => {
    const c = new Set(), t = new Set(), e = new Set();
    lotes.forEach((l) => { c.add(l.color); t.add(l.textura); e.add(l.espesor); });
    return { c: [...c], t: [...t], e: [...e] };
  }, [lotes]);
  const matOk = !o.color || lotes.some((l) =>
    l.color.toLowerCase() === o.color.trim().toLowerCase() &&
    l.textura.toLowerCase() === o.textura.trim().toLowerCase() &&
    Number(l.espesor) === Number(o.espesor) && l.cantidad > 0);

  useEffect(() => {
    if (manual || !o.ancho_final || !o.alto_final) { setPreview(null); return; }
    const t = setTimeout(() => {
      api.despiece({ tipo_persiana: o.tipo_persiana, ancho_final: o.ancho_final, alto_final: o.alto_final,
        cantidad: o.cantidad || 1 })
        .then(setPreview).catch((e) => setPreview({ error: e.message }));
    }, 250);
    return () => clearTimeout(t);
  }, [o.tipo_persiana, o.ancho_final, o.alto_final, o.cantidad, manual]);

  const save = async (e) => {
    e.preventDefault();
    setBusy(true); setErrs(null);
    const payload = { ...o };
    if (manual) payload.piezas = piezas;
    try {
      const r = initial ? await api.editarOrden(initial.id, payload) : await api.crearOrden(payload);
      onSaved(r);
    } catch (err) { setErrs(errorList(err)); } finally { setBusy(false); }
  };
  const setPieza = (i, k, v) => setPiezas(piezas.map((p, j) => (j === i ? { ...p, [k]: v } : p)));

  return (
    <Modal title={initial ? `Editar orden ${initial.numero}` : "Nueva orden de producción"} onClose={onClose}>
      {locked && <div className="alert warn">Esta orden ya tiene piezas cortadas: solo puede cambiar cliente y prioridad.</div>}
      <form onSubmit={save}>
        <div className="form">
          <label>Número de orden<input required value={o.numero} onChange={set("numero")} disabled={locked} autoFocus /></label>
          <label>Cliente / Lote<input value={o.cliente} onChange={set("cliente")} /></label>
          <label>Prioridad
            <select value={o.prioridad} onChange={set("prioridad")}>
              <option>Normal</option><option>Urgente</option>
            </select>
          </label>
          <label>Tipo de persiana
            <select value={o.tipo_persiana} onChange={set("tipo_persiana")} disabled={locked}>
              {tipos.map((t) => <option key={t.nombre}>{t.nombre}</option>)}
              <option value="Manual">Manual (piezas con medida)</option>
            </select>
          </label>
          <label>Color<input required list="dl-color" value={o.color} onChange={set("color")} disabled={locked} /></label>
          <label>Textura<input required list="dl-tex" value={o.textura} onChange={set("textura")} disabled={locked} /></label>
          <label>Espesor (mm)<input required type="number" step="0.1" min="0.1" list="dl-esp" value={o.espesor}
            onChange={set("espesor")} disabled={locked} /></label>
          {!manual && <>
            <label>Ancho final (mm)<input required type="number" min="1" step="0.1" value={o.ancho_final} onChange={set("ancho_final")} disabled={locked} /></label>
            <label>Alto final (mm)<input required type="number" min="1" step="0.1" value={o.alto_final} onChange={set("alto_final")} disabled={locked} /></label>
            <label>Cantidad de persianas<input required type="number" min="1" step="1" value={o.cantidad} onChange={set("cantidad")} disabled={locked} /></label>
          </>}
        </div>
        <datalist id="dl-color">{mats.c.map((x) => <option key={x} value={x} />)}</datalist>
        <datalist id="dl-tex">{mats.t.map((x) => <option key={x} value={x} />)}</datalist>
        <datalist id="dl-esp">{mats.e.map((x) => <option key={x} value={x} />)}</datalist>
        {o.color && o.textura && o.espesor && !matOk && (
          <div className="alert warn">No hay hojas en inventario con exactamente ese color, textura y espesor (RN-01). La orden quedará pendiente por falta de material.</div>
        )}

        {manual ? (
          <>
            <h3>Piezas</h3>
            <table>
              <thead><tr><th>Componente</th><th>Ancho (mm)</th><th>Alto (mm)</th><th>Cantidad</th>
                <th title="Dimensión que debe correr paralela a la veta">Veta paralela a</th><th /></tr></thead>
              <tbody>
                {piezas.map((p, i) => (
                  <tr key={i}>
                    <td><input value={p.componente} onChange={(e) => setPieza(i, "componente", e.target.value)} disabled={locked} /></td>
                    <td><input required type="number" min="1" step="0.1" value={p.ancho} onChange={(e) => setPieza(i, "ancho", e.target.value)} disabled={locked} /></td>
                    <td><input required type="number" min="1" step="0.1" value={p.alto} onChange={(e) => setPieza(i, "alto", e.target.value)} disabled={locked} /></td>
                    <td><input required type="number" min="1" step="1" value={p.cantidad} onChange={(e) => setPieza(i, "cantidad", e.target.value)} disabled={locked} /></td>
                    <td><select value={p.veta} onChange={(e) => setPieza(i, "veta", e.target.value)} disabled={locked}>
                      <option value="ancho">Ancho</option><option value="alto">Alto</option></select></td>
                    <td><button type="button" className="btn icon danger" disabled={locked || piezas.length === 1}
                      onClick={() => setPiezas(piezas.filter((_, j) => j !== i))}>✕</button></td>
                  </tr>))}
              </tbody>
            </table>
            {!locked && <button type="button" className="btn sm" style={{ marginTop: 8 }}
              onClick={() => setPiezas([...piezas, { componente: `Pieza ${piezas.length + 1}`, ancho: "", alto: "", cantidad: 1, veta: "ancho" }])}>
              + Agregar pieza</button>}
          </>
        ) : preview && (
          <>
            <h3>Despiece automático (RF-06)</h3>
            {preview.error ? <div className="alert err">{preview.error}</div> : (
              <table>
                <thead><tr><th>Componente</th><th className="num">Ancho</th><th className="num">Alto</th>
                  <th className="num">Cantidad</th><th>Veta paralela a</th></tr></thead>
                <tbody>{preview.map((p, i) => (
                  <tr key={i}><td>{p.componente}</td><td className="num">{fmt(p.ancho)}</td><td className="num">{fmt(p.alto)}</td>
                    <td className="num">{p.cantidad}</td><td>{p.veta}</td></tr>))}</tbody>
              </table>)}
          </>
        )}
        <Errors list={errs} />
        <div className="row" style={{ marginTop: 16 }}>
          <span className="spacer" />
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" disabled={busy}>{initial ? "Guardar cambios" : "Agregar a la cola"}</button>
        </div>
      </form>
    </Modal>
  );
}

/** RF-05: cola con reordenamiento por botones y arrastrar y soltar. */
export function Queue({ orders, onReorder, onEdit, onDelete, busy }) {
  const [drag, setDrag] = useState(null);
  const [over, setOver] = useState(null);
  const dragRef = useRef(null);
  const move = (from, to) => {
    if (from === null || from === undefined || Number.isNaN(from)) return;
    if (to < 0 || to >= orders.length || from === to) return;
    const ids = orders.map((o) => o.id);
    const [x] = ids.splice(from, 1);
    ids.splice(to, 0, x);
    onReorder(ids);
  };
  if (!orders.length) return <div className="empty">La cola está vacía. Agregue o importe órdenes.</div>;
  return (
    <ul className="queue">
      {orders.map((o, i) => (
        <li key={o.id} draggable={!busy}
          className={`${drag === i ? "dragging" : ""} ${over === i && drag !== i ? "over" : ""}`}
          onDragStart={(e) => {
            dragRef.current = i; setDrag(i);
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", String(i));
          }}
          onDragOver={(e) => { e.preventDefault(); setOver(i); }}
          onDragLeave={() => setOver(null)}
          onDrop={(e) => {
            e.preventDefault();
            const raw = e.dataTransfer.getData("text/plain");
            move(raw !== "" ? Number(raw) : dragRef.current, i);
            dragRef.current = null; setDrag(null); setOver(null);
          }}
          onDragEnd={() => { setDrag(null); setOver(null); }}>
          <span className="handle" title="Arrastrar para reordenar">⠿</span>
          <span className="pos">{i + 1}</span>
          <div>
            <div className="row" style={{ gap: 6 }}>
              <span className="title">{o.numero}</span>
              {o.prioridad === "Urgente" && <span className="badge urg">URGENTE</span>}
              <span className="muted">{o.cliente}</span>
            </div>
            <div className="muted">
              {o.tipo_persiana}{o.tipo_persiana !== "Manual" && ` ${fmt(o.ancho_final, 0)}×${fmt(o.alto_final, 0)} ×${o.cantidad}`}
              {" · "}{o.color} / {o.textura} / {fmt(o.espesor)} mm · {o.piezas_pendientes} pieza(s)
              {o.piezas_pendientes < o.total_piezas && ` de ${o.total_piezas}`}
            </div>
          </div>
          <div className="actions">
            <button className="btn icon" disabled={busy || i === 0} onClick={() => move(i, i - 1)} aria-label="Subir">▲</button>
            <button className="btn icon" disabled={busy || i === orders.length - 1} onClick={() => move(i, i + 1)} aria-label="Bajar">▼</button>
            <button className="btn icon" onClick={() => onEdit(o)} aria-label="Editar">✎</button>
            <button className="btn icon danger" onClick={() => onDelete(o)} aria-label="Eliminar">✕</button>
          </div>
        </li>
      ))}
    </ul>
  );
}

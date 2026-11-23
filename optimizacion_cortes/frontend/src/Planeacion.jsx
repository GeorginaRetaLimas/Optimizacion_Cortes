import { useCallback, useEffect, useState } from "react";
import { api, errorList } from "./api.js";
import { OrderForm, Queue } from "./Ordenes.jsx";
import { Errors, Importer, Modal, Sparkline, fmt, pct } from "./ui.jsx";

const QUICK_SECONDS = 5; // simulación rápida tras reordenar la cola (RF-05)

function Delta({ now, before, better = "up", unit = " pts" }) {
  if (before === undefined || before === null) return null;
  const d = now - before;
  if (Math.abs(d) < 0.05) return <div className="d">sin cambio</div>;
  const good = better === "up" ? d > 0 : d < 0;
  return <div className={`d ${good ? "up" : "down"}`}>{d > 0 ? "+" : ""}{fmt(d, 1)}{unit} vs. antes</div>;
}

/** RF-10: métricas, planos y confirmación de una corrida. */
export function RunView({ run, previous, onConfirmed }) {
  const [view, setView] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [errs, setErrs] = useState(null);
  const m = run.metricas, p = previous || {};
  const confirm = async () => {
    if (!window.confirm(`¿Confirmar la orden de corte ${run.etiqueta}? Se descontarán ${m.total_hojas} hoja(s) del inventario y se darán de alta ${m.retazos_generados} retazo(s).`)) return;
    setBusy(true); setErrs(null);
    try {
      const r = await api.confirmar(run.id);
      setMsg(`Corte confirmado: ${r.hojas_descontadas} hoja(s) descontadas y ${r.retazos_dados_de_alta} retazo(s) dados de alta en inventario.`);
      onConfirmed && onConfirmed(r.corrida);
    } catch (e) { setErrs(errorList(e)); } finally { setBusy(false); }
  };
  const pend = run.ordenes.filter((o) => !o.cubierta);
  return (
    <>
      <div className="card">
        <div className="row">
          <h2 style={{ margin: 0 }}>Corrida {run.etiqueta}</h2>
          <span className={`badge ${run.estado === "simulada" ? "warn" : run.estado === "confirmada" ? "ok" : "off"}`}>
            {run.estado === "simulada" ? "Simulación (sin confirmar)" : run.estado}</span>
          <span className="muted">{run.creado} UTC · {fmt(m.segundos, 1)} s de cómputo</span>
          <span className="spacer" />
          <a className="btn primary big" href={`/api/corridas/${run.id}/planos.zip`}>
            <span className="step">3</span> Descargar planos (.zip)</a>
          {run.estado === "simulada" && (
            <button className="btn ok big" disabled={busy} onClick={confirm}>Confirmar orden de corte</button>)}
        </div>
        {run.estado === "obsoleta" && <div className="alert warn">Los datos cambiaron después de esta corrida. Vuelva a optimizar antes de confirmar.</div>}
        {msg && <div className="alert ok">{msg}</div>}
        <Errors list={errs} />
        <h3>Métricas proyectadas</h3>
        <div className="metrics">
          <div className="metric"><div className="v">{m.hojas_consumidas}</div><div className="l">Hojas nuevas consumidas</div>
            <Delta now={m.hojas_consumidas} before={p.hojas_consumidas} better="down" unit="" /></div>
          <div className="metric"><div className="v">{m.retazos_consumidos}</div><div className="l">Retazos reutilizados</div></div>
          <div className="metric"><div className="v">{pct(m.aprovechamiento)}</div><div className="l">Aprovechamiento global</div>
            <Delta now={m.aprovechamiento} before={p.aprovechamiento} /></div>
          <div className="metric"><div className="v">{pct(m.merma_neta)}</div><div className="l">Merma neta</div>
            <Delta now={m.merma_neta} before={p.merma_neta} better="down" /></div>
          <div className="metric"><div className="v">{pct(m.pct_retazos)}</div><div className="l">Área en retazos recuperables ({m.retazos_generados})</div></div>
          <div className="metric"><div className="v">{m.ordenes_cubiertas} / {m.ordenes_total}</div><div className="l">Órdenes cubiertas</div></div>
          <div className="metric"><div className="v" style={{ color: m.ordenes_pendientes ? "var(--err)" : undefined }}>{m.ordenes_pendientes}</div>
            <div className="l">Pendientes por falta de stock</div></div>
          <div className="metric"><div className="v">{pct(m.adherencia_cola)}</div><div className="l">Adherencia a la cola</div>
            <Delta now={m.adherencia_cola} before={p.adherencia_cola} /></div>
          {m.costo_merma > 0 && <div className="metric"><div className="v">${fmt(m.costo_merma, 0)}</div><div className="l">Costo estimado de merma</div></div>}
        </div>
        {pend.length > 0 && (
          <div className="alert warn">Órdenes sin cubrir: {pend.map((o) => `${o.numero} (${o.colocadas}/${o.requeridas} piezas, ${o.motivo.toLowerCase()})`).join("; ")}.</div>)}
      </div>

      <div className="card">
        <h2>Planos de corte ({run.hojas.length} hojas, en secuencia de corte)</h2>
        <div className="sheets">
          {run.hojas.map((s) => (
            <div className="sheet" key={s.hoja_id}>
              <img loading="lazy" alt={`Plano ${s.hoja_id}`} src={`/api/corridas/${run.id}/hojas/${s.hoja_id}.png?miniatura=1`}
                onClick={() => setView(s)} />
              <div className="info">
                <strong>{s.hoja_id}</strong>
                <span>{s.codigo}</span>
                {s.es_retazo && <span className="badge ok">retazo</span>}
                {s.veta_direccional && <span className="badge veta">veta</span>}
                <span className="spacer" />
                <span>{pct(s.aprovechamiento)}</span>
                <a className="btn sm" href={`/api/corridas/${run.id}/hojas/${s.hoja_id}.png?descargar=1`}>PNG</a>
              </div>
            </div>))}
        </div>
      </div>

      <div className="card">
        <h2>Detalle por material y por orden</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Material</th><th className="num">Piezas</th><th className="num">Hojas</th><th>Rotación</th>
              <th className="num">Generaciones</th><th>Parada</th><th>Convergencia (aptitud)</th></tr></thead>
            <tbody>{run.grupos.map((g) => (
              <tr key={g.material}>
                <td>{g.material}</td><td className="num">{g.piezas}</td><td className="num">{g.hojas}</td>
                <td>{g.rotacion_permitida ? "Permitida" : <span className="badge veta">Bloqueada (veta)</span>}</td>
                <td className="num">{g.generaciones}</td><td>{g.criterio_parada} ({fmt(g.segundos, 1)} s)</td>
                <td><Sparkline values={g.historial} /></td>
              </tr>))}</tbody>
          </table>
        </div>
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead><tr><th className="num">Pos.</th><th>Orden</th><th>Prioridad</th><th className="num">Piezas</th>
              <th>Estado</th><th className="num">Atraso en cola</th></tr></thead>
            <tbody>{run.ordenes.map((o) => (
              <tr key={o.id}>
                <td className="num">{o.posicion}</td><td>{o.numero}</td>
                <td>{o.prioridad === "Urgente" ? <span className="badge urg">Urgente</span> : "Normal"}</td>
                <td className="num">{o.colocadas} / {o.requeridas}</td>
                <td>{o.cubierta ? <span className="badge ok">Cubierta</span> : <span className="badge warn">{o.motivo}</span>}</td>
                <td className="num">{o.desplazamiento ? `${o.desplazamiento} pos.` : "—"}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </div>

      {view && (
        <Modal title={`Plano ${view.hoja_id} · ${view.codigo}`} onClose={() => setView(null)} wide>
          <img alt={`Plano ${view.hoja_id}`} src={`/api/corridas/${run.id}/hojas/${view.hoja_id}.png`} style={{ width: "100%" }} />
          <div className="row" style={{ marginTop: 10 }}>
            <span className="spacer" />
            <a className="btn primary" href={`/api/corridas/${run.id}/hojas/${view.hoja_id}.png?descargar=1`}>Descargar PNG</a>
          </div>
        </Modal>)}
    </>
  );
}

export default function Planeacion({ onStockChanged }) {
  const [orders, setOrders] = useState([]);
  const [tipos, setTipos] = useState([]);
  const [lotes, setLotes] = useState([]);
  const [run, setRun] = useState(null);
  const [prev, setPrev] = useState(null);
  const [form, setForm] = useState(null); // null | "new" | orden
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState(null);
  const [auto, setAuto] = useState(true);

  const load = useCallback(async () => {
    const [o, t, l, runs] = await Promise.all([api.ordenes(), api.tipos(), api.lotes(), api.corridas()]);
    setOrders(o); setTipos(t); setLotes(l);
    setRun(runs.length ? await api.corrida(runs[0].id) : null);
  }, []);
  useEffect(() => { load().catch((e) => setErrs(errorList(e))); }, [load]);

  const optimize = async (quick = false) => {
    setBusy(true); setErrs(null);
    try {
      const r = await api.optimizar(quick ? { tiempo_max: QUICK_SECONDS } : {});
      setPrev(run ? run.metricas : null);
      setRun(r);
    } catch (e) { setErrs(errorList(e)); } finally { setBusy(false); }
  };
  const reorder = async (ids) => {
    setOrders(ids.map((id) => orders.find((o) => o.id === id)));
    try {
      setOrders(await api.reordenar(ids));
      setRun((r) => (r ? { ...r, estado: "obsoleta" } : r));
      if (auto) await optimize(true);
    } catch (e) { setErrs(errorList(e)); load(); }
  };
  const remove = async (o) => {
    if (!window.confirm(`¿Eliminar la orden ${o.numero} de la cola?`)) return;
    await api.borrarOrden(o.id);
    load();
  };

  return (
    <div className="grid2">
      <div>
        <div className="card">
          <h2>Cola de producción <span className="badge">{orders.length}</span></h2>
          <div className="toolbar">
            <Importer kind="ordenes" label={<><span className="step">1</span> Importar órdenes</>} autoLoad
              onDone={() => { load(); }} />
            <button className="btn" onClick={() => setForm("new")}>+ Nueva orden</button>
          </div>
          <label className="row muted" style={{ marginBottom: 10 }}>
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            Recalcular el impacto automáticamente al reordenar ({QUICK_SECONDS} s)
          </label>
          <Queue orders={orders} busy={busy} onReorder={reorder} onEdit={setForm} onDelete={remove} />
        </div>
      </div>
      <div>
        <div className="card">
          <div className="row">
            <h2 style={{ margin: 0 }}>Optimización de corte</h2>
            <span className="spacer" />
            <button className="btn go big" disabled={busy || !orders.length} onClick={() => optimize(false)}>
              {busy ? <span className="loader" /> : <span className="step">2</span>}
              {busy ? "Optimizando…" : "Optimizar"}
            </button>
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>
            Agrupa por color, textura y espesor y ejecuta el algoritmo genético con los parámetros vigentes.
            Flujo rápido: <strong>1</strong> importar órdenes → <strong>2</strong> optimizar → <strong>3</strong> descargar planos.
          </p>
          <Errors list={errs} />
          {!run && !busy && <div className="empty">Aún no hay una simulación. Pulse “Optimizar”.</div>}
        </div>
        {run && <div style={{ marginTop: 16 }}>
          <RunView key={run.id} run={run} previous={prev}
            onConfirmed={(r) => { setRun(r); setPrev(null); load(); onStockChanged && onStockChanged(); }} />
        </div>}
      </div>
      {form && (
        <OrderForm initial={form === "new" ? null : form} tipos={tipos} lotes={lotes}
          onClose={() => setForm(null)}
          onSaved={() => { setForm(null); load(); }} />)}
    </div>
  );
}

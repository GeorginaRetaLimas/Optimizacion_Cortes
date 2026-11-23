// Cliente de la API REST del backend.
const PIN_KEY = "sw_admin_pin";

export function getPin() {
  try { return sessionStorage.getItem(PIN_KEY) || ""; } catch { return ""; }
}
export function setPin(pin) {
  try { sessionStorage.setItem(PIN_KEY, pin); } catch { /* sin almacenamiento */ }
}

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function request(method, url, body, { form = false, admin = false } = {}) {
  const opts = { method, headers: {} };
  if (admin) opts.headers["X-Admin-Pin"] = getPin();
  if (body !== undefined) {
    if (form) opts.body = body;
    else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  const res = await fetch(url, opts);
  let data = null;
  try { data = await res.json(); } catch { /* respuesta sin JSON */ }
  if (!res.ok && !(data && "errores" in data && res.status === 422 && "filas" in data)) {
    throw new ApiError((data && data.error) || `Error ${res.status}`, res.status, data);
  }
  return data;
}

export const api = {
  estado: () => request("GET", "/api/estado"),
  verificarPin: (pin) => request("POST", "/api/admin/verificar", { pin }),
  lotes: (retazos) => request("GET", `/api/lotes${retazos === undefined ? "" : `?retazos=${retazos ? 1 : 0}`}`),
  crearLote: (l) => request("POST", "/api/lotes", l),
  editarLote: (id, l) => request("PUT", `/api/lotes/${id}`, l),
  borrarLote: (id) => request("DELETE", `/api/lotes/${id}`),
  importar: (kind, file, confirmar) => {
    const fd = new FormData();
    fd.append("archivo", file);
    fd.append("confirmar", confirmar ? "1" : "0");
    return request("POST", `/api/${kind}/importar`, fd, { form: true });
  },
  tipos: () => request("GET", "/api/tipos"),
  guardarTipo: (t) => request("PUT", `/api/tipos/${encodeURIComponent(t.nombre)}`, t, { admin: true }),
  borrarTipo: (n) => request("DELETE", `/api/tipos/${encodeURIComponent(n)}`, undefined, { admin: true }),
  despiece: (b) => request("POST", "/api/despiece", b),
  ordenes: (estado = "pendiente") => request("GET", `/api/ordenes?estado=${estado}`),
  crearOrden: (o) => request("POST", "/api/ordenes", o),
  editarOrden: (id, o) => request("PUT", `/api/ordenes/${id}`, o),
  borrarOrden: (id) => request("DELETE", `/api/ordenes/${id}`),
  reordenar: (ids) => request("POST", "/api/ordenes/reordenar", { ids }),
  parametros: () => request("GET", "/api/parametros"),
  guardarParametros: (p) => request("PUT", "/api/parametros", p, { admin: true }),
  optimizar: (opts = {}) => request("POST", "/api/corridas", opts),
  corridas: () => request("GET", "/api/corridas"),
  corrida: (id) => request("GET", `/api/corridas/${id}`),
  confirmar: (id) => request("POST", `/api/corridas/${id}/confirmar`),
};

export function errorList(e) {
  const out = [e.message];
  const errs = e.data && e.data.errores;
  if (Array.isArray(errs)) {
    for (const x of errs) {
      out.push(typeof x === "string" ? x : `${x.campo ? x.campo + ": " : ""}${x.mensaje}`);
    }
  }
  return out;
}

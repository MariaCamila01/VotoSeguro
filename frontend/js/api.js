// Cliente HTTP de la API REST /api/v1 (compartido por votante y administración)
// Se puede cambiar con <meta name="api-base" content="https://otro-servidor/api/v1">
export const API_BASE =
  document.querySelector('meta[name="api-base"]')?.content || "/api/v1";

export class ErrorApi extends Error {
  constructor(status, codigo, mensaje, extra = {}) {
    super(mensaje);
    this.status = status;
    this.codigo = codigo;
    this.extra = extra;
  }
}

export async function api(metodo, ruta, { cuerpo, token } = {}) {
  const cabeceras = { Accept: "application/json" };
  if (cuerpo !== undefined) cabeceras["Content-Type"] = "application/json";
  if (token) cabeceras.Authorization = `Bearer ${token}`;

  let resp;
  try {
    resp = await fetch(API_BASE + ruta, {
      method: metodo,
      headers: cabeceras,
      body: cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined,
    });
  } catch {
    throw new ErrorApi(0, "SIN_CONEXION", "No hay conexión con el servidor. Revise su red e intente de nuevo.");
  }

  let datos = null;
  try { datos = await resp.json(); } catch { /* respuesta sin JSON */ }

  if (!resp.ok) {
    const e = (datos && datos.error) || {};
    const { codigo, mensaje, ...extra } = e;
    throw new ErrorApi(resp.status, codigo || `HTTP_${resp.status}`,
                       mensaje || "Ocurrió un error inesperado", extra);
  }
  return datos;
}

// Crea elementos sin innerHTML: el texto nunca se interpreta como HTML.
export function el(etiqueta, atributos = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(atributos)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "clase") nodo.className = v;
    else if (k.startsWith("on")) nodo.addEventListener(k.slice(2), v);
    else nodo.setAttribute(k, v === true ? "" : v);
  }
  for (const h of hijos.flat()) {
    if (h === null || h === undefined || h === false) continue;
    nodo.append(h instanceof Node ? h : document.createTextNode(String(h)));
  }
  return nodo;
}

export function mostrarMensaje(nodo, texto, tipo = "error") {
  nodo.className = `mensaje ${tipo}`;
  nodo.textContent = texto || "";
}

export function fecha(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es-CO", {
    timeZone: "America/Bogota", dateStyle: "medium", timeStyle: "short",
  });
}

export function $(selector) {
  return document.querySelector(selector);
}

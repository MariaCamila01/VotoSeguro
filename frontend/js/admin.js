// Panel de administración y auditoría (secciones 3.3, 3.4 y 3.5)
import { api, el, fecha, mostrarMensaje, $ } from "./api.js";

const S = {
  token: sessionStorage.getItem("vs_token"),
  rol: sessionStorage.getItem("vs_rol"),
  nombre: sessionStorage.getItem("vs_nombre"),
  elecciones: [],
  seleccion: null,
};

async function llamar(metodo, ruta, cuerpo) {
  try {
    return await api(metodo, ruta, { cuerpo, token: S.token });
  } catch (e) {
    if (e.status === 401) cerrarSesion("Su sesión expiró. Inicie sesión de nuevo.", false);
    throw e;
  }
}

// --------------------------------------------------------------- sesión
async function login() {
  const msg = $("#msgLogin");
  const usuario = $("#usuario").value.trim();
  const password = $("#password").value;
  if (!usuario || !password) return mostrarMensaje(msg, "Escriba usuario y contraseña.");
  try {
    const r = await api("POST", "/auth/admin/login", { cuerpo: { usuario, password } });
    Object.assign(S, { token: r.token, rol: r.rol, nombre: r.nombre });
    sessionStorage.setItem("vs_token", r.token);
    sessionStorage.setItem("vs_rol", r.rol);
    sessionStorage.setItem("vs_nombre", r.nombre);
    $("#password").value = "";
    mostrarMensaje(msg, "");
    entrar();
  } catch (e) {
    const extra = e.extra.reintentarEnSeg ? ` Espere ${Math.ceil(e.extra.reintentarEnSeg / 60)} min.` : "";
    mostrarMensaje(msg, e.message + extra);
  }
}

async function cerrarSesion(mensaje = "", avisarServidor = true) {
  if (avisarServidor && S.token) {
    try { await api("POST", "/auth/logout", { token: S.token }); } catch { /* sin importancia */ }
  }
  sessionStorage.clear();
  Object.assign(S, { token: null, rol: null, nombre: null, seleccion: null });
  $("#vistaPanel").classList.add("oculto");
  $("#sesion").classList.add("oculto");
  $("#vistaLogin").classList.remove("oculto");
  mostrarMensaje($("#msgLogin"), mensaje, "info");
}

function entrar() {
  $("#vistaLogin").classList.add("oculto");
  $("#vistaPanel").classList.remove("oculto");
  $("#sesion").classList.remove("oculto");
  $("#usuarioActual").textContent = `${S.nombre} · ${S.rol}`;
  document.querySelectorAll("[data-solo]").forEach(n =>
    n.classList.toggle("oculto", n.dataset.solo !== S.rol));
  cambiarPestana("elecciones");
}

function cambiarPestana(nombre) {
  document.querySelectorAll("[role=tab]").forEach(b =>
    b.setAttribute("aria-selected", String(b.dataset.pestana === nombre)));
  document.querySelectorAll("[data-panel]").forEach(p =>
    p.classList.toggle("oculto", p.dataset.panel !== nombre));
  ({ elecciones: cargarElecciones, padron: cargarPadron, ledger: cargarLedger, auditoria: cargarAuditoria })[nombre]();
}

// ----------------------------------------------------------- elecciones
const insigniaEstado = (estado) => el("span", { clase: `estado estado-${estado}` }, estado);

async function cargarElecciones() {
  try {
    S.elecciones = await llamar("GET", "/elecciones");
    $("#tablaElecciones").replaceChildren(...S.elecciones.map(e => el("tr", {},
      el("td", {}, e.nombre),
      el("td", {}, insigniaEstado(e.estado)),
      el("td", {}, fecha(e.fechaInicio)),
      el("td", {}, fecha(e.fechaFin)),
      el("td", {}, el("button", { clase: "btn btn-secundario btn-pequeno", onclick: () => verDetalle(e.id) }, "Gestionar")),
    )));
    if (!S.elecciones.length) {
      $("#tablaElecciones").append(el("tr", {}, el("td", { colspan: "5", clase: "tenue" }, "Todavía no hay elecciones.")));
    }
    mostrarMensaje($("#msgElecciones"), "");
  } catch (e) {
    mostrarMensaje($("#msgElecciones"), e.message);
  }
}

function leerOpciones(texto) {
  return texto.split("\n").map(l => l.trim()).filter(Boolean).map(l => {
    const [nombre, ...resto] = l.split("|");
    const descripcion = resto.join("|").trim();
    return descripcion ? { nombre: nombre.trim(), descripcion } : { nombre: nombre.trim() };
  });
}

const opcionesATexto = (ops) => ops.map(o => o.descripcion ? `${o.nombre} | ${o.descripcion}` : o.nombre).join("\n");

async function crearEleccion() {
  const msg = $("#msgNueva");
  const inicio = $("#nInicio").value, fin = $("#nFin").value;
  if (!inicio || !fin) return mostrarMensaje(msg, "Indique fecha de inicio y de fin.");
  const cuerpo = {
    nombre: $("#nNombre").value.trim(),
    fechaInicio: new Date(inicio).toISOString(),
    fechaFin: new Date(fin).toISOString(),
  };
  const opciones = leerOpciones($("#nOpciones").value);
  if (opciones.length) cuerpo.opciones = opciones;
  try {
    const e = await llamar("POST", "/elecciones", cuerpo);
    $("#formNueva").reset();
    $("#tarjetaNueva").classList.add("oculto");
    await cargarElecciones();
    verDetalle(e.id);
  } catch (e) {
    mostrarMensaje(msg, e.message);
  }
}

async function verDetalle(id) {
  const msg = $("#msgDetalle");
  mostrarMensaje(msg, "");
  $("#dReporte").classList.add("oculto");
  $("#dVerificacion").replaceChildren();
  try {
    const e = await llamar("GET", `/elecciones/${id}`);
    S.seleccion = e;
    $("#tarjetaDetalle").classList.remove("oculto");
    $("#dNombre").textContent = e.nombre;
    $("#dFechas").textContent = `${fecha(e.fechaInicio)} → ${fecha(e.fechaFin)}`;
    $("#dEstado").replaceWith(Object.assign(insigniaEstado(e.estado), { id: "dEstado" }));
    $("#dVotos").textContent = e.totalVotosEmitidos;
    $("#dOpciones").textContent = e.opciones.length;

    const editable = e.estado === "BORRADOR" && S.rol === "admin";
    $("#editorOpciones").classList.toggle("oculto", !editable);
    $("#dOpcionesTexto").value = opcionesATexto(e.opciones);
    $("#dListaOpciones").replaceChildren(...(editable ? [] : e.opciones.map(o =>
      el("li", {}, o.nombre, o.descripcion ? ` — ${o.descripcion}` : ""))));

    const b = (texto, clase, accion) => el("button", { clase: `btn ${clase}`, onclick: accion }, texto);
    const acciones = [];
    if (S.rol === "admin") {
      if (e.estado === "BORRADOR") {
        acciones.push(b("Guardar opciones", "btn-secundario", guardarOpciones));
        acciones.push(b("Abrir elección", "btn-primario", () => transicion("abrir")));
      }
      if (e.estado === "ABIERTA") {
        acciones.push(b("Cerrar elección", "btn-peligro", () => transicion("cerrar")));
        acciones.push(el("a", { clase: "btn btn-secundario", href: `index.html?eleccion=${e.id}`, target: "_blank" },
          "Abrir página de votación"));
      }
      if (e.estado === "CERRADA") acciones.push(b("Ver resultados", "btn-primario", verReporte));
    }
    if (e.estado !== "BORRADOR") acciones.push(b("Verificar ledger", "btn-secundario", verificarSeleccion));
    $("#dAcciones").replaceChildren(...acciones);
    $("#tarjetaDetalle").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    mostrarMensaje($("#msgElecciones"), err.message);
  }
}

async function guardarOpciones() {
  try {
    await llamar("PUT", `/elecciones/${S.seleccion.id}/opciones`, { opciones: leerOpciones($("#dOpcionesTexto").value) });
    await verDetalle(S.seleccion.id);
    mostrarMensaje($("#msgDetalle"), "Opciones guardadas.", "ok");
  } catch (e) {
    mostrarMensaje($("#msgDetalle"), e.message);
  }
}

async function transicion(accion) {
  const texto = accion === "abrir"
    ? "¿Abrir la elección? Las opciones ya no se podrán modificar."
    : "¿Cerrar la elección? No se aceptarán más votos y se verificará el ledger.";
  if (!window.confirm(texto)) return;
  try {
    const r = await llamar("POST", `/elecciones/${S.seleccion.id}/${accion}`);
    await cargarElecciones();
    await verDetalle(S.seleccion.id);
    mostrarMensaje($("#msgDetalle"), accion === "abrir" ? "Elección abierta." : "Elección cerrada.", "ok");
    if (r.verificacion) pintarVerificacion($("#dVerificacion"), r.verificacion);
  } catch (e) {
    mostrarMensaje($("#msgDetalle"), e.message);
  }
}

async function verReporte() {
  try {
    const r = await llamar("GET", `/reportes/${S.seleccion.id}`);
    $("#tablaResultados").replaceChildren(...r.resultados.map(x => el("tr", {},
      el("td", {}, x.nombre),
      el("td", {}, x.votos),
      el("td", {}, `${x.porcentaje.toFixed(1)} %`),
      el("td", {}, (() => {
        const barra = el("div", { clase: "barra-resultado" }, el("div"));
        barra.firstChild.style.width = `${x.porcentaje}%`;
        return barra;
      })()),
    )));
    $("#tablaResultados").append(el("tr", {}, el("td", {}, el("strong", {}, "Total")),
      el("td", {}, el("strong", {}, r.totalVotos)), el("td"), el("td")));
    $("#dReporte").classList.remove("oculto");
    pintarVerificacion($("#dVerificacion"), r.integridad);
  } catch (e) {
    mostrarMensaje($("#msgDetalle"), e.message);
  }
}

async function verificarSeleccion() {
  try {
    pintarVerificacion($("#dVerificacion"), await llamar("GET", `/ledger/${S.seleccion.id}/verificar`));
  } catch (e) {
    mostrarMensaje($("#msgDetalle"), e.message);
  }
}

function pintarVerificacion(nodo, v) {
  const resumen = el("div", { clase: `mensaje ${v.integro ? "ok" : "error"}` },
    v.integro
      ? `Cadena íntegra: ${v.totalBloques} bloque(s) verificados.`
      : `Integridad comprometida${v.indiceFalla !== null ? ` en el bloque #${v.indiceFalla}` : ""}: ${v.motivo}`);
  const c = v.consistencia;
  const lista = el("ul", { clase: "lista-verificacion" },
    el("li", {}, `Tokens emitidos a votantes: ${c.tokensEmitidos} · Votos: ${c.votos} · Bloques: ${c.bloques}`),
    v.anclaVerificada ? el("li", {}, "Coincide con el ancla guardada al cierre ✓") : null,
    el("li", {}, "Hash final: ", el("span", { clase: "mono" }, v.hashFinal)),
    el("li", {}, `Verificado: ${fecha(v.ultimaVerificacion)}`),
    ...v.advertencias.map(a => el("li", {}, `⚠ ${a}`)));
  nodo.replaceChildren(resumen, lista);
}

// --------------------------------------------------------------- padrón
async function cargarPadron() {
  try {
    const r = await llamar("GET", "/votantes/resumen");
    $("#pTotal").textContent = r.total;
    $("#pAutorizados").textContent = r.conAutorizacionDatos;
  } catch (e) {
    mostrarMensaje($("#msgPadron"), e.message);
  }
}

async function subirPadron() {
  const msg = $("#msgPadron");
  const votantes = $("#padronCsv").value.split("\n").map(l => l.trim()).filter(Boolean)
    .filter(l => !/^documento/i.test(l))
    .map(l => {
      const [documentoInstitucional, correo] = l.split(/[,;\t]/).map(x => (x || "").trim());
      return { documentoInstitucional, correo };
    });
  if (!votantes.length) return mostrarMensaje(msg, "Pegue al menos una fila documento,correo.");
  try {
    const r = await llamar("POST", "/votantes", { votantes });
    const rech = r.rechazados.map(x => `fila ${x.fila}: ${x.motivo}`).join("; ");
    mostrarMensaje(msg, `Creados: ${r.creados} · Actualizados: ${r.actualizados} · Rechazados: ${r.rechazados.length}` +
      (rech ? ` (${rech})` : ""), r.rechazados.length ? "info" : "ok");
    $("#padronCsv").value = "";
    cargarPadron();
  } catch (e) {
    mostrarMensaje(msg, e.message);
  }
}

async function suprimir() {
  const msg = $("#msgSuprimir");
  const documento = $("#docSuprimir").value.trim();
  if (!documento) return mostrarMensaje(msg, "Escriba el documento.");
  if (!window.confirm(`¿Eliminar definitivamente los datos personales de ${documento}?`)) return;
  try {
    const r = await llamar("POST", "/votantes/suprimir", { documentoInstitucional: documento });
    mostrarMensaje(msg, r.mensaje, "ok");
    $("#docSuprimir").value = "";
    cargarPadron();
  } catch (e) {
    mostrarMensaje(msg, e.message);
  }
}

// --------------------------------------------------------------- ledger
async function cargarLedger() {
  if (!S.elecciones.length) {
    try { S.elecciones = await llamar("GET", "/elecciones"); } catch { /* se muestra vacío */ }
  }
  const candidatas = S.elecciones.filter(e => e.estado !== "BORRADOR");
  $("#lEleccion").replaceChildren(...candidatas.map(e => el("option", { value: e.id }, `${e.nombre} (${e.estado})`)));
  $("#btnVerificar").disabled = !candidatas.length;
  $("#lResultado").replaceChildren();
  $("#lCadena").classList.add("oculto");
}

async function verificarLedger() {
  try {
    pintarVerificacion($("#lResultado"), await llamar("GET", `/ledger/${$("#lEleccion").value}/verificar`));
  } catch (e) {
    $("#lResultado").replaceChildren(el("div", { clase: "mensaje error" }, e.message));
  }
}

async function verCadena() {
  try {
    const r = await llamar("GET", `/ledger/${$("#lEleccion").value}/cadena?limite=1000`);
    const corto = (h) => el("span", { clase: "mono", title: h }, `${h.slice(0, 12)}…${h.slice(-6)}`);
    $("#tablaCadena").replaceChildren(...r.bloques.map(b => el("tr", {},
      el("td", {}, b.indice), el("td", {}, corto(b.hashAnterior)), el("td", {}, corto(b.hashActual)),
      el("td", {}, fecha(b.timestamp)))));
    $("#lCadena").classList.remove("oculto");
  } catch (e) {
    $("#lResultado").replaceChildren(el("div", { clase: "mensaje error" }, e.message));
  }
}

// ------------------------------------------------------------ auditoría
function detalleLegible(d) {
  if (!d) return "";
  if (typeof d !== "object") return String(d);
  return Object.entries(d).map(([k, v]) => {
    const texto = typeof v === "string" && v.length > 20 ? `${v.slice(0, 8)}…` : String(v);
    return `${k}: ${texto}`;
  }).join(" · ");
}

async function cargarAuditoria() {
  try {
    const filas = await llamar("GET", "/auditoria?limite=200");
    $("#tablaAuditoria").replaceChildren(...filas.map(f => el("tr", {},
      el("td", {}, fecha(f.timestamp)),
      el("td", {}, el("span", { clase: f.accion === "INTEGRIDAD_COMPROMETIDA" ? "estado estado-BORRADOR" : "" }, f.accion)),
      el("td", {}, f.responsable),
      el("td", { clase: "pequeno" }, detalleLegible(f.detalle)),
    )));
  } catch (e) {
    $("#tablaAuditoria").replaceChildren(el("tr", {}, el("td", { colspan: "4" }, e.message)));
  }
}

// --------------------------------------------------------------- eventos
document.addEventListener("DOMContentLoaded", () => {
  $("#formLogin").addEventListener("submit", (e) => { e.preventDefault(); login(); });
  $("#btnSalir").addEventListener("click", () => cerrarSesion("Sesión cerrada."));
  document.querySelectorAll("[role=tab]").forEach(b =>
    b.addEventListener("click", () => cambiarPestana(b.dataset.pestana)));
  $("#btnNueva").addEventListener("click", () => {
    $("#tarjetaNueva").classList.remove("oculto");
    $("#nNombre").focus();
  });
  $("#btnCancelarNueva").addEventListener("click", () => $("#tarjetaNueva").classList.add("oculto"));
  $("#formNueva").addEventListener("submit", (e) => { e.preventDefault(); crearEleccion(); });
  $("#formPadron").addEventListener("submit", (e) => { e.preventDefault(); subirPadron(); });
  $("#formSuprimir").addEventListener("submit", (e) => { e.preventDefault(); suprimir(); });
  $("#btnVerificar").addEventListener("click", verificarLedger);
  $("#btnCadena").addEventListener("click", verCadena);
  $("#btnRecargarAuditoria").addEventListener("click", cargarAuditoria);

  if (S.token) entrar();
});

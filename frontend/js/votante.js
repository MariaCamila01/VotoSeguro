// Cliente del votante: OTP → JWT → voto → comprobante (secciones 3.1 y 3.2)
import { api, el, fecha, mostrarMensaje, $ } from "./api.js";

const estado = {
  eleccionId: null,
  eleccionNombre: "",
  documento: "",
  token: null,          // JWT solo en memoria: nunca en localStorage
  opcion: null,
  temporizador: null,
};

// ------------------------------------------------------------ navegación
function irAPaso(n) {
  for (let i = 1; i <= 4; i++) {
    $(`#paso${i}`).classList.toggle("oculto", i !== n);
    const li = document.querySelector(`.pasos li[data-paso="${i}"]`);
    li.classList.toggle("activo", i === n);
    li.classList.toggle("hecho", i < n);
  }
  const foco = { 1: "#documento", 2: "#otp" }[n];
  if (foco) $(foco).focus();
}

function reiniciar(mensaje, tipo = "error") {
  clearInterval(estado.temporizador);
  estado.token = null;
  estado.opcion = null;
  $("#otp").value = "";
  $("#btnContinuar").disabled = true;
  irAPaso(1);
  mostrarMensaje($("#msg1"), mensaje || "", tipo);
}

function textoError(e) {
  if (e.codigo === "LIMITE_EXCEDIDO" && e.extra.reintentarEnSeg) {
    const min = Math.ceil(e.extra.reintentarEnSeg / 60);
    return `${e.message}. Intente de nuevo en ${min} minuto${min === 1 ? "" : "s"}.`;
  }
  if (e.codigo === "OTP_INVALIDO" && e.extra.intentosRestantes !== undefined) {
    return `Código incorrecto. Le quedan ${e.extra.intentosRestantes} intento(s).`;
  }
  return e.message;
}

// ------------------------------------------------------------- inicio
async function iniciar() {
  try {
    await api("GET", "/salud");
    $("#estadoServicio").textContent = "Conexión segura";
  } catch {
    $("#estadoServicio").textContent = "Servicio no disponible";
    $("#estadoServicio").classList.add("error");
  }

  const select = $("#eleccion");
  try {
    const elecciones = await api("GET", "/elecciones");
    select.replaceChildren(...elecciones.map(e =>
      el("option", { value: e.id }, `${e.nombre} (cierra ${fecha(e.fechaFin)})`)));
    if (!elecciones.length) {
      select.append(el("option", { value: "" }, "No hay elecciones abiertas"));
      select.disabled = true;
      $("#btnSolicitar").disabled = true;
    }
    const pedida = new URLSearchParams(location.search).get("eleccion");
    if (pedida && elecciones.some(e => e.id === pedida)) select.value = pedida;
  } catch (e) {
    mostrarMensaje($("#msg1"), textoError(e));
  }
}

// ------------------------------------------------------- paso 1: solicitar
async function solicitarOtp() {
  const msg = $("#msg1");
  const documento = $("#documento").value.trim().toUpperCase();
  const eleccionId = $("#eleccion").value;

  if (!/^[A-Z0-9-]{4,20}$/.test(documento)) {
    return mostrarMensaje(msg, "Escriba su documento institucional (4 a 20 letras o números).");
  }
  if (!$("#autorizacion").checked) {
    return mostrarMensaje(msg, "Debe autorizar el tratamiento de datos para continuar.");
  }

  const boton = $("#btnSolicitar");
  boton.disabled = true;
  mostrarMensaje(msg, "Enviando código…", "info");
  try {
    const r = await api("POST", "/auth/otp/solicitar", {
      cuerpo: { documentoInstitucional: documento, eleccionId, aceptaTratamientoDatos: true },
    });
    estado.documento = documento;
    estado.eleccionId = eleccionId;
    estado.eleccionNombre = $("#eleccion").selectedOptions[0].textContent;
    $("#textoDestino").textContent = `Enviamos un código a ${r.destino}.`;
    $("#vigenciaOtp").textContent = `El código vence en ${Math.round(r.expiraEn / 60)} minutos.`;
    mostrarMensaje(msg, "");
    mostrarMensaje($("#msg2"), "");
    irAPaso(2);
  } catch (e) {
    mostrarMensaje(msg, textoError(e));
  } finally {
    boton.disabled = false;
  }
}

// -------------------------------------------------------- paso 2: verificar
async function verificarOtp() {
  const msg = $("#msg2");
  const codigo = $("#otp").value.trim();
  if (!/^\d{6}$/.test(codigo)) return mostrarMensaje(msg, "El código tiene 6 dígitos.");

  const boton = $("#btnVerificar");
  boton.disabled = true;
  try {
    const r = await api("POST", "/auth/otp/verificar", {
      cuerpo: { documentoInstitucional: estado.documento, eleccionId: estado.eleccionId, codigoOTP: codigo },
    });
    estado.token = r.token;
    await mostrarOpciones(r.expiraEn);
  } catch (e) {
    mostrarMensaje(msg, textoError(e));
    if (["OTP_BLOQUEADO", "OTP_EXPIRADO"].includes(e.codigo)) $("#otp").value = "";
  } finally {
    boton.disabled = false;
  }
}

async function reenviar() {
  const msg = $("#msg2");
  try {
    const r = await api("POST", "/auth/otp/solicitar", {
      cuerpo: { documentoInstitucional: estado.documento, eleccionId: estado.eleccionId, aceptaTratamientoDatos: true },
    });
    $("#otp").value = "";
    mostrarMensaje(msg, `Código reenviado a ${r.destino}. El anterior ya no sirve.`, "ok");
  } catch (e) {
    mostrarMensaje(msg, textoError(e));
  }
}

// ---------------------------------------------------------- paso 3: votar
async function mostrarOpciones(segundos) {
  const opciones = await api("GET", `/elecciones/${estado.eleccionId}/opciones`);
  $("#tituloEleccion").textContent = estado.eleccionNombre.replace(/ \(cierra.*$/, "");
  const cont = $("#opciones");
  cont.replaceChildren(...opciones.map(o => el("button", {
    clase: "opcion", type: "button", "aria-pressed": "false",
    onclick: (ev) => seleccionar(ev.currentTarget, o),
  }, el("strong", {}, o.nombre), o.descripcion ? el("span", {}, o.descripcion) : null)));
  mostrarMensaje($("#msg3"), "");
  irAPaso(3);
  iniciarTemporizador(segundos);
}

function seleccionar(boton, opcion) {
  document.querySelectorAll(".opcion").forEach(b => b.setAttribute("aria-pressed", "false"));
  boton.setAttribute("aria-pressed", "true");
  estado.opcion = opcion;
  $("#btnContinuar").disabled = false;
}

function iniciarTemporizador(total) {
  clearInterval(estado.temporizador);
  const fin = Date.now() + total * 1000;
  const pintar = () => {
    const resta = Math.max(0, Math.round((fin - Date.now()) / 1000));
    $("#reloj").textContent = `${String(Math.floor(resta / 60)).padStart(2, "0")}:${String(resta % 60).padStart(2, "0")}`;
    $("#barraTiempo").style.width = `${(resta / total) * 100}%`;
    if (resta <= 0) {
      cerrarModal();
      reiniciar("El tiempo para votar terminó. Solicite un nuevo código para continuar.");
    }
  };
  pintar();
  estado.temporizador = setInterval(pintar, 1000);
}

function abrirModal() {
  if (!estado.opcion) return;
  $("#modalTexto").textContent = `Va a votar por: ${estado.opcion.nombre}`;
  $("#modal").classList.remove("oculto");
  $("#btnConfirmar").focus();
}

function cerrarModal() {
  $("#modal").classList.add("oculto");
}

async function confirmarVoto() {
  const boton = $("#btnConfirmar");
  boton.disabled = true;
  try {
    const r = await api("POST", "/votos", { cuerpo: { opcionId: estado.opcion.id }, token: estado.token });
    clearInterval(estado.temporizador);
    estado.token = null;
    cerrarModal();
    $("#cConfirmacion").textContent = r.confirmacion;
    $("#cIndice").textContent = `#${r.indiceBloque}`;
    $("#cHash").textContent = r.hashBloque;
    $("#cFecha").textContent = fecha(r.timestamp);
    irAPaso(4);
  } catch (e) {
    cerrarModal();
    // El JWT se invalida aunque el voto falle (sección 5.3 del documento)
    const mensaje = e.codigo === "YA_VOTO" ? e.message
      : `${textoError(e)} Por seguridad su sesión se cerró; solicite un nuevo código.`;
    reiniciar(mensaje);
  } finally {
    boton.disabled = false;
  }
}

// ---------------------------------------------------------- comprobante
async function verificarComprobante() {
  const msg = $("#msgComprobante");
  const id = $("#confirmacion").value.trim();
  if (!/^[0-9a-f-]{36}$/i.test(id)) return mostrarMensaje(msg, "El número de confirmación tiene 36 caracteres.");
  try {
    const r = await api("GET", `/ledger/comprobante/${id}`);
    mostrarMensaje(msg, `Voto encontrado en "${r.eleccion}", bloque #${r.indiceBloque}, registrado el ${fecha(r.timestamp)}`, "ok");
  } catch (e) {
    mostrarMensaje(msg, e.message);
  }
}

// ------------------------------------------------------------- eventos
document.addEventListener("DOMContentLoaded", () => {
  $("#formSolicitar").addEventListener("submit", (e) => { e.preventDefault(); solicitarOtp(); });
  $("#formVerificar").addEventListener("submit", (e) => { e.preventDefault(); verificarOtp(); });
  $("#formComprobante").addEventListener("submit", (e) => { e.preventDefault(); verificarComprobante(); });
  $("#otp").addEventListener("input", (e) => { e.target.value = e.target.value.replace(/\D/g, "").slice(0, 6); });
  $("#btnReenviar").addEventListener("click", reenviar);
  $("#btnVolver").addEventListener("click", () => reiniciar("", "info"));
  $("#btnContinuar").addEventListener("click", abrirModal);
  $("#btnCancelar").addEventListener("click", cerrarModal);
  $("#btnConfirmar").addEventListener("click", confirmarVoto);
  $("#btnTerminar").addEventListener("click", () => {
    $("#documento").value = "";
    $("#autorizacion").checked = false;
    reiniciar("Gracias por votar.", "ok");
  });
  $("#btnCopiar").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("#cConfirmacion").textContent);
      $("#btnCopiar").textContent = "Copiado ✓";
    } catch { /* el portapapeles puede no estar disponible */ }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") cerrarModal(); });
  iniciar();
});

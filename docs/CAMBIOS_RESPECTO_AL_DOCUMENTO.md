# Cambios respecto al documento y al código anterior

## 1. Qué había antes y qué hay ahora

El repositorio anterior (`sistema-votacion-biometrica`) implementaba otro sistema: una simulación
de elección presidencial nacional con biometría simulada, Registraduría y *Shamir's Secret Sharing*.
El documento describe un sistema distinto (votación **institucional** con OTP), así que el código se
reescribió para seguir el documento.

| Antes | Ahora | Motivo (documento) |
|---|---|---|
| Biometría simulada (un `setTimeout`) | OTP de 6 dígitos al correo institucional | §2 "el sistema usa OTP … no biometría" |
| Jurado + cédula + nombre en `localStorage` | El votante se autentica solo; JWT en memoria | §2.1 flujo de autenticación |
| BD de Registraduría con ciudadanos reales simulados | Padrón institucional cifrado | Introducción: no reemplaza el sistema oficial |
| Shamir 2-de-2 entre dos bases | Separación identidad–voto en el modelo de datos | §5.1 y Modelo Conceptual |
| Blockchain **en memoria** con prueba de trabajo (se perdía al reiniciar) | Ledger hash-chain persistido en `bloque_ledger` | §3.4 y tabla `bloque_ledger` |
| Rutas `/votar`, `/verificar`, `/estado` sin autenticación | API REST `/api/v1` con JWT + RBAC | §3 Endpoints, §2.3 Roles |
| Contraseñas en `docker-compose.yml`, CORS abierto, URL de Railway fija | Secretos en `.env`, proxy con TLS, mismo origen | §5.1 y §5.3 |
| Sin panel de administración | Panel admin/auditor | Diagrama de componentes |
| Voto en blanco automático al acabar el tiempo | El tiempo vence → hay que pedir otro código | Votar por alguien sin su acción no es un voto válido |
| Candidatos presidenciales reales | Elección estudiantil de ejemplo | Alcance institucional |
| 3 docker-compose separados con `host.docker.internal` | Un solo `docker-compose.yml` | Diagrama "Infraestructura Docker" |

## 2. Desviaciones del modelo físico del documento (sugerimos actualizar el documento)

### 2.1 `emision_token` ya no guarda `token_voto_id`  ⚠ importante

En el documento:

```
votante ──< emision_token >── token_voto ──< voto ──< bloque_ledger
            (votante_id,       (id)          (token_voto_id)
             token_voto_id)
```

Con eso, esta consulta revela por quién votó cada persona:

```sql
SELECT v.documento_institucional, o.nombre
FROM votante v
JOIN emision_token et ON et.votante_id = v.id
JOIN voto vo ON vo.token_voto_id = et.token_voto_id
JOIN opcion_voto o ON o.id = vo.opcion_id;
```

La sección 5.1 del propio documento advierte que si existe ese vínculo "el anonimato es solo
cosmético". La conclusión del Modelo Conceptual también dice que de Token de Voto en adelante "no
queda rastro de identidad". Para que eso se cumpla de verdad:

- `emision_token` solo registra `(votante_id, eleccion_id, fecha)`: "a esta persona ya se le
  emitió su token para esta elección". Es lo que impide votar dos veces.
- `token_voto`, `voto` y `bloque_ledger` no tienen ningún camino de claves foráneas hacia `votante`.
  La prueba `test_ninguna_ruta_de_claves_foraneas_une_voto_con_votante` lo comprueba.
- La emisión y el voto se guardan en **transacciones separadas**. Si fueran una sola, las dos filas
  compartirían el identificador interno de transacción de PostgreSQL (`xmin`) y se podrían cruzar.
- `emision_token.fecha_emision` es `DATE` (sin hora) para que la hora exacta no sirva para cruzarla
  con `voto.timestamp_voto`.

### 2.2 Otros ajustes al esquema

| Tabla | Cambio | Por qué |
|---|---|---|
| `votante` | `documento_institucional` y `correo` → `documento_hash` (HMAC), `documento_cifrado`, `correo_cifrado` (pgcrypto) | §5.1 cifrado en reposo |
| `votante` | Se quita `ha_votado` | Dependía de "la elección activa"; con varias elecciones daba datos erróneos. Ahora se consulta `emision_token` |
| `votante` | `fecha_autorizacion_datos`, `version_politica_datos` | §5.2 autorización previa (el documento lo marcaba como "trabajo pendiente") |
| `emision_token` | `UNIQUE (votante_id, eleccion_id)` en vez de `UNIQUE (votante_id)` | Con el UNIQUE original una persona solo podría votar en una elección en toda la vida del sistema |
| `emision_token` | `votante_id` admite `NULL` (`ON DELETE SET NULL`) | Al suprimir los datos de un votante el conteo de emisiones sigue cuadrando |
| `codigo_otp` | `eleccion_id`, `intentos` | El OTP se pide para una elección; sin límite de intentos un código de 6 dígitos se adivina |
| `codigo_otp` | `codigo_hash` = HMAC-SHA256 con clave del servidor | Con SHA-256 simple, el millón de códigos posibles se revierte en milisegundos |
| nuevas | `jwt_revocado`, `limite_tasa` | §5.3: "jti registrado en una tabla PostgreSQL" y rate limiting |
| `voto`, `bloque_ledger`, `registro_auditoria` | Triggers de solo inserción + el usuario de la API sin `UPDATE`/`DELETE` | Inmutabilidad "por diseño" (§5.2) |

### 2.3 Ajustes a la API

- **Respuesta de `/ledger/{id}/verificar`**: el documento la muestra como arreglo `[{…}]`; se devuelve
  un objeto `{integro, totalBloques, ultimaVerificacion, indiceFalla, motivo, …}`.
- **`GET /elecciones/{id}/estado` después de votar**: el JWT queda "consumido" para `POST /votos`
  pero sigue sirviendo para consultar el estado hasta que expire (caso de uso "Consultar estado").
- **Reportes solo con la elección CERRADA** (409 si está abierta): evita publicar resultados parciales.
- **Rutas agregadas** que el frontend necesita y el documento no listaba: `GET /elecciones`,
  `GET /elecciones/{id}/opciones`, `GET /elecciones/{id}`, `PUT /elecciones/{id}`,
  `GET /ledger/comprobante/{id}`, `POST /votantes`, `GET /votantes/resumen`, `POST /votantes/suprimir`,
  `GET /auditoria`, `POST /auth/logout`, `GET /salud`.
- **Ancla del ledger**: al cerrar, el hash final y el número de bloques se guardan en la auditoría.
  Una cadena de hashes por sí sola no detecta que alguien borre los *últimos* bloques; con el ancla sí.
- La verificación también cruza conteos: si hay **más votos que tokens emitidos a votantes**, alguien
  insertó votos por fuera del sistema.
- **HS256**: como recomienda §2.2, un solo servicio emite y valida los tokens.
- **Logs sin hora de voto**: nginx no registra `POST /votos` ni `GET /ledger/comprobante/…` (la hora
  y la IP de esas peticiones se podrían cruzar con `voto.timestamp_voto`).

## 3. Limitaciones conocidas (para mencionar en el documento)

- **Confianza en el operador**: un administrador de base de datos con acceso de superusuario podría
  intentar correlacionar emisiones y votos por el orden físico de las filas o por tiempos
  aproximados. Eliminarlo del todo exige técnicas como firmas ciegas o mezcladores (*mixnets*),
  fuera del alcance de la Fase 1.
- **Coerción**: el comprobante prueba que el voto existe, no por quién se votó. Aun así, quien vota
  desde casa puede ser presionado; esto es común a todo voto remoto.
- **MFA para administradores** no está implementado (solo usuario + contraseña + límite de intentos).
- **Gestión de claves**: las claves están en variables de entorno. En producción deberían ir en un
  gestor de secretos. Si se pierde `CLAVE_CIFRADO_DATOS` el padrón cifrado no se puede leer.
- **Certificado TLS** autofirmado en desarrollo.

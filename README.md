# VotoSeguro Bogotá

Sistema de votación institucional verificable (universidades y organizaciones).
Implementa el diseño del documento *VotoSeguro Bogotá* (Sistemas Distribuidos — Universidad Manuela Beltrán):

- **Verificación OTP en tiempo real** contra el padrón institucional (Hallazgo 1)
- **Tokens de un solo uso**: imposible votar dos veces (Hallazgo 2)
- **Ledger hash-chain** con verificación de integridad (Hallazgo 3)
- **Separación identidad–voto**: ninguna consulta SQL puede unir un voto con la persona que lo emitió

---

## Arquitectura

Corresponde al *Diagrama de Componentes* del documento:

```
 Navegador ──HTTPS (TLS 1.2+)──▶ proxy (nginx) ──▶ api (Flask + Gunicorn) ──▶ db (PostgreSQL 16)
   ├─ index.html  (cliente votante)                      │
   └─ admin.html  (panel de administración)              └──SMTP──▶ mailpit (correo de pruebas)
```

| Componente del diagrama            | Dónde está                                                    |
|------------------------------------|---------------------------------------------------------------|
| Aplicación Web / Cliente Votante   | `frontend/index.html`, `frontend/js/votante.js`               |
| Panel de Administración            | `frontend/admin.html`, `frontend/js/admin.js`                 |
| API Gateway / Controladores REST   | `proxy/` (TLS) + `api/app/__init__.py` + `api/app/seguridad/rbac.py` |
| Módulo de Autenticación OTP        | `api/app/modulos/auth.py`                                     |
| Módulo de Tokens de un solo uso    | `api/app/modulos/votacion.py` (`registrar_voto_anonimo`)      |
| Módulo de Votación                 | `api/app/modulos/votacion.py`                                 |
| Módulo de Ledger (Hash-Chain)      | `api/app/servicios/ledger.py`, `api/app/modulos/ledger.py`    |
| Módulo de Reportes y Auditoría     | `api/app/modulos/reportes.py`, `api/app/modulos/auditoria.py` |
| PostgreSQL                         | `db/initdb/01_schema.sql`, `db/initdb/02_rol_aplicacion.sh`   |

```
votoseguro-bogota/
├── docker-compose.yml        ← levanta todo
├── .env.example              ← copiar a .env
├── api/                      ← API REST /api/v1 (Python 3.12, Flask)
│   ├── app/
│   │   ├── modulos/          ← un Blueprint por módulo del diagrama
│   │   ├── servicios/        ← lógica: ledger, padrón, correo, auditoría
│   │   └── seguridad/        ← JWT, RBAC, cifrado, límite de tasa
│   └── tests/                ← 27 pruebas de integración contra PostgreSQL real
├── db/initdb/                ← esquema físico + rol de BD con permisos mínimos
├── frontend/                 ← HTML/CSS/JS sin dependencias externas
├── proxy/                    ← nginx con TLS y cabeceras de seguridad
└── docs/                     ← cambios respecto al documento
```

---

## Puesta en marcha

Requisitos: Docker Desktop (o Docker Engine + Compose v2).

```bash
cp .env.example .env          # en Windows: copy .env.example .env
# Edite .env y cambie los secretos (ver comentarios del archivo)
docker compose up --build
```

| Qué                         | URL                                  |
|-----------------------------|--------------------------------------|
| Votar                       | https://localhost:8443               |
| Panel de administración     | https://localhost:8443/admin.html    |
| Bandeja de correo (OTP)     | http://localhost:8025                |
| API (salud)                 | https://localhost:8443/api/v1/salud  |

> El certificado es autofirmado: el navegador mostrará una advertencia la primera vez. Acéptela
> (en producción se monta un certificado real en el volumen `certificados`).

Con `SEMBRAR_DEMO=true` se crea una elección **abierta** y un padrón de prueba:
documentos `UMB2026001` … `UMB2026010` (correos `estudiante01@umb.edu.co` …).
Las cuentas `admin` y `auditor` usan las contraseñas definidas en `.env`.

### Probar el flujo completo

1. Abra https://localhost:8443, escriba `UMB2026001`, acepte la política de datos y pulse **Enviar código**.
2. Abra http://localhost:8025 y copie el código de 6 dígitos que llegó.
3. Ingrese el código, elija una opción y confirme. Guarde el **número de confirmación**.
4. Intente votar de nuevo con el mismo documento: el sistema lo rechaza.
5. Entre a `/admin.html` como `admin`: **Gestionar** → **Cerrar elección** → **Ver resultados**.
6. Entre como `auditor`: pestaña **Ledger** → **Verificar integridad** y **Ver cadena**.

Para ver la base de datos: `docker compose --profile herramientas up -d adminer` → http://localhost:8081
(servidor `db`). Verá que el documento y el correo están cifrados y que la tabla `voto` no tiene
ningún dato del votante.

### Despliegue en la nube (Railway + Netlify)

| Pieza | Dónde | Configuración |
|---|---|---|
| Frontend | Netlify, carpeta base `frontend/` | `frontend/netlify.toml` reenvía `/api/*` a Railway |
| API | Railway, servicio `api` | Dockerfile `api/Dockerfile` (contexto: raíz del repo) |
| PostgreSQL | Railway, plantilla Postgres | El esquema lo crea la API al arrancar (`DATABASE_ADMIN_URL`) |
| Correo demo | Railway, imagen `axllent/mailpit` | Interfaz protegida con usuario y contraseña |

Variables del servicio `api` en Railway: las mismas de `.env.example`, más
`DATABASE_ADMIN_URL=${{Postgres.DATABASE_URL}}`,
`DATABASE_URL=postgresql://${{APP_DB_USER}}:${{APP_DB_PASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}`,
`SMTP_HOST=mailpit.railway.internal` y `PROXY_SALTOS=2` (Netlify + Railway).

> La URL `*.up.railway.app` de la API también es accesible directamente; quien entre por ahí
> puede falsear su IP ante el límite por IP (los límites por documento siguen aplicando).

---

## API REST — `/api/v1`

Formato JSON. Autenticación con `Authorization: Bearer <JWT>`. Errores: `{"error": {"codigo", "mensaje"}}`.

| Método | Ruta                                   | Rol              | Descripción |
|--------|----------------------------------------|------------------|-------------|
| POST   | `/auth/otp/solicitar`                  | público          | `{documentoInstitucional, eleccionId, aceptaTratamientoDatos: true}` → envía OTP (máx. 3 cada 10 min) |
| POST   | `/auth/otp/verificar`                  | público          | `{documentoInstitucional, eleccionId, codigoOTP}` → JWT de votante (10 min, un solo voto) |
| POST   | `/auth/admin/login`                    | público          | `{usuario, password}` → JWT de 8 h (bcrypt, máx. 5 intentos cada 15 min) |
| POST   | `/auth/logout`                         | cualquiera       | Revoca el JWT |
| POST   | `/votos`                               | votante          | `{opcionId}` → `201 {confirmacion, hashBloque, indiceBloque, timestamp}` |
| GET    | `/elecciones`                          | público / admin  | Público: elecciones abiertas. Admin/auditor: todas |
| GET    | `/elecciones/{id}/opciones`            | público          | Opciones de voto |
| GET    | `/elecciones/{id}/estado`              | votante, admin, auditor | `{estado, totalVotosEmitidos, fechaFin, …}` |
| POST   | `/elecciones`                          | admin            | Crea en BORRADOR `{nombre, fechaInicio, fechaFin, opciones?}` |
| GET    | `/elecciones/{id}`                     | admin, auditor   | Detalle con opciones |
| PUT    | `/elecciones/{id}`                     | admin            | Edita nombre y fechas (solo BORRADOR) |
| PUT    | `/elecciones/{id}/opciones`            | admin            | `{opciones: [{nombre, descripcion}]}` (solo BORRADOR) |
| POST   | `/elecciones/{id}/abrir`               | admin            | BORRADOR → ABIERTA |
| POST   | `/elecciones/{id}/cerrar`              | admin            | ABIERTA → CERRADA + verificación automática del ledger |
| GET    | `/ledger/{eleccionId}/verificar`       | admin, auditor   | `{integro, totalBloques, indiceFalla, motivo, …}` |
| GET    | `/ledger/{eleccionId}/cadena`          | auditor          | Cadena de hashes (sin identidad ni opción) |
| GET    | `/ledger/comprobante/{confirmacion}`   | público          | El votante comprueba que su voto está en la cadena |
| GET    | `/reportes/{eleccionId}`               | admin            | Conteo por opción + integridad (solo con la elección CERRADA) |
| POST   | `/votantes`                            | admin            | Carga el padrón `{votantes: [{documentoInstitucional, correo}]}` |
| GET    | `/votantes/resumen`                    | admin            | Total del padrón y autorizaciones de datos |
| POST   | `/votantes/suprimir`                   | admin            | Habeas data: borra los datos personales (el voto se conserva anónimo) |
| GET    | `/auditoria`                           | admin, auditor   | RegistroAuditoria (`?accion=…&limite=…`) |
| GET    | `/salud`                               | público          | Estado del servicio |

Códigos HTTP según la sección 4 del documento (200, 201, 400, 401, 403, 404, 409, 422, 429, 500)
más 503 cuando no se puede enviar el correo con el OTP.

Ejemplo con `curl` (`-k` acepta el certificado autofirmado):

```bash
E=$(curl -sk https://localhost:8443/api/v1/elecciones | python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
curl -sk -X POST https://localhost:8443/api/v1/auth/otp/solicitar -H "Content-Type: application/json" \
     -d "{\"documentoInstitucional\":\"UMB2026002\",\"eleccionId\":\"$E\",\"aceptaTratamientoDatos\":true}"
```

---

## Seguridad implementada (sección 5 del documento)

| Requisito del documento | Implementación |
|---|---|
| TLS 1.2+ en todos los endpoints | nginx (`proxy/`) con `ssl_protocols TLSv1.2 TLSv1.3`, HSTS y redirección HTTP→HTTPS |
| Cifrado en reposo de datos personales | `pgp_sym_encrypt` (pgcrypto) en documento y correo; búsqueda por HMAC-SHA256 |
| Separación identidad–voto | `emision_token` ya no apunta a `token_voto`; identidad y voto se escriben en transacciones distintas |
| JWT de un solo uso con `jti` | Tabla `jwt_revocado`; el JWT se invalida al llamar `POST /votos`, salga bien o mal |
| Rate limiting del OTP | 3 solicitudes / 10 min por documento + límite por IP; 5 intentos por código |
| RBAC por endpoint | `seguridad/rbac.py`: tabla de permisos, todo lo no listado se deniega |
| Logs de auditoría | Toda acción administrativa en `registro_auditoria` (sin contenido de votos) |
| Ley 1581 — autorización previa | `aceptaTratamientoDatos` obligatorio; se guarda fecha y versión aceptada |
| Ley 1581 — supresión | `POST /votantes/suprimir` |
| Ley 1581 — retención | `flask --app wsgi purgar` (OTP vencidos, JWT expirados) |
| Privacidad en logs | nginx no registra `POST /votos` ni consultas de comprobante; la API no lleva log de accesos |

Además: la API usa un usuario de base de datos **sin** permiso de `UPDATE`/`DELETE` sobre votos,
bloques y auditoría; triggers que impiden modificarlos; OTP guardado como HMAC; contraseñas con bcrypt;
CSP estricta (sin scripts en línea) y contenedores sin root.

---

## Pruebas

27 pruebas de integración contra un PostgreSQL real: flujo completo, doble voto, OTP expirado y
bloqueado, límite de tasa, RBAC, token manipulado, detección de votos alterados / bloques borrados /
votos insertados, anonimato a nivel de esquema, cifrado en reposo, supresión y votos concurrentes.

```bash
docker run -d --name pg-pruebas -p 5433:5432 \
  -e POSTGRES_USER=votoseguro_admin -e POSTGRES_PASSWORD=pruebas postgres:16-alpine
cd api
pip install -r requirements-dev.txt
PGPORT=5433 PGPASSWORD=pruebas pytest        # PowerShell: $env:PGPORT=5433; $env:PGPASSWORD="pruebas"; pytest
```

---

## Diferencias con el documento

Ver [`docs/CAMBIOS_RESPECTO_AL_DOCUMENTO.md`](docs/CAMBIOS_RESPECTO_AL_DOCUMENTO.md). La más importante:
en el modelo físico del documento, `emision_token.token_voto_id` permitía unir
`votante → emision_token → token_voto → voto` con un JOIN, que es justo lo que la sección 5.1 dice
que hay que evitar. El código lo corrige; conviene actualizar el documento.

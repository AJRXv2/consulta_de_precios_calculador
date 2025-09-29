# Calculadora y Consulta de Precios

Aplicación Flask para gestionar proveedores, calcular precios y consultar listas de precios en Excel.

## Características
- Carga y versionado de listas Excel (marca versiones antiguas como `OLD`).
- Búsqueda de productos multi-lista con filtros.
- Calculadora automática y manual con historial persistente.
- Descarga de listas vigentes y antiguas.

## Próximo paso: Migración a PostgreSQL
Actualmente se usan archivos JSON (`datos_v2.json`, `historial.json`). Para producción en Railway se recomienda PostgreSQL.

### Variables de entorno
Crea un archivo `.env` (no se sube al repo) para desarrollo local:
```
FLASK_ENV=development
DATABASE_URL=postgresql://usuario:password@localhost:5432/tu_db
PORT=5000
```
Railway provee `DATABASE_URL` automáticamente.

## Instalación local
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python app_v5.py
```

## Despliegue en Railway
1. Sube el repo a GitHub.
2. En Railway: New Project -> Deploy from GitHub.
3. Agrega variable `PORT` = 8080 (Railway suele inyectar `PORT`).
4. Crea un servicio PostgreSQL y copia su `DATABASE_URL` a variables del servicio web.
5. Ajusta `start` command: `python app_v5.py` (o usa el `Procfile` añadido con `web: python app_v5.py`).
6. (Opcional recomendado) Modifica el código para usar el puerto dinámico `PORT` que Railway inyecta (puedo agregarlo si lo pides).

## Migración de Datos
Usa el script `migrar_json_a_pg.py` para cargar los datos actuales de `datos_v2.json` y `historial.json`.

### Pasos:
```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql://usuario:password@host:puerto/db  # Windows PowerShell: $Env:DATABASE_URL="..."
python migrar_json_a_pg.py
```

Opciones:
--forzar-actualizacion  Actualiza (UPSERT) proveedores ya existentes en la tabla.

El script es idempotente (no duplica historial existente) y crea tablas si faltan.

## Licencia
MIT (ajusta según necesites).

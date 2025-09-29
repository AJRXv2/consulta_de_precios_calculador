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

### Persistencia de archivos Excel (Railway Volume)
Por defecto los Excel se guardan en `listas_excel/` dentro del contenedor. Ese filesystem se pierde en cada nuevo deploy. Para que sobrevivan:

1. Crea un Volume en tu servicio de Railway (ej: nombre `data`, mount path `/data`).
2. Agrega la variable de entorno `LISTAS_PATH=/data/listas_excel`.
3. Redeploy. A partir de ahí las listas nuevas se conservarán.
4. (Opcional) Sube nuevamente las listas actuales para poblar el volumen.

Sin `LISTAS_PATH`, el sistema usa la carpeta local empaquetada (no persistente en PaaS). Posteriormente podrás migrar a base de datos para búsquedas más rápidas.

## Migración de Datos
Usa el script `migrar_json_a_pg.py` para cargar los datos actuales de `datos_v2.json` y `historial.json`.

### Nota sobre error construyendo pandas en Python 3.13
Railway actualmente instala Python 3.13 por defecto en algunos planes. La versión `pandas==2.2.2` puede intentar compilar desde fuente bajo 3.13, tardando mucho o fallando con errores de Meson/Ninja ("standard attributes in middle of decl-specifiers"). Para evitarlo hay dos estrategias:

1. Fijar la versión de Python a 3.12 (hay ruedas pre-compiladas) añadiendo un archivo `.tool-versions` o `runtime.txt` con `python 3.12.6` / `python-3.12.6`.
2. Asegurarse de instalar primero una versión concreta de `numpy` con ruedas (por ejemplo `numpy==1.26.4`) antes de `pandas` en `requirements.txt`.

Este repositorio ya incluye ambos ajustes:
* `runtime.txt` y `.tool-versions` apuntando a Python 3.12.6.
* `requirements.txt` ahora fija `numpy==1.26.4` antes de `pandas`.

Si ya hiciste un deploy fallido, vuelve a desplegar tras estos cambios.
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

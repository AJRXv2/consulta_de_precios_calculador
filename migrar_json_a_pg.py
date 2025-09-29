"""Script de migración de datos locales JSON a PostgreSQL.

Uso:
    python migrar_json_a_pg.py [--forzar-actualizacion]

Requisitos:
    - Variable de entorno DATABASE_URL definida.
    - Dependencias instaladas (psycopg2-binary, python-dotenv).

Comportamiento:
    - Proveedores: Inserta proveedores que NO existan (por id). Con --forzar-actualizacion hace UPSERT.
    - Historial: Inserta solo entradas cuyo id_historial no exista.

Seguro para ejecutar múltiples veces (idempotente, salvo que uses la opción de forzar actualización de proveedores).
"""
from __future__ import annotations
import os
import json
import argparse
from datetime import datetime
from dotenv import load_dotenv

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
except ImportError:
    psycopg2 = None  # type: ignore
    RealDictCursor = None  # type: ignore
    class Json:  # fallback mínimo para tipeo
        def __init__(self, v):
            self.adapted = v

# Cargar .env si existe
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Resolver rutas de los JSON (asumimos este script está en la raíz del proyecto)
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_PATH, "datos_v2.json")
HISTORIAL_FILE = os.path.join(BASE_PATH, "historial.json")


def fail(msg: str):
    print(f"[ERROR] {msg}")
    raise SystemExit(1)


def get_conn():
    if not DATABASE_URL:
        fail("DATABASE_URL no está definida.")
    if not psycopg2:
        fail("psycopg2 no está instalado. Ejecuta: pip install psycopg2-binary")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def ensure_tables():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS proveedores (
                id TEXT PRIMARY KEY,
                data JSONB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS historial (
                id_historial TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                tipo_calculo TEXT,
                proveedor_nombre TEXT,
                producto TEXT,
                precio_base DOUBLE PRECISION,
                porcentajes JSONB,
                precio_final DOUBLE PRECISION,
                observaciones TEXT
            );
            """
        )
        conn.commit()


def cargar_json(path: str, default):
    if not os.path.exists(path):
        print(f"[WARN] No existe {path}, se salta.")
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Error leyendo {path}: {e}. Se usa default.")
        return default


def migrar_proveedores(data: dict, forzar_actualizacion: bool) -> tuple[int,int]:
    """Devuelve (insertados, actualizados)."""
    if not data:
        return (0,0)
    inserted = 0
    updated = 0
    with get_conn() as conn, conn.cursor() as cur:
        # Obtener existentes
        cur.execute("SELECT id FROM proveedores")
        existentes = {r["id"] for r in cur.fetchall()}
        for pid, pdata in data.items():
            if pid in existentes:
                if forzar_actualizacion:
                    cur.execute(
                        "UPDATE proveedores SET data = %s WHERE id = %s",
                        (Json(pdata), pid)
                    )
                    updated += 1
            else:
                cur.execute(
                    "INSERT INTO proveedores (id, data) VALUES (%s, %s)",
                    (pid, Json(pdata))
                )
                inserted += 1
        conn.commit()
    return inserted, updated


def migrar_historial(items: list) -> int:
    if not items:
        return 0
    inserted = 0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id_historial FROM historial")
        existentes = {r["id_historial"] for r in cur.fetchall()}
        for item in items:
            if item.get("id_historial") in existentes:
                continue
            # Asegurar campos faltantes
            cur.execute(
                """
                INSERT INTO historial (id_historial, timestamp, tipo_calculo, proveedor_nombre, producto,
                                       precio_base, porcentajes, precio_final, observaciones)
                VALUES (%(id_historial)s, %(timestamp)s, %(tipo_calculo)s, %(proveedor_nombre)s, %(producto)s,
                        %(precio_base)s, %(porcentajes)s, %(precio_final)s, %(observaciones)s)
                """,
                item
            )
            inserted += 1
        conn.commit()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Migrar datos JSON a PostgreSQL")
    parser.add_argument("--forzar-actualizacion", action="store_true", help="Actualiza proveedores existentes (UPSERT)")
    args = parser.parse_args()

    if not DATABASE_URL:
        fail("Define DATABASE_URL antes de migrar.")
    if not psycopg2:
        fail("Instala psycopg2-binary antes de migrar.")

    ensure_tables()

    proveedores_json = cargar_json(DATA_FILE, {})
    historial_json = cargar_json(HISTORIAL_FILE, [])

    ins_p, upd_p = migrar_proveedores(proveedores_json, args.forzar_actualizacion)
    ins_h = migrar_historial(historial_json)

    print("--- RESUMEN MIGRACIÓN ---")
    print(f"Proveedores insertados: {ins_p}")
    print(f"Proveedores actualizados: {upd_p}")
    print(f"Entradas historial insertadas: {ins_h}")
    print("Listo.")

if __name__ == "__main__":
    main()

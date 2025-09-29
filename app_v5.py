# --- IMPORTACIONES ---
from flask import Flask, render_template, request, send_from_directory, abort
import os
import json
import tempfile
import sys
import webbrowser
from threading import Timer
from waitress import serve
import uuid 
from datetime import datetime
import pandas as pd
import re
import unicodedata
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
except ImportError:  # Permite correr sin PostgreSQL hasta instalar deps
    psycopg2 = None
    RealDictCursor = None
    class Json:  # Fallback mínimo
        def __init__(self, v):
            self.adapted = v
        def getquoted(self):
            return repr(json.dumps(self.adapted))
from dotenv import load_dotenv

try:
    load_dotenv()
except Exception:
    pass

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25MB por archivo
app.config['UPLOAD_EXTENSIONS'] = ['.xlsx', '.xls']
app.config['UPLOAD_FOLDER'] = ''  # Se establecerá luego a LISTAS_PATH

# --- LÓGICA DE RUTAS PERSISTENTES ---
if getattr(sys, 'frozen', False):
    base_path = os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(__file__)

DATA_FILE = os.path.join(base_path, "datos_v2.json") 
HISTORIAL_FILE = os.path.join(base_path, "historial.json") 
LISTAS_PATH = os.path.join(base_path, "listas_excel")

os.makedirs(LISTAS_PATH, exist_ok=True)
app.config['UPLOAD_FOLDER'] = LISTAS_PATH

# --- DB CONFIG ---
DATABASE_URL = os.getenv('DATABASE_URL') if psycopg2 else None

def get_pg_conn():
    if not DATABASE_URL or not psycopg2:
        return None
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def ensure_tables():
    if not DATABASE_URL or not psycopg2:
        return
    with get_pg_conn() as conn, conn.cursor() as cur:
        cur.execute("""
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
        """)
    
ensure_tables()

# --- ESTRUCTURA DE DATOS POR DEFECTO ---
default_proveedores = {
    "p001": {"nombre_base": "Ñañu", "descuento": 0.00, "iva": 0.21, "ganancia": 0.60, "es_dinamico": True},
    "p002": {"nombre_base": "Bermon", "descuento": 0.14, "iva": 0.21, "ganancia": 0.60, "es_dinamico": True},
    "p003": {"nombre_base": "Berger", "descuento": 0.10, "iva": 0.21, "ganancia": 0.60, "es_dinamico": True},
    "p004": {"nombre_base": "Cachan", "descuento": 0.26, "iva": 0.21, "ganancia": 0.50, "es_dinamico": True},
    "p005": {"nombre_base": "BremenTools", "descuento": 0.00, "iva": 0.21, "ganancia": 0.00, "es_dinamico": True},
    "p006": {"nombre_base": "BremenTools", "descuento": 0.00, "iva": 0.105, "ganancia": 0.00, "es_dinamico": True},
    "p007": {"nombre_base": "Crossmaster", "descuento": 0.07, "iva": 0.21, "ganancia": 0.60, "es_dinamico": True},
    "p008": {"nombre_base": "Chiesa", "descuento": 0.00, "iva": 0.21, "ganancia": 0.60, "es_dinamico": True},
    "p009": {"nombre_base": "Chiesa", "descuento": 0.00, "iva": 0.105, "ganancia": 0.60, "es_dinamico": True}
}

# --- FUNCIONES AUXILIARES ---
def normalize_text(text):
    text = str(text)
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]+', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def format_pct(valor):
    num_pct = abs(valor * 100) 
    if num_pct == int(num_pct):
        return f"{int(num_pct):02d}"
    else:
        return f"{num_pct:.1f}"

def generar_nombre_visible(prov_data):
    if not prov_data.get("es_dinamico", False):
        return prov_data.get("nombre_base", "Sin Nombre")
    base = prov_data.get("nombre_base", "")
    desc = prov_data.get("descuento", 0)
    iva = prov_data.get("iva", 0)
    ganc = prov_data.get("ganancia", 0)
    partes_nombre = [base]
    if desc != 0: partes_nombre.append(f"DESC{format_pct(desc)}")
    if iva != 0: partes_nombre.append(f"IVA{format_pct(iva)}")
    if ganc != 0: partes_nombre.append(f"GAN{format_pct(ganc)}")
    return " ".join(partes_nombre)

def parse_percentage(raw):
    if raw is None: return None
    s = str(raw).strip().replace("%", "").replace(",", ".")
    if s == "": return None
    try:
        v = float(s)
    except ValueError: return None
    if v > 1: v = v / 100.0
    return v

def formatear_precio(valor):
    if valor is None or not isinstance(valor, (int, float)):
        return "N/A"
    try:
        valor_float = float(str(valor).replace(",", "."))
        return f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "N/A"

def formatear_pulgadas(nombre_producto):
    if not isinstance(nombre_producto, str):
        return nombre_producto

    # Función interna para reemplazar cada número encontrado
    def reemplazar(match):
        numero = match.group(0) # El número completo, ej: "516"
        
        # Si tiene 3 dígitos, es probable que sea X/16 o X/32. Asumimos /16.
        if len(numero) == 3:
            # Evita convertir números redondos como "100", "200", etc.
            if numero.endswith("00"):
                return numero
            return f"{numero[0]}/{numero[1:]}" # 516 -> 5/16
            
        # Si tiene 4 dígitos, es probable que sea XX/16 o XX/32. Asumimos /16.
        if len(numero) == 4:
            # Evita convertir años o números redondos
            if numero.endswith("00"):
                return numero
            return f"{numero[:2]}/{numero[2:]}" # 1116 -> 11/16

        # Si tiene 2 dígitos, podría ser 1/2, 1/4, 3/4, etc.
        if len(numero) == 2:
            return f"{numero[0]}/{numero[1]}" # 14 -> 1/4

        return numero # Devuelve el número original si no coincide

    # El regex ahora busca cualquier número de 2 a 4 dígitos que esté solo
    # (rodeado de espacios o al final de la cadena) para evitar modificar
    # códigos de producto como "AB1234".
    # \b es un "word boundary" o límite de palabra.
    return re.sub(r'\b(\d{2,4})\b', reemplazar, nombre_producto)

app.jinja_env.globals.update(generar_nombre_visible=generar_nombre_visible, formatear_precio=formatear_precio)

# --- FUNCIONES DB ---
def load_proveedores():
    # PostgreSQL preferente si está disponible
    if DATABASE_URL:
        try:
            with get_pg_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT id, data FROM proveedores")
                rows = cur.fetchall()
                if rows:
                    return {r['id']: r['data'] for r in rows}
                # Si vacío, insertar default
                for pid, pdata in default_proveedores.items():
                    cur.execute("INSERT INTO proveedores (id, data) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (pid, Json(pdata)))
                conn.commit()
                return json.loads(json.dumps(default_proveedores))
        except Exception as e:
            print(f"[WARN] load_proveedores PG fallo: {e}. Se usa JSON local.")
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: no se pudo leer {DATA_FILE} -> usando valores por defecto. Error: {e}")
    return json.loads(json.dumps(default_proveedores))

def save_proveedores(data):
    # Guardar en PostgreSQL si existe
    if DATABASE_URL:
        try:
            with get_pg_conn() as conn, conn.cursor() as cur:
                for pid, pdata in data.items():
                    cur.execute("""
                        INSERT INTO proveedores (id, data) VALUES (%s, %s)
                        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
                    """, (pid, Json(pdata)))
                # Borrar los que no están ya
                cur.execute("SELECT id FROM proveedores")
                ids_db = {r['id'] for r in cur.fetchall()}
                ids_local = set(data.keys())
                for to_del in ids_db - ids_local:
                    cur.execute("DELETE FROM proveedores WHERE id=%s", (to_del,))
                conn.commit()
                return
        except Exception as e:
            print(f"[WARN] save_proveedores PG fallo: {e}. Se intenta fallback JSON.")
    dirpath = os.path.dirname(DATA_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dirpath)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmpf:
            json.dump(data, tmpf, ensure_ascii=False, indent=4)
        os.replace(tmp_path, DATA_FILE)
    except Exception:
        try: os.remove(tmp_path)
        except Exception: pass
        raise

def load_historial():
    if DATABASE_URL:
        try:
            with get_pg_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT * FROM historial ORDER BY timestamp ASC")
                rows = cur.fetchall()
                return rows
        except Exception as e:
            print(f"[WARN] load_historial PG fallo: {e}. Usando JSON local.")
    if not os.path.exists(HISTORIAL_FILE):
        return []
    try:
        with open(HISTORIAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def atomic_save_historial_list(historial_list):
    if DATABASE_URL:
        try:
            with get_pg_conn() as conn, conn.cursor() as cur:
                # estrategia simple: truncar y reinsertar
                cur.execute("DELETE FROM historial")
                for item in historial_list:
                    cur.execute("""
                        INSERT INTO historial (id_historial, timestamp, tipo_calculo, proveedor_nombre, producto,
                                               precio_base, porcentajes, precio_final, observaciones)
                        VALUES (%(id_historial)s, %(timestamp)s, %(tipo_calculo)s, %(proveedor_nombre)s, %(producto)s,
                                %(precio_base)s, %(porcentajes)s, %(precio_final)s, %(observaciones)s)
                    """, item)
                conn.commit()
                return
        except Exception as e:
            print(f"[WARN] atomic_save_historial_list PG fallo: {e}. Fallback JSON.")
    dirpath = os.path.dirname(HISTORIAL_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dirpath)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmpf:
            json.dump(historial_list, tmpf, ensure_ascii=False, indent=4)
        os.replace(tmp_path, HISTORIAL_FILE)
    except Exception:
        try: os.remove(tmp_path)
        except Exception: pass
        raise

def add_entry_to_historial(nueva_entrada):
    if DATABASE_URL:
        try:
            with get_pg_conn() as conn, conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO historial (id_historial, timestamp, tipo_calculo, proveedor_nombre, producto,
                                           precio_base, porcentajes, precio_final, observaciones)
                    VALUES (%(id_historial)s, %(timestamp)s, %(tipo_calculo)s, %(proveedor_nombre)s, %(producto)s,
                            %(precio_base)s, %(porcentajes)s, %(precio_final)s, %(observaciones)s)
                """, nueva_entrada)
                conn.commit()
                return
        except Exception as e:
            print(f"[WARN] add_entry_to_historial PG fallo: {e}. Se usa JSON.")
    historial_actual = load_historial() or []
    historial_actual.append(nueva_entrada)
    atomic_save_historial_list(historial_actual)

# --- ACTUALIZACIÓN DE LISTAS EXCEL ---
def inferir_nombre_base_archivo(nombre_original, proveedores_dict):
    """Intenta inferir el nombre base del proveedor a partir del nombre de archivo subido.
    Compara la porción alfabética normalizada contra los nombres_base existentes.
    """
    base_sin_ext = os.path.splitext(nombre_original)[0]
    letras = ''.join(c for c in base_sin_ext if c.isalpha())
    norm_archivo = normalize_text(letras)
    for p in proveedores_dict.values():
        norm_prov = normalize_text(''.join(c for c in p.get('nombre_base','') if c.isalpha()))
        if norm_prov and (norm_prov in norm_archivo or norm_archivo in norm_prov):
            return p['nombre_base']
    # Si no se encuentra coincidencia devuelve el nombre original sin números
    return letras or base_sin_ext

def humanizar_tiempo_desde(timestamp_segundos):
    try:
        delta = datetime.now() - datetime.fromtimestamp(timestamp_segundos)
        if delta.days > 0:
            return f"{delta.days} día(s) atrás"
        horas = delta.seconds // 3600
        if horas > 0:
            return f"{horas} hora(s) atrás"
        minutos = (delta.seconds % 3600) // 60
        if minutos > 0:
            return f"{minutos} minuto(s) atrás"
        return "Hace instantes"
    except Exception:
        return "-"

# --- LÓGICA DE CÁLCULO ---
proveedores = load_proveedores()

def core_math(precio, iva, descuentos, ganancias):
    precio_actual = precio
    for desc in descuentos:
        if desc is not None: precio_actual *= (1 - desc)
    if iva is not None: precio_actual *= (1 + iva)
    for ganc in ganancias:
        if ganc is not None: precio_actual *= (1 + ganc)
    return round(precio_actual, 4)

# --- RUTA PRINCIPAL ---
@app.route("/", methods=["GET", "POST"])
def index():
    global proveedores 
    mensaje = None
    resultado_auto = None
    resultado_manual = None
    productos_encontrados = None
    proveedor_id_seleccionado = None
    datos_seleccionados = {}
    active_tab = "busqueda" 
    proveedor_buscado = ""
    filtro_resultados = ""
    # --- MODIFICACIÓN ---
    datos_calculo_auto = {}
    datos_calculo_manual = {}

    if request.method == "POST":
        formulario = request.form.get("formulario")
        active_tab = request.form.get("active_tab", "busqueda")

        if formulario == "consulta_producto":
            termino_busqueda = request.form.get("termino_busqueda", "").strip()
            proveedor_buscado = request.form.get("proveedor_busqueda", "") # Capturar proveedor
            filtro_resultados = request.form.get("filtro_resultados", "").strip() # <-- AÑADIR ESTA LÍNEA

            if not termino_busqueda:
                mensaje = "⚠️ POR FAVOR, INGRESA UN CÓDIGO O NOMBRE."
            else:
                productos_encontrados = []
                PROVEEDOR_CONFIG = {
                    'brementools': {'fila_encabezado': 5, 'codigo': ['codigo'], 'producto': ['producto'], 'precios_a_mostrar': ['precio', 'precio de venta', 'precio de lista', 'precio neto unitario'], 'iva': ['iva'], 'extra_datos': ['unidades x caja']},
                    #'bremenbuloneria': {'fila_encabezado': 5, 'codigo': ['codigo'], 'producto': ['producto'], 'precios_a_mostrar': ['precio neto unitario'], 'iva': ['iva'], 'extra_datos': ['rosca', 'terminacion', 'unidades por caja']},
                    'crossmaster': {'fila_encabezado': 11, 'codigo': ['codigo'], 'producto': ['descripcion'], 'precios_a_mostrar': ['precio lista'], 'iva': ['iva'], 'extra_datos': []},
                    'berger': {'fila_encabezado': 0, 'codigo': ['cod'], 'producto': ['detalle'], 'precios_a_mostrar': ['pventa'], 'iva': ['iva'], 'extra_datos': ['marca']},
                    'chiesa': {'fila_encabezado': 1, 'codigo': ['codigo'], 'producto': ['descripcion'], 'precios_a_mostrar': ['pr unit', 'prunit'], 'iva': ['iva'], 'extra_datos': ['dcto', 'oferta']},
                    'cachan': {'fila_encabezado': 0, 'codigo': ['codigo'], 'producto': ['nombre'], 'precios_a_mostrar': ['precio'], 'iva': [], 'extra_datos': ['marca']}
                }

                for filename in os.listdir(LISTAS_PATH):
                    if not filename.endswith(('.xlsx', '.xls')): continue
                    if 'old' in filename.lower():
                        # Saltar archivos marcados como antiguos
                        continue
                    try:
                        nombre_proveedor_archivo = normalize_text(''.join(filter(str.isalpha, os.path.splitext(filename)[0])))
                        
                        # --- LÓGICA DE FILTRADO POR PROVEEDOR ---
                        # Si se seleccionó un proveedor y el nombre del archivo no coincide, saltar al siguiente.
                        if proveedor_buscado and normalize_text(proveedor_buscado) != nombre_proveedor_archivo:
                            continue
                        # --- FIN DE LA LÓGICA DE FILTRADO ---

                        config = PROVEEDOR_CONFIG.get(nombre_proveedor_archivo)
                        if not config: continue

                        proveedor_display_name = next((p.get("nombre_base") for p in proveedores.values() if normalize_text(p.get("nombre_base","")) == nombre_proveedor_archivo), nombre_proveedor_archivo.title())
                        file_path = os.path.join(LISTAS_PATH, filename)
                        
                        header_row_index = config.get('fila_encabezado')
                        if header_row_index is None: continue

                        all_sheets = pd.read_excel(file_path, sheet_name=None, header=header_row_index)

                        for sheet_name, df in all_sheets.items():
                            if df.empty: continue
                            
                            df.columns = [normalize_text(c) for c in df.columns]

                            actual_cols = {
                                'codigo': next((alias for alias in config['codigo'] if alias in df.columns), None),
                                'producto': next((alias for alias in config['producto'] if alias in df.columns), None),
                                'iva': next((alias for alias in config.get('iva', []) if alias in df.columns), None),
                                'precios_a_mostrar': [alias for alias in config.get('precios_a_mostrar', []) if alias in df.columns],
                                'extra_datos': [alias for alias in config.get('extra_datos', []) if alias in df.columns]
                            }
                            if not all([actual_cols['codigo'], actual_cols['producto']]): continue
                            
                            if termino_busqueda.isdigit() and len(termino_busqueda) > 2:
                                df[actual_cols['codigo']] = df[actual_cols['codigo']].apply(lambda x: str(x).split('.')[0] if pd.notna(x) else '')
                                condition = (df[actual_cols['codigo']] == termino_busqueda)
                            else:
                                # Normalizar y convertir el término de búsqueda a formato de pulgadas
                                termino_norm = normalize_text(formatear_pulgadas(termino_busqueda))
                                palabras = termino_norm.split()
                                df[actual_cols['producto']] = df[actual_cols['producto']].apply(lambda x: normalize_text(formatear_pulgadas(x)))
                                # Coincidencia: todas las palabras deben estar presentes en el nombre del producto
                                condition = df[actual_cols['producto']].apply(lambda nombre: all(palabra in nombre for palabra in palabras))
                            # ...existing code...
                            producto_rows = df[condition]

                            if not producto_rows.empty:
                                for i, fila in producto_rows.iterrows():
                                    
                                    # Crear diccionarios base
                                    precios = {col.replace("_", " ").title(): fila.get(col) for col in actual_cols['precios_a_mostrar']}
                                    extra_datos = {col.replace("_", " ").title(): fila.get(col) for col in actual_cols['extra_datos']}
                                    precios_calculados = {}

                                    # --- LÓGICA ESPECIAL PARA PROVEEDORES ---

                                    # Lógica para BremenTools
                                    if nombre_proveedor_archivo == 'brementools':
                                        precio_neto_col = next((alias for alias in ['precio neto unitario'] if alias in df.columns), None)
                                        if precio_neto_col and pd.notna(fila.get(precio_neto_col)):
                                            try:
                                                precio_neto = float(str(fila[precio_neto_col]).replace(",", "."))
                                                precio_final_bremen = precio_neto * 1.21 * 1.60
                                                precios["Precio Final Calculado"] = precio_final_bremen
                                            except (ValueError, TypeError):
                                                pass

                                    # Lógica para Chiesa
                                    if nombre_proveedor_archivo == 'chiesa':
                                        precio_base_col = next((alias for alias in ['pr unit', 'prunit'] if alias in df.columns), None)
                                        if precio_base_col and pd.notna(fila.get(precio_base_col)):
                                            try:
                                                precio_base = float(str(fila[precio_base_col]).replace(",", "."))
                                                dcto_excel = parse_percentage(fila.get('dcto', 0)) or 0.0
                                                oferta_excel = parse_percentage(fila.get('oferta', 0)) or 0.0
                                                
                                                precio_con_4_extra = precio_base * (1 - dcto_excel) * (1 - oferta_excel) * (1 - 0.04)
                                                precios_calculados["Costo (con 4% extra)"] = precio_con_4_extra

                                                precio_sin_4_extra = precio_base * (1 - dcto_excel) * (1 - oferta_excel)
                                                precios_calculados["Costo (sin 4% extra)"] = precio_sin_4_extra
                                            except (ValueError, TypeError):
                                                pass
                                    
                                    # --- FIN DE LÓGICA ESPECIAL ---

                                    producto_iva = "N/A"
                                    if actual_cols['iva'] and pd.notna(fila[actual_cols['iva']]):
                                        try:
                                            iva_val_str = str(fila[actual_cols['iva']]).replace('%','').replace(',','.')
                                            iva_float = float(iva_val_str)
                                            if iva_float < 1.0 and iva_float != 0: iva_float *= 100
                                            producto_iva = f"{iva_float:.1f}%".replace(".0%", "%")
                                        except: producto_iva = str(fila[actual_cols['iva']])
                                    
                                    productos_encontrados.append({
                                        "codigo": fila[actual_cols['codigo']], "producto": formatear_pulgadas(fila[actual_cols['producto']]),
                                        "proveedor": f"{proveedor_display_name} (Hoja: {sheet_name})", "iva": producto_iva, 
                                        "precios": precios, 
                                        "extra_datos": extra_datos,
                                        "precios_calculados": precios_calculados
                                    })
                    except Exception as e:
                        mensaje = f"❌ ERROR PROCESANDO {filename}: {e}"
                
                # --- NUEVO BLOQUE PARA FILTRAR RESULTADOS ---
                if filtro_resultados and productos_encontrados:
                    productos_filtrados = []
                    filtro_norm = normalize_text(filtro_resultados)
                    for producto in productos_encontrados:
                        # Busca el filtro en el nombre, código o marca del producto
                        texto_busqueda = f"{producto['producto']} {producto['codigo']} {producto.get('extra_datos', {}).get('Marca', '')}"
                        if filtro_norm in normalize_text(texto_busqueda):
                            productos_filtrados.append(producto)
                    
                    mensaje = f"✅ SE ENCONTRARON {len(productos_filtrados)} COINCIDENCIA(S) AL FILTRAR POR '{filtro_resultados}'."
                    productos_encontrados = productos_filtrados
                # --- FIN DEL BLOQUE DE FILTRADO ---

                if not productos_encontrados and not mensaje:
                    mensaje = f"ℹ️ NO SE ENCONTRARON RESULTADOS PARA '{termino_busqueda}'."
                elif productos_encontrados:
                    mensaje = f"✅ SE ENCONTRARON {len(productos_encontrados)} COINCIDENCIA(S)."
        
        elif formulario == "calcular_auto":
            datos_calculo_auto = {k: v for k, v in request.form.items()} # Capturar datos
            proveedor_id = request.form.get("proveedor_id")
            precio_raw = request.form.get("precio")
            producto_label = request.form.get("auto_producto", "") # Capturar el producto opcional

            if proveedor_id and precio_raw:
                try:
                    precio = float(precio_raw.replace(".", "").replace(",", "."))
                    datos_prov = proveedores.get(proveedor_id)
                    descuentos = [datos_prov.get("descuento", 0)]
                    ganancias = [datos_prov.get("ganancia", 0)]
                    iva = datos_prov.get("iva", 0)
                    precio_final = core_math(precio, iva, descuentos, ganancias)
                    
                    nombre_visible_prov = generar_nombre_visible(proveedores[proveedor_id])
                    resultado_auto = f"{formatear_precio(precio_final)} (Proveedor: {nombre_visible_prov})"
                    add_entry_to_historial({
                        "id_historial": str(uuid.uuid4()), "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "tipo_calculo": "Automático", "proveedor_nombre": nombre_visible_prov,
                        "producto": producto_label or "N/A", # Guardar el producto
                        "precio_base": precio, "porcentajes": {"descuento": descuentos[0], "iva": iva, "ganancia": ganancias[0]},
                        "precio_final": precio_final, "observaciones": ""
                    })
                except Exception as e:
                    mensaje = f"⚠️ ERROR CÁLCULO AUTO: {e}"
            else:
                mensaje = "⚠️ COMPLETA PROVEEDOR Y PRECIO."

        elif formulario == "calcular_manual":
            datos_calculo_manual = {k: v for k, v in request.form.items()} # Capturar datos
            
            precio_raw = datos_calculo_manual.get("manual_precio")
            if precio_raw:
                try:
                    precio = float(precio_raw.replace(".", "").replace(",", "."))
                    nombre_prov_label = datos_calculo_manual.get("manual_proveedor_label", "").strip() or "N/A"
                    producto_label = datos_calculo_manual.get("manual_producto", "")
                    obs_label = datos_calculo_manual.get("manual_observaciones", "")

                    desc_manual = parse_percentage(datos_calculo_manual.get("manual_descuento")) or 0.0
                    desc_extra1 = parse_percentage(datos_calculo_manual.get("desc_extra_1")) or 0.0
                    desc_extra2 = parse_percentage(datos_calculo_manual.get("desc_extra_2")) or 0.0
                    
                    iva_manual = parse_percentage(datos_calculo_manual.get("manual_iva")) or 0.0
                    
                    ganc_manual = parse_percentage(datos_calculo_manual.get("manual_ganancia")) or 0.0
                    ganc_extra = parse_percentage(datos_calculo_manual.get("ganancia_extra")) or 0.0

                    descuentos = [desc_manual, desc_extra1, desc_extra2]
                    ganancias = [ganc_manual, ganc_extra]
                    
                    precio_final = core_math(precio, iva_manual, descuentos, ganancias)
                    resultado_manual = f"{formatear_precio(precio_final)}"
                    
                    mensaje = "✅ Cálculo Manual Realizado y Guardado en Historial."
                    
                    add_entry_to_historial({
                        "id_historial": str(uuid.uuid4()), "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "tipo_calculo": "Manual", "proveedor_nombre": nombre_prov_label, 
                        "producto": producto_label or "N/A", "precio_base": precio,
                        "porcentajes": {
                            "descuento": desc_manual, "descuento_extra_1": desc_extra1, "descuento_extra_2": desc_extra2,
                            "iva": iva_manual, "ganancia": ganc_manual, "ganancia_extra": ganc_extra
                        },
                        "precio_final": precio_final, "observaciones": obs_label or ""
                    })
                except Exception as e:
                    mensaje = f"⚠️ ERROR CÁLCULO MANUAL: {e}"
            else:
                mensaje = "⚠️ PRECIO MANUAL NO PUEDE ESTAR VACÍO."
        
        elif formulario == "editar":
            proveedor_id_seleccionado = request.form.get("editar_proveedor_id")
            if "guardar" in request.form and proveedor_id_seleccionado:
                target_data = proveedores.get(proveedor_id_seleccionado, {})
                target_data["nombre_base"] = request.form.get("edit_nombre_base", target_data["nombre_base"])
                target_data["es_dinamico"] = request.form.get("edit_es_dinamico") == "true"
                for clave in ["descuento", "iva", "ganancia"]:
                    parsed = parse_percentage(request.form.get(clave))
                    if parsed is not None:
                        target_data[clave] = parsed
                proveedores[proveedor_id_seleccionado] = target_data
                try:
                    save_proveedores(proveedores)
                    mensaje = "✅ CAMBIOS GUARDADOS."
                except Exception as e:
                    mensaje = f"❌ ERROR GUARDANDO DATOS.JSON: {e}"
            if proveedor_id_seleccionado:
                datos_seleccionados = proveedores.get(proveedor_id_seleccionado, {})

        elif formulario == "agregar":
            nombre_base = request.form.get("nuevo_nombre_base", "").strip()
            if not nombre_base:
                mensaje = "⚠️ ERROR: EL NOMBRE BASE NO PUEDE ESTAR VACÍO."
            else:
                proveedores[str(uuid.uuid4())] = {
                    "nombre_base": nombre_base, "es_dinamico": request.form.get("nuevo_es_dinamico") == "true",
                    "descuento": parse_percentage(request.form.get("nuevo_descuento")) or 0.0,
                    "iva": parse_percentage(request.form.get("nuevo_iva")) or 0.0,
                    "ganancia": parse_percentage(request.form.get("nuevo_ganancia")) or 0.0
                }
                try:
                    save_proveedores(proveedores)
                    mensaje = f"✅ PROVEEDOR '{nombre_base}' AÑADIDO."
                except Exception as e:
                    mensaje = f"❌ ERROR GUARDANDO DATOS.JSON: {e}"

        elif formulario == "borrar":
            proveedor_id_a_borrar = request.form.get("borrar_proveedor_id")
            if proveedor_id_a_borrar and proveedor_id_a_borrar in proveedores:
                nombre_borrado = generar_nombre_visible(proveedores.pop(proveedor_id_a_borrar))
                try:
                    save_proveedores(proveedores)
                    mensaje = f"✅ PROVEEDOR '{nombre_borrado}' BORRADO."
                except Exception as e:
                    mensaje = f"❌ ERROR GUARDANDO DATOS.JSON: {e}"
            else:
                mensaje = "⚠️ ERROR: PROVEEDOR NO ENCONTRADO O NO SELECCIONADO."
        
        elif formulario == "borrar_historial_seleccionado":
            ids_para_borrar = request.form.getlist("historial_ids_a_borrar")
            if ids_para_borrar:
                nuevo_historial = [item for item in load_historial() if item.get("id_historial") not in ids_para_borrar]
                try:
                    atomic_save_historial_list(nuevo_historial)
                    mensaje = f"✅ {len(ids_para_borrar)} ENTRADA(S) BORRADA(S)."
                except Exception as e:
                    mensaje = f"❌ ERROR GUARDANDO HISTORIAL: {e}"
            else:
                mensaje = "ℹ️ NO SE SELECCIONÓ NINGUNA ENTRADA."

        elif formulario == "borrar_todo_historial":
            try:
                atomic_save_historial_list([])
                mensaje = "✅ TODO EL HISTORIAL BORRADO."
            except Exception as e:
                mensaje = f"❌ ERROR BORRANDO TODO EL HISTORIAL: {e}"

        elif formulario == "subir_lista":
            # Manejo de carga de archivos Excel
            active_tab = "gestion"  # Permanecer en gestión tras subir
            archivos = request.files.getlist('archivos_excel')
            override_prov = request.form.get('proveedor_archivo', '').strip()
            incluir_dia = request.form.get('incluir_dia') == 'true'
            resultados_subida = []
            if not archivos or (len(archivos) == 1 and archivos[0].filename == ''):
                mensaje = "⚠️ NO SE SELECCIONÓ NINGÚN ARCHIVO."  # no early return, continuamos
            else:
                for archivo in archivos:
                    nombre_orig = archivo.filename
                    ext = os.path.splitext(nombre_orig)[1].lower()
                    if ext not in app.config['UPLOAD_EXTENSIONS']:
                        resultados_subida.append(f"❌ {nombre_orig}: extensión no permitida")
                        continue
                    try:
                        nombre_base = override_prov or inferir_nombre_base_archivo(nombre_orig, proveedores)
                        # Construir fecha
                        fecha_formato = "%d%m%Y" if incluir_dia else "%m%Y"
                        fecha_str = datetime.now().strftime(fecha_formato)
                        nombre_final = f"{nombre_base}-{fecha_str}{ext}"
                        ruta_final = os.path.join(LISTAS_PATH, nombre_final)
                        # Marcar como OLD las listas previas vigentes del mismo proveedor
                        try:
                            norm_prov_subida = normalize_text(nombre_base)
                            for existing in os.listdir(LISTAS_PATH):
                                if not existing.lower().endswith(('.xlsx','.xls')): continue
                                if 'old' in existing.lower():
                                    continue
                                prov_part = os.path.splitext(existing)[0].split('-')[0]
                                if normalize_text(prov_part) == norm_prov_subida:
                                    old_src = os.path.join(LISTAS_PATH, existing)
                                    base_no_ext, ext_exist = os.path.splitext(existing)
                                    propuesta = f"{base_no_ext}-OLD{ext_exist}"
                                    old_dst = os.path.join(LISTAS_PATH, propuesta)
                                    if os.path.exists(old_dst):
                                        # evitar colisión añadiendo timestamp
                                        ts = datetime.now().strftime('%H%M%S')
                                        old_dst = os.path.join(LISTAS_PATH, f"{base_no_ext}-OLD-{ts}{ext_exist}")
                                    os.rename(old_src, old_dst)
                        except Exception as e_mark:
                            resultados_subida.append(f"⚠️ Aviso al marcar OLD previas: {e_mark}")
                        # Guardar (overwrite permitido)
                        archivo.save(ruta_final)
                        resultados_subida.append(f"✅ {nombre_orig} -> {nombre_final}")
                    except Exception as e:
                        resultados_subida.append(f"❌ {nombre_orig}: error {e}")
                mensaje = " | ".join(resultados_subida)

    historial = load_historial()
    historial.reverse() 
    lista_proveedores_display = sorted([(p_id, generar_nombre_visible(p_data)) for p_id, p_data in proveedores.items()], key=lambda x: x[1])
    
    # Crear lista única de nombres base de proveedores para el dropdown
    lista_nombres_proveedores = sorted(list(set(p_data['nombre_base'] for p_data in proveedores.values())))

    # --- Calcular últimas actualizaciones de archivos Excel ---
    ultimas_actualizaciones = {}
    try:
        for fname in os.listdir(LISTAS_PATH):
            if not fname.lower().endswith(('.xlsx', '.xls')):
                continue
            ruta = os.path.join(LISTAS_PATH, fname)
            try:
                mtime = os.path.getmtime(ruta)
            except Exception:
                continue
            provider_part = os.path.splitext(fname)[0].split('-')[0]
            norm_provider_part = normalize_text(provider_part)
            nombre_match = next((p['nombre_base'] for p in proveedores.values() if normalize_text(p['nombre_base']) == norm_provider_part), provider_part)
            data_existente = ultimas_actualizaciones.get(nombre_match)
            if not data_existente or mtime > data_existente['mtime']:
                ultimas_actualizaciones[nombre_match] = {
                    'filename': fname,
                    'mtime': mtime,
                    'fecha': datetime.fromtimestamp(mtime).strftime('%d/%m/%Y %H:%M'),
                    'hace': humanizar_tiempo_desde(mtime)
                }
    except Exception:
        pass
    ultimas_actualizaciones_list = sorted([
        {'proveedor': k, **v} for k, v in ultimas_actualizaciones.items()
    ], key=lambda x: x['proveedor'])

    # Listas vigentes y antiguas para descarga
    listas_vigentes = []
    listas_old = []
    try:
        for fname in os.listdir(LISTAS_PATH):
            if not fname.lower().endswith(('.xlsx','.xls')): continue
            full_path = os.path.join(LISTAS_PATH, fname)
            info = {
                'filename': fname,
                'fecha': datetime.fromtimestamp(os.path.getmtime(full_path)).strftime('%d/%m/%Y %H:%M')
            }
            if 'old' in fname.lower():
                listas_old.append(info)
            else:
                listas_vigentes.append(info)
        listas_vigentes.sort(key=lambda x: x['filename'])
        listas_old.sort(key=lambda x: x['filename'])
    except Exception:
        pass


    return render_template(
        "index_v5.html",
        proveedores_lista=lista_proveedores_display,
        resultado_auto=resultado_auto,
        resultado_manual=resultado_manual,
        productos_encontrados=productos_encontrados,
        mensaje=mensaje,
        proveedor_id_seleccionado=proveedor_id_seleccionado,
        datos_seleccionados=datos_seleccionados,
        historial=historial,
        active_tab=active_tab,
        lista_nombres_proveedores=lista_nombres_proveedores,
        proveedor_buscado=proveedor_buscado,
        filtro_resultados=filtro_resultados,
        # --- MODIFICACIÓN ---
        datos_calculo_auto=datos_calculo_auto,
        datos_calculo_manual=datos_calculo_manual,
        ultimas_actualizaciones=ultimas_actualizaciones_list,
        listas_path=LISTAS_PATH,
        listas_vigentes=listas_vigentes,
        listas_old=listas_old
    )

@app.route('/download_lista/<path:filename>')
def download_lista(filename):
    # Seguridad básica: evitar path traversal
    if '..' in filename or filename.startswith('/'):
        abort(400)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in app.config['UPLOAD_EXTENSIONS']:
        abort(404)
    file_path = os.path.join(LISTAS_PATH, filename)
    if not os.path.isfile(file_path):
        abort(404)
    return send_from_directory(LISTAS_PATH, filename, as_attachment=True)

def abrir_navegador():
    webbrowser.open_new('http://127.0.0.1:5000/')

if __name__ == "__main__":
    # Puerto dinámico para plataformas como Railway / Render / Heroku
    port = int(os.getenv("PORT", 5000))
    # Abrir navegador solo si es entorno local (heurística: no hay PORT externo)
    if port == 5000:
        try:
            Timer(1, abrir_navegador).start()
        except Exception:
            pass
    print(f"Iniciando servidor en http://0.0.0.0:{port}/ (Waitress)")
    print(f"Las listas de precios en formato Excel deben guardarse en: {LISTAS_PATH}")
    serve(app, host='0.0.0.0', port=port)
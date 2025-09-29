import pandas as pd
import os

# Cambia este nombre de archivo si el tuyo se llama diferente
NOMBRE_ARCHIVO_CHIESA = "Chiesa-092025.xlsx"
CARPETA_LISTAS = "listas_excel"

file_path = os.path.join(CARPETA_LISTAS, NOMBRE_ARCHIVO_CHIESA)

if not os.path.exists(file_path):
    print(f"--- ¡ERROR! ---")
    print(f"No se encontró el archivo '{file_path}'.")
    print(f"Asegúrate de que el nombre del archivo en la línea 5 de este script sea el correcto y que el archivo esté en la carpeta '{CARPETA_LISTAS}'.")
else:
    print(f"--- Analizando el archivo: {file_path} ---")
    try:
        # Intentamos leer el archivo con varias filas de encabezado posibles
        for i in range(5):
            print(f"\n=== INTENTO DE LECTURA (Encabezado en Fila {i + 1}) ===")
            # Leemos todas las hojas porque no sabemos en cuál están los datos
            all_sheets = pd.read_excel(file_path, sheet_name=None, header=i)
            
            # Analizamos la primera hoja que encontremos con datos
            for sheet_name, df in all_sheets.items():
                if not df.empty:
                    print(f"  > Analizando Hoja: '{sheet_name}'")
                    print(f"  > Columnas detectadas: {df.columns.tolist()}")
                    print("-------------------------------------------------")
                    break # Solo necesitamos analizar la primera hoja con contenido para este test
            
    except Exception as e:
        print(f"\n--- ¡ERROR INESPERADO! ---")
        print(f"Ocurrió un error al intentar leer el archivo: {e}")
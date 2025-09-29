import os
import sys

print("--- INICIANDO TEST DE RUTA ---")

# Esta es la misma lógica que usa tu aplicación para encontrar su ubicación
if getattr(sys, 'frozen', False):
    # Si se ejecuta como un .exe compilado
    base_path = os.path.dirname(sys.executable)
    print(f"Modo de ejecución: Compilado (.exe)")
else:
    # Si se ejecuta como un script de python (.py)
    base_path = os.path.dirname(__file__)
    print(f"Modo de ejecución: Script (.py)")

print(f"\n1. La ruta base del programa es:")
print(f"   '{base_path}'")

# Construimos la ruta a la carpeta de las listas
listas_path = os.path.join(base_path, "listas_excel")
print(f"\n2. El programa buscará los archivos Excel en esta carpeta:")
print(f"   '{listas_path}'")

# Revisamos si la carpeta existe y qué contiene
print(f"\n3. Revisando la carpeta...")
if os.path.exists(listas_path):
    print(f"   -> ¡ÉXITO! La carpeta '{listas_path}' fue encontrada.")
    try:
        contenido = os.listdir(listas_path)
        if not contenido:
            print(f"   -> La carpeta existe, pero está VACÍA.")
        else:
            print(f"   -> La carpeta contiene los siguientes archivos:")
            for item in contenido:
                print(f"      - {item}")
    except Exception as e:
        print(f"   -> ERROR: No se pudo leer el contenido de la carpeta. Mensaje: {e}")
else:
    print(f"   -> ¡FALLA! La carpeta '{listas_path}' NO fue encontrada.")

print("\n--- FIN DEL TEST ---")
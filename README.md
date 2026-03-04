# glucoapp

Aplicación sencilla para el control de glucometría implementada con Streamlit.

Descripción
- Punto de entrada: `app.py`.
- Base de datos SQLite local: `glucocontrol.db` (se crea/usa en la misma carpeta al iniciar la app).

Requisitos
- Python 3.10+ recomendado
- Dependencias listadas en `requirements.txt` (principalmente `streamlit` y `pandas`).

Instalación y ejecución (Windows - cmd.exe)

1) Crear y activar un entorno virtual (recomendado):

```cmd
cd C:\devpython\glucoapp
python -m venv .venv
.venv\Scripts\activate
```

2) Instalar dependencias:

```cmd
pip install -r requirements.txt
```

3) Ejecutar la aplicación con Streamlit:

```cmd
streamlit run app.py
```

Notas importantes
- Al ejecutarla por primera vez se crea `glucocontrol.db` en la carpeta del proyecto.
- Hay un usuario administrador por defecto creado (username: `admin`, password: `admin123`). Cámbialo o elimínalo en producción.
- Haz copia de seguridad de `glucocontrol.db` si vas a modificar datos importantes.

Estructura esencial
- `app.py` — lógica principal de la app (autenticación, dashboards de admin y usuario, formularios y almacenamiento en SQLite).

Siguientes pasos recomendados
- Crear un archivo `.gitignore` que excluya la base de datos (`glucocontrol.db`) y los entornos virtuales (`.venv/`).
- Si quieres, puedo añadir un script `.bat` para iniciar la app en Windows con un doble clic.

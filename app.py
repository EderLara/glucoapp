import streamlit as st
import sqlite3
import pandas as pd
import datetime
import hashlib
import re

# ==========================================
# 1. CONFIGURACIÓN Y BASE DE DATOS
# ==========================================
st.set_page_config(page_title="Control Glucometría", page_icon="🩸", layout="wide")

DB_FILE = 'glucocontrol.db'

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    # Tabla de Usuarios
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT NOT NULL)''')
    # Tabla de Registros de Glucosa
    c.execute('''CREATE TABLE IF NOT EXISTS glucometries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    value REAL NOT NULL,
                    record_date TEXT NOT NULL,
                    record_time TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id))''')
    # Tabla de Accesos
    c.execute('''CREATE TABLE IF NOT EXISTS access_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    login_timestamp TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id))''')
    
    # Crear usuario administrador por defecto si no existe
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", 
                  ('admin', hash_password('admin123'), 'admin'))
    
    conn.commit()
    conn.close()

# ==========================================
# 2. FUNCIONES DE AUTENTICACIÓN
# ==========================================
def login_user(username, password):
    conn = get_connection()
    c = conn.cursor()
    hashed_pw = hash_password(password)
    c.execute("SELECT id, username, role FROM users WHERE username=? AND password=?", (username, hashed_pw))
    user = c.fetchone()
    
    if user:
        # Registrar el acceso
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO access_logs (user_id, login_timestamp) VALUES (?, ?)", (user[0], now))
        conn.commit()
    
    conn.close()
    return user

def register_user(username, password):
    """Registra un usuario con `username` (debe ser un correo electrónico) y `password`.

    Devuelve una tupla (success: bool, message: str).
    """
    # Validar que el username sea un correo electrónico simple
    email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    if not username or not re.match(email_regex, username):
        return False, "El nombre de usuario debe ser un correo electrónico válido."

    # Validar longitud mínima de contraseña
    if not password or len(password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."

    conn = get_connection()
    c = conn.cursor()

    # Verificar existencia previa para dar un mensaje claro
    c.execute("SELECT id FROM users WHERE username=?", (username,))
    if c.fetchone():
        conn.close()
        return False, "El correo ya está registrado. Elige otro."

    try:
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", 
                  (username, hash_password(password), 'user'))
        conn.commit()
        conn.close()
        return True, "Usuario registrado exitosamente."
    except sqlite3.IntegrityError:
        # En caso de carrera u otra condición, manejar la duplicación
        conn.close()
        return False, "El correo ya está registrado. Elige otro."

def update_password(user_id, new_password):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET password=? WHERE id=?", (hash_password(new_password), user_id))
    conn.commit()
    conn.close()

# ==========================================
# 3. PANELES DE CONTROL (DASHBOARDS)
# ==========================================

def admin_dashboard(user_id): # <-- AHORA RECIBE EL user_id
    st.header("👑 Panel de Administración")
    
    # --- NUEVO: FORMULARIO PARA CAMBIAR CONTRASEÑA ---
    with st.expander("🔐 Cambiar Contraseña de Administrador"):
        with st.form("change_password_form", clear_on_submit=True):
            current_password = st.text_input("Contraseña Actual", type="password")
            new_password = st.text_input("Nueva Contraseña", type="password")
            confirm_password = st.text_input("Confirmar Nueva Contraseña", type="password")
            
            submitted_pw = st.form_submit_button("Actualizar Contraseña")
            
            if submitted_pw:
                # Verificar que la contraseña actual sea correcta
                conn = get_connection()
                c = conn.cursor()
                c.execute("SELECT password FROM users WHERE id=?", (user_id,))
                stored_hashed_pw = c.fetchone()[0]
                conn.close()
                
                if hash_password(current_password) != stored_hashed_pw:
                    st.error("La contraseña actual es incorrecta.")
                elif new_password != confirm_password:
                    st.error("Las contraseñas nuevas no coinciden.")
                elif len(new_password) < 6:
                    st.error("La nueva contraseña debe tener al menos 6 caracteres para ser segura.")
                else:
                    update_password(user_id, new_password)
                    st.success("¡Contraseña actualizada exitosamente!")
    
    st.divider()

    # --- RESTO DEL DASHBOARD ADMIN (Sin cambios) ---
    conn = get_connection()
    
    # Métricas generales
    st.subheader("Estadísticas Generales")
    col1, col2 = st.columns(2)
    
    users_df = pd.read_sql_query("SELECT id, username, role FROM users WHERE role='user'", conn)
    total_users = len(users_df)
    col1.metric("Usuarios Registrados (Pacientes)", total_users)
    
    gluco_df = pd.read_sql_query("SELECT * FROM glucometries", conn)
    total_records = len(gluco_df)
    col2.metric("Total de Registros de Glucometría", total_records)
    
    st.divider()
    
    # Promedios y Registros por Usuario
    st.subheader("Detalle por Usuario")
    if not users_df.empty:
        query_stats = """
        SELECT u.username AS Usuario, 
               COUNT(g.id) AS Cantidad_Registros, 
               ROUND(AVG(g.value), 2) AS Promedio_Glucosa
        FROM users u
        LEFT JOIN glucometries g ON u.id = g.user_id
        WHERE u.role = 'user'
        GROUP BY u.id
        """
        stats_df = pd.read_sql_query(query_stats, conn)
        st.dataframe(stats_df, use_container_width=True)
    else:
        st.info("No hay pacientes registrados aún.")
        
    st.divider()
    
    # Registro de Accesos
    st.subheader("Registro de Accesos por Usuario")
    query_logs = """
    SELECT u.username AS Usuario, a.login_timestamp AS Fecha_Hora_Acceso
    FROM access_logs a
    JOIN users u ON a.user_id = u.id
    ORDER BY a.login_timestamp DESC
    LIMIT 50
    """
    logs_df = pd.read_sql_query(query_logs, conn)
    st.dataframe(logs_df, use_container_width=True)
    
    conn.close()

def user_dashboard(user_id, username):
    st.header(f"👋 Bienvenido, {username}")
    st.write("Mantener tu glucosa controlada es el mejor paso para cuidar tu salud.")
    
    conn = get_connection()
    today = datetime.date.today()
    
    # --- FORMULARIO DE INGRESO ---
    st.subheader("📝 Nuevo Registro de Glucometría")
    with st.form("gluco_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            gluco_val = st.number_input("Nivel de Glucosa (mg/dL)", min_value=20.0, max_value=600.0, step=1.0)
        with col2:
            gluco_date = st.date_input("Fecha", value=today)
        with col3:
            gluco_time = st.time_input("Hora", value=datetime.datetime.now().time())
            
        submitted = st.form_submit_button("Guardar Registro")
        if submitted:
            c = conn.cursor()
            c.execute("INSERT INTO glucometries (user_id, value, record_date, record_time) VALUES (?, ?, ?, ?)",
                      (user_id, gluco_val, gluco_date.strftime("%Y-%m-%d"), gluco_time.strftime("%H:%M")))
            conn.commit()
            st.success("¡Registro guardado exitosamente!")
            
    st.divider()
    
    # --- TARJETAS DE MÉTRICAS ---
    st.subheader("📊 Tus Estadísticas Recientes")
    
    # Calcular fechas
    date_7_days_ago = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    date_3_days_ago = (today - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    date_yesterday = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")
    
    # Consultas
    query_week = "SELECT AVG(value) FROM glucometries WHERE user_id=? AND record_date >= ?"
    query_3days = "SELECT AVG(value) FROM glucometries WHERE user_id=? AND record_date >= ?"
    query_yesterday = "SELECT value, record_time FROM glucometries WHERE user_id=? AND record_date = ?"
    
    c = conn.cursor()
    c.execute(query_week, (user_id, date_7_days_ago))
    avg_week = c.fetchone()[0]
    
    c.execute(query_3days, (user_id, date_3_days_ago))
    avg_3days = c.fetchone()[0]
    
    c.execute(query_yesterday, (user_id, date_yesterday))
    yest_records = c.fetchall()

    col1, col2, col3 = st.columns(3)
    
    with col1:
        val = f"{avg_week:.1f}" if avg_week else "N/A"
        st.metric("Promedio Semanal", f"{val} mg/dL")
        
    with col2:
        val = f"{avg_3days:.1f}" if avg_3days else "N/A"
        st.metric("Promedio Últimos 3 Días", f"{val} mg/dL")
        
    with col3:
        if yest_records:
            # Mostrar los valores de ayer como una lista separada por comas
            vals = [f"{r[0]:.0f}" for r in yest_records]
            st.metric("Valores de Ayer", ", ".join(vals))
        else:
            st.metric("Valores de Ayer", "Sin registros")

    # Mostrar tabla con el historial personal
    with st.expander("Ver todo mi historial"):
        history_df = pd.read_sql_query(
            "SELECT record_date AS Fecha, record_time AS Hora, value AS 'Glucosa (mg/dL)' FROM glucometries WHERE user_id=? ORDER BY record_date DESC, record_time DESC", 
            conn, params=(user_id,)
        )
        st.dataframe(history_df, use_container_width=True)

    conn.close()

# ==========================================
# 4. FLUJO PRINCIPAL DE LA APLICACIÓN
# ==========================================
def main():
    init_db()
    
    # Manejo de estado de sesión
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['user_id'] = None
        st.session_state['username'] = None
        st.session_state['role'] = None

    if not st.session_state['logged_in']:
        st.title("🩸 Control de Glucometría")
        
        tab1, tab2 = st.tabs(["Iniciar Sesión", "Registrarse"])
        
        with tab1:
            st.subheader("Ingresa a tu cuenta")
            username = st.text_input("Usuario", key="login_user")
            password = st.text_input("Contraseña", type="password", key="login_pass")
            if st.button("Ingresar"):
                user = login_user(username, password)
                if user:
                    st.session_state['logged_in'] = True
                    st.session_state['user_id'] = user[0]
                    st.session_state['username'] = user[1]
                    st.session_state['role'] = user[2]
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.")
                    
        with tab2:
            st.subheader("Crea una cuenta nueva")
            new_user = st.text_input("Nuevo Usuario", key="reg_user")
            new_pass = st.text_input("Nueva Contraseña", type="password", key="reg_pass")
            if st.button("Registrarse"):
                if new_user and new_pass:
                    success, msg = register_user(new_user, new_pass)
                    if success:
                        st.success(msg + " Por favor inicia sesión.")
                    else:
                        st.error(msg)
                else:
                    st.warning("Por favor llena todos los campos.")
    
    else:
        # Menú lateral para cerrar sesión
        with st.sidebar:
            st.write(f"Conectado como: **{st.session_state['username']}**")
            if st.button("Cerrar Sesión"):
                st.session_state['logged_in'] = False
                st.session_state['user_id'] = None
                st.session_state['username'] = None
                st.session_state['role'] = None
                st.rerun()
        
         # Enrutamiento según el rol
        if st.session_state['role'] == 'admin':
            admin_dashboard(st.session_state['user_id']) 

        else:
            user_dashboard(st.session_state['user_id'], st.session_state['username'])

if __name__ == '__main__':
    main()
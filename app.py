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
    
    # Tabla de auditoría de acciones administrativas
    c.execute('''CREATE TABLE IF NOT EXISTS admin_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_user_id INTEGER,
                    record_id INTEGER,
                    timestamp TEXT NOT NULL,
                    details TEXT,
                    FOREIGN KEY(admin_user_id) REFERENCES users(id),
                    FOREIGN KEY(target_user_id) REFERENCES users(id))''')
    
    # Crear usuario administrador por defecto si no existe
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", 
                  ('admin', hash_password('admin123'), 'admin'))
    
    conn.commit()
    conn.close()

# ==========================================
# 2. FUNCIONES DE AUTENTICACIÓN Y DB CRUD
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

# Nuevas funciones CRUD para registros de glucometría
def update_glucometry(record_id, value, record_date, record_time):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE glucometries SET value=?, record_date=?, record_time=? WHERE id=?", (value, record_date, record_time, record_id))
    conn.commit()
    conn.close()

def delete_glucometry(record_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM glucometries WHERE id=?", (record_id,))
    conn.commit()
    conn.close()


# --- Funciones de auditoría ---
def log_admin_action(admin_user_id, action, target_user_id, record_id, details=None):
    """Registra una acción administrativa en la tabla admin_audit."""
    conn = get_connection()
    c = conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO admin_audit (admin_user_id, action, target_user_id, record_id, timestamp, details) VALUES (?, ?, ?, ?, ?, ?)",
        (admin_user_id, action, target_user_id, record_id, timestamp, details)
    )
    conn.commit()
    conn.close()


# Wrappers para acciones realizadas por admin (registran auditoría)
def admin_update_glucometry(admin_user_id, record_id, value, record_date, record_time, target_user_id=None):
    # Aplicar cambio
    update_glucometry(record_id, value, record_date, record_time)
    # Registrar en auditoría
    details = f"Actualizar registro {record_id}: value={value}, date={record_date}, time={record_time}"
    log_admin_action(admin_user_id, 'update_record', target_user_id, record_id, details)


def admin_delete_glucometry(admin_user_id, record_id, target_user_id=None):
    # Borrar registro
    delete_glucometry(record_id)
    # Registrar en auditoría
    details = f"Eliminar registro {record_id}"
    log_admin_action(admin_user_id, 'delete_record', target_user_id, record_id, details)


# Helper: aplicar cambios entre dataframe original y editado (index = id)
def sync_history_changes(original_df, edited_df, actor_id=None, id_to_user=None):
    """Sincroniza las diferencias entre original_df y edited_df.
    Ambos dataframes deben tener el mismo index con el id del registro.
    - Borra registros presentes en original y no en edited.
    - Actualiza registros con cambios en Fecha, Hora o Glucosa.
    Si actor_id es provisto, las acciones se registran en la tabla admin_audit.
    id_to_user: mapping {record_id: user_id} usado para el log cuando actor_id está presente.
    """
    # Asegurar índices como enteros
    orig_ids = set(map(int, original_df.index.astype(int)))
    edit_ids = set(map(int, edited_df.index.astype(int)))

    # Eliminaciones
    to_delete = orig_ids - edit_ids
    for rid in to_delete:
        if actor_id:
            target_user = id_to_user.get(rid) if id_to_user else None
            admin_delete_glucometry(actor_id, rid, target_user)
        else:
            delete_glucometry(rid)

    # Actualizaciones
    intersect = orig_ids & edit_ids
    for rid in intersect:
        orig_row = original_df.loc[rid]
        edit_row = edited_df.loc[rid]

        # Normalizar valores
        orig_date = str(orig_row['Fecha'])
        edit_date = str(edit_row['Fecha'])

        orig_time = str(orig_row['Hora'])
        edit_time = str(edit_row['Hora'])

        try:
            orig_val = float(orig_row['Glucosa'])
        except Exception:
            orig_val = None
        try:
            edit_val = float(edit_row['Glucosa'])
        except Exception:
            edit_val = None

        if orig_date != edit_date or orig_time != edit_time or orig_val != edit_val:
            # Convertir formatos si vienen como date/time objects
            if isinstance(edit_date, (datetime.date, datetime.datetime)):
                edit_date = edit_date.strftime('%Y-%m-%d')
            if isinstance(edit_time, (datetime.time, datetime.datetime)):
                edit_time = edit_time.strftime('%H:%M')

            if actor_id:
                target_user = id_to_user.get(rid) if id_to_user else None
                admin_update_glucometry(actor_id, rid, edit_val, edit_date, edit_time, target_user)
            else:
                update_glucometry(rid, edit_val, edit_date, edit_time)

def admin_dashboard(user_id):
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
                row = c.fetchone()
                conn.close()
                stored_hashed_pw = row[0] if row else None
                
                if not stored_hashed_pw or hash_password(current_password) != stored_hashed_pw:
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
    
    st.divider()

    # --- NUEVA SECCIÓN: GESTIÓN CRUD DE REGISTROS (ADMIN) ---
    with st.expander("🛠️ Gestionar Registros de Glucometría (Admin)"):
        # Opcionalmente filtrar por usuario
        users_list = pd.read_sql_query("SELECT id, username FROM users WHERE role='user' ORDER BY username", conn)
        user_options = ['Todos'] + users_list['username'].tolist()
        sel_user = st.selectbox("Filtrar por paciente", user_options, index=0, key="admin_filter_user")

        if sel_user == 'Todos':
            records_df = pd.read_sql_query(
                "SELECT g.id, g.user_id, u.username, g.record_date AS Fecha, g.record_time AS Hora, g.value AS Glucosa FROM glucometries g JOIN users u ON g.user_id = u.id ORDER BY g.record_date DESC, g.record_time DESC",
                conn
            )
        else:
            # obtener user id
            uid = int(users_list[users_list['username'] == sel_user]['id'].iloc[0]) if not users_list.empty else None
            records_df = pd.read_sql_query(
                "SELECT g.id, g.user_id, u.username, g.record_date AS Fecha, g.record_time AS Hora, g.value AS Glucosa FROM glucometries g JOIN users u ON g.user_id = u.id WHERE g.user_id=? ORDER BY g.record_date DESC, g.record_time DESC",
                conn, params=(uid,)
            )

        if records_df.empty:
            st.info("No hay registros para mostrar.")
        else:
            # Preparar mapping id -> user_id para auditoría
            id_to_user = records_df.set_index('id')['user_id'].to_dict()

            # Mostrar usuario en una tabla de solo lectura y permitir edición de Fecha/Hora/Glucosa
            editor_df = records_df.set_index('id')[['Fecha', 'Hora', 'Glucosa']]

            st.markdown("**Registros mostrados (solo lectura: usuario)**")
            st.dataframe(records_df[['username','Fecha','Hora','Glucosa']], use_container_width=True)

            # Intentar editor en línea
            try:
                edited = st.experimental_data_editor(editor_df, num_rows="dynamic", use_container_width=True, key=f"editor_admin_{user_id}")
                if st.button("Aplicar cambios (admin)", key=f"apply_admin_{user_id}"):
                    sync_history_changes(editor_df, edited, actor_id=user_id, id_to_user=id_to_user)
                    st.success("Cambios aplicados.")
                    st.experimental_rerun()
            except Exception:
                # Fallback: seleccionar registro y editar
                recs = records_df.to_dict('records')
                options = [f"{r['username']} | {r['Fecha']} {r['Hora']} — {r['Glucosa']} mg/dL (id:{r['id']})" for r in recs]
                sel_index = st.selectbox("Selecciona registro para editar/eliminar", list(range(len(recs))), format_func=lambda i: options[i], key="admin_sel_record")
                sel_rec = recs[sel_index]

                with st.form("admin_edit_form", clear_on_submit=False):
                    st.markdown(f"**Paciente:** {sel_rec['username']}")
                    edited_value = st.number_input("Nivel de Glucosa (mg/dL)", min_value=20.0, max_value=600.0, step=1.0, value=float(sel_rec['Glucosa']))
                    try:
                        edited_date_val = datetime.date.fromisoformat(sel_rec['Fecha'])
                    except Exception:
                        edited_date_val = datetime.date.today()
                    edited_date = st.date_input("Fecha", value=edited_date_val)

                    try:
                        t_parsed = datetime.datetime.strptime(sel_rec['Hora'], "%H:%M").time()
                    except Exception:
                        t_parsed = datetime.datetime.now().time()
                    edited_time = st.time_input("Hora", value=t_parsed)

                    cols = st.columns([1,1])
                    with cols[0]:
                        save = st.form_submit_button("Guardar cambios")
                    with cols[1]:
                        delete = st.form_submit_button("Eliminar registro")

                    if save:
                        # Usar wrapper admin para auditoría
                        admin_update_glucometry(user_id, sel_rec['id'], float(edited_value), edited_date.strftime("%Y-%m-%d"), edited_time.strftime("%H:%M"), target_user_id=sel_rec.get('user_id'))
                        st.success("Registro actualizado.")
                        st.experimental_rerun()

                    if delete:
                        with st.expander("Confirmar eliminación"):
                            confirm = st.button("Confirmar eliminación")
                            if confirm:
                                admin_delete_glucometry(user_id, sel_rec['id'], target_user_id=sel_rec.get('user_id'))
                                st.success("Registro eliminado.")
                                st.experimental_rerun()

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
            st.experimental_rerun()
            
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

    # Mostrar tabla con el historial personal y CRUD
    with st.expander("Ver todo mi historial"):
        history_df = pd.read_sql_query(
            "SELECT id, record_date AS Fecha, record_time AS Hora, value AS Glucosa FROM glucometries WHERE user_id=? ORDER BY record_date DESC, record_time DESC", 
            conn, params=(user_id,)
        )

        if history_df.empty:
            st.info("No tienes registros aún.")
        else:
            # Preparar dataframe con id como index para editor
            editor_df = history_df.set_index('id')[['Fecha', 'Hora', 'Glucosa']]

            # Intentar usar el data editor si está disponible
            try:
                edited = st.experimental_data_editor(editor_df, num_rows="dynamic", use_container_width=True, key=f"editor_user_{user_id}")
                if st.button("Aplicar cambios", key=f"apply_user_{user_id}"):
                    # Sincronizar cambios
                    sync_history_changes(editor_df, edited)
                    st.success("Cambios aplicados.")
                    st.experimental_rerun()
            except Exception:
                # Fallback al UI clásico si data editor no está disponible
                display_df = history_df.copy()
                display_df['Glucosa (mg/dL)'] = display_df['Glucosa']
                st.dataframe(display_df[['Fecha', 'Hora', 'Glucosa (mg/dL)']], use_container_width=True)

                # Preparar selección de registro a editar/eliminar
                records = history_df.to_dict('records')
                options = [f"{r['Fecha']} {r['Hora']} — {r['Glucosa']} mg/dL (id:{r['id']})" for r in records]
                sel_index = st.selectbox("Selecciona registro para editar/eliminar", list(range(len(records))), format_func=lambda i: options[i], key=f"sel_record_{user_id}")
                sel_rec = records[sel_index]

                with st.form("edit_record_form", clear_on_submit=False):
                    edited_value = st.number_input("Nivel de Glucosa (mg/dL)", min_value=20.0, max_value=600.0, step=1.0, value=float(sel_rec['Glucosa']))
                    # Fecha: convertir desde ISO
                    try:
                        edited_date_val = datetime.date.fromisoformat(sel_rec['Fecha'])
                    except Exception:
                        edited_date_val = today
                    edited_date = st.date_input("Fecha", value=edited_date_val)

                    # Hora: parsear formato HH:MM
                    try:
                        t_parsed = datetime.datetime.strptime(sel_rec['Hora'], "%H:%M").time()
                    except Exception:
                        t_parsed = datetime.datetime.now().time()
                    edited_time = st.time_input("Hora", value=t_parsed)

                    cols = st.columns([1,1])
                    with cols[0]:
                        save = st.form_submit_button("Guardar cambios")
                    with cols[1]:
                        delete = st.form_submit_button("Eliminar registro")

                    if save:
                        update_glucometry(sel_rec['id'], float(edited_value), edited_date.strftime("%Y-%m-%d"), edited_time.strftime("%H:%M"))
                        st.success("Registro actualizado.")
                        st.experimental_rerun()

                    if delete:
                        # Usar modal si está disponible
                        try:
                            with st.expander("Confirmar eliminación"):
                                confirm = st.button("Confirmar eliminación")
                                if confirm:
                                    delete_glucometry(sel_rec['id'])
                                    st.success("Registro eliminado.")
                                    st.experimental_rerun()
                        except Exception:
                            confirm = st.checkbox("Confirmar eliminación", key=f"confirm_del_{sel_rec['id']}")
                            if confirm:
                                delete_glucometry(sel_rec['id'])
                                st.success("Registro eliminado.")
                                st.experimental_rerun()

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
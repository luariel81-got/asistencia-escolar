"""
Sistema de Gestión de Asistencia Escolar - MEC Paraguay
Tercer Ciclo (7°-9°) y Nivel Medio (BTS, BTC, BTI - 1°-3° año)
Base de datos persistente: PostgreSQL (Supabase)
"""

import streamlit as st
import psycopg2
import psycopg2.extras
import pandas as pd
import plotly.express as px
from datetime import date, timedelta
import random

# ─────────────────────────────────────────────
# CONFIGURACIÓN GENERAL
# ─────────────────────────────────────────────
UMBRAL_FALTAS_CONSECUTIVAS = 2

GRADOS = {
    "Tercer Ciclo": ["7° Grado", "8° Grado", "9° Grado"],
    "Nivel Medio - BTS": ["1° BTS", "2° BTS", "3° BTS"],
    "Nivel Medio - BTC": ["1° BTC", "2° BTC", "3° BTC"],
    "Nivel Medio - BTI": ["1° BTI", "2° BTI", "3° BTI"],
}

TODOS_LOS_GRADOS = [g for nivel in GRADOS.values() for g in nivel]
ESTADOS = ["Presente", "Ausente Injustificado", "Ausente Justificado"]

# ─────────────────────────────────────────────
# CONEXIÓN A BASE DE DATOS
# ─────────────────────────────────────────────

@st.cache_resource
def get_conn():
    """Conexión persistente a Supabase PostgreSQL usando st.secrets."""
    return psycopg2.connect(
        host=st.secrets["db_host"],
        port=st.secrets["db_port"],
        dbname=st.secrets["db_name"],
        user=st.secrets["db_user"],
        password=st.secrets["db_password"],
        sslmode="require",
        connect_timeout=10,
    )


def run_query(sql: str, params=None, fetch=True):
    """Ejecuta una consulta. Si fetch=True devuelve resultados."""
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        if fetch:
            return cur.fetchall()
        conn.commit()
        return None


def run_df(sql: str, params=None) -> pd.DataFrame:
    """Ejecuta una consulta y devuelve un DataFrame."""
    rows = run_query(sql, params, fetch=True)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ─────────────────────────────────────────────
# INICIALIZACIÓN DE BASE DE DATOS
# ─────────────────────────────────────────────

def init_db():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS grados (
                id SERIAL PRIMARY KEY,
                nombre TEXT UNIQUE NOT NULL,
                nivel TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS estudiantes (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                grado_id INTEGER NOT NULL REFERENCES grados(id),
                contacto TEXT
            );

            CREATE TABLE IF NOT EXISTS asistencia (
                id SERIAL PRIMARY KEY,
                estudiante_id INTEGER NOT NULL REFERENCES estudiantes(id),
                fecha DATE NOT NULL,
                estado TEXT NOT NULL CHECK(estado IN (
                    'Presente','Ausente Injustificado','Ausente Justificado'
                )),
                UNIQUE(estudiante_id, fecha)
            );
        """)
        for nivel, lista in GRADOS.items():
            for grado in lista:
                cur.execute(
                    "INSERT INTO grados (nombre, nivel) VALUES (%s, %s) ON CONFLICT (nombre) DO NOTHING",
                    (grado, nivel),
                )
        conn.commit()


def seed_mock_data():
    """Genera datos de prueba si no hay estudiantes."""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM estudiantes")
        if cur.fetchone()[0] > 0:
            return

        mock_students = {
            "7° Grado": [
                ("Ana Martínez", "0981-111-001"), ("Luis Pérez", "0981-111-002"),
                ("Sofía Rojas", "0981-111-003"), ("Carlos López", "0981-111-004"),
                ("Valentina García", "0981-111-005"),
            ],
            "8° Grado": [
                ("Miguel Torres", "0982-222-001"), ("Lucía Ramírez", "0982-222-002"),
                ("Diego Flores", "0982-222-003"), ("Isabella Morales", "0982-222-004"),
            ],
            "1° BTS": [
                ("Fernando Ríos", "0983-333-001"), ("Camila Díaz", "0983-333-002"),
                ("Rodrigo Sánchez", "0983-333-003"),
            ],
            "1° BTC": [
                ("Patricia Gómez", "0984-444-001"), ("Andrés Vargas", "0984-444-002"),
                ("Natalia Castro", "0984-444-003"),
            ],
        }

        today = date.today()
        for grado_nombre, alumnos in mock_students.items():
            cur.execute("SELECT id FROM grados WHERE nombre = %s", (grado_nombre,))
            row = cur.fetchone()
            if not row:
                continue
            grado_id = row[0]
            for nombre, contacto in alumnos:
                cur.execute(
                    "INSERT INTO estudiantes (nombre, grado_id, contacto) VALUES (%s, %s, %s) RETURNING id",
                    (nombre, grado_id, contacto),
                )
                est_id = cur.fetchone()[0]
                dias_sim, dia_actual = 0, today
                while dias_sim < 5:
                    if dia_actual.weekday() < 5:
                        estado = random.choices(ESTADOS, weights=[0.80, 0.12, 0.08], k=1)[0]
                        cur.execute(
                            "INSERT INTO asistencia (estudiante_id, fecha, estado) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            (est_id, dia_actual, estado),
                        )
                        dias_sim += 1
                    dia_actual -= timedelta(days=1)
        conn.commit()


# ─────────────────────────────────────────────
# FUNCIONES DE CONSULTA
# ─────────────────────────────────────────────

def get_estudiantes_por_grado(grado_nombre: str) -> pd.DataFrame:
    return run_df("""
        SELECT e.id, e.nombre, e.contacto
        FROM estudiantes e JOIN grados g ON e.grado_id = g.id
        WHERE g.nombre = %s ORDER BY e.nombre
    """, (grado_nombre,))


def get_asistencia_fecha(grado_nombre: str, fecha) -> pd.DataFrame:
    return run_df("""
        SELECT e.id as estudiante_id, e.nombre, e.contacto,
               COALESCE(a.estado, 'Sin registro') as estado
        FROM estudiantes e JOIN grados g ON e.grado_id = g.id
        LEFT JOIN asistencia a ON a.estudiante_id = e.id AND a.fecha = %s
        WHERE g.nombre = %s ORDER BY e.nombre
    """, (fecha, grado_nombre))


def guardar_asistencia(registros: list):
    conn = get_conn()
    with conn.cursor() as cur:
        for est_id, fecha, estado in registros:
            cur.execute("""
                INSERT INTO asistencia (estudiante_id, fecha, estado) VALUES (%s, %s, %s)
                ON CONFLICT (estudiante_id, fecha) DO UPDATE SET estado = EXCLUDED.estado
            """, (est_id, fecha, estado))
        conn.commit()


def get_resumen_grado(grado_nombre: str) -> pd.DataFrame:
    return run_df("""
        SELECT e.nombre,
               COUNT(CASE WHEN a.estado = 'Presente' THEN 1 END) as presentes,
               COUNT(CASE WHEN a.estado = 'Ausente Injustificado' THEN 1 END) as inj,
               COUNT(CASE WHEN a.estado = 'Ausente Justificado' THEN 1 END) as just,
               COUNT(a.id) as total_dias
        FROM estudiantes e JOIN grados g ON e.grado_id = g.id
        LEFT JOIN asistencia a ON a.estudiante_id = e.id
        WHERE g.nombre = %s
        GROUP BY e.id, e.nombre ORDER BY e.nombre
    """, (grado_nombre,))


def detectar_faltas_consecutivas(grado_nombre: str = None) -> pd.DataFrame:
    filtro = "AND g.nombre = %s" if grado_nombre else ""
    params = (grado_nombre,) if grado_nombre else ()
    df = run_df(f"""
        SELECT e.id as estudiante_id, e.nombre, e.contacto, g.nombre as grado,
               a.fecha, a.estado
        FROM asistencia a
        JOIN estudiantes e ON a.estudiante_id = e.id
        JOIN grados g ON e.grado_id = g.id
        WHERE a.estado LIKE 'Ausente%%' {filtro}
        ORDER BY e.id, a.fecha DESC
    """, params)

    if df.empty:
        return pd.DataFrame(columns=["nombre", "grado", "contacto", "faltas_consecutivas", "desde"])

    resultados = []
    for est_id, grupo in df.groupby("estudiante_id"):
        fechas = sorted(pd.to_datetime(grupo["fecha"]).tolist(), reverse=True)
        racha = 1
        for i in range(1, len(fechas)):
            diff = (fechas[i - 1] - fechas[i]).days
            if 1 <= diff <= 3:
                racha += 1
            else:
                break
        if racha >= UMBRAL_FALTAS_CONSECUTIVAS:
            resultados.append({
                "nombre": grupo["nombre"].iloc[0],
                "grado": grupo["grado"].iloc[0],
                "contacto": grupo["contacto"].iloc[0] or "Sin contacto",
                "faltas_consecutivas": racha,
                "desde": fechas[-1].date() if racha > 1 else fechas[0].date(),
            })

    return pd.DataFrame(resultados).sort_values("faltas_consecutivas", ascending=False)


def agregar_estudiante(nombre: str, grado_nombre: str, contacto: str):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM grados WHERE nombre = %s", (grado_nombre,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "INSERT INTO estudiantes (nombre, grado_id, contacto) VALUES (%s, %s, %s)",
                (nombre.strip(), row[0], contacto.strip()),
            )
            conn.commit()


def eliminar_estudiante(est_id: int):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM asistencia WHERE estudiante_id = %s", (est_id,))
        cur.execute("DELETE FROM estudiantes WHERE id = %s", (est_id,))
        conn.commit()


# ─────────────────────────────────────────────
# CSS TABLET
# ─────────────────────────────────────────────

def inject_tablet_css():
    st.markdown("""
    <style>
    html, body, [class*="css"] { font-size: 17px !important; }
    .stButton > button {
        min-height: 52px !important; font-size: 16px !important;
        border-radius: 10px !important; padding: 10px 20px !important;
    }
    .stSelectbox > div > div,
    .stDateInput > div > div > input {
        min-height: 48px !important; font-size: 16px !important; border-radius: 8px !important;
    }
    .stTextInput > div > div > input {
        min-height: 48px !important; font-size: 16px !important; border-radius: 8px !important;
    }
    .stRadio > div { gap: 6px !important; }
    .stRadio label { font-size: 16px !important; padding: 10px 12px !important; border-radius: 8px !important; }
    .stTabs [data-baseweb="tab"] { min-height: 48px !important; font-size: 15px !important; padding: 10px 18px !important; }
    [data-testid="metric-container"] [data-testid="stMetricValue"] { font-size: 26px !important; }
    [data-testid="stSidebar"] { min-width: 240px !important; }
    .main .block-container { padding-top: 1.5rem !important; padding-bottom: 3rem !important; max-width: 1100px; }
    .stDownloadButton > button { min-height: 52px !important; font-size: 16px !important; }
    </style>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# PÁGINAS
# ─────────────────────────────────────────────

def pagina_pasar_lista():
    st.header("📋 Pasar Lista")
    col1, col2 = st.columns([2, 1])
    with col1:
        grado_sel = st.selectbox("Seleccionar Grado", TODOS_LOS_GRADOS, key="lista_grado")
    with col2:
        fecha_sel = st.date_input("Fecha", value=date.today(), key="lista_fecha")

    estudiantes_df = get_asistencia_fecha(grado_sel, fecha_sel)

    if estudiantes_df.empty:
        st.warning(f"⚠️ No hay estudiantes en **{grado_sel}**. Agregá estudiantes en 'Gestión de Estudiantes'.")
        return

    st.markdown(f"**{len(estudiantes_df)} estudiantes** — {grado_sel} — {fecha_sel.strftime('%d/%m/%Y')}")

    COLOR_MAP = {
        "Presente": "🟢", "Ausente Injustificado": "🔴",
        "Ausente Justificado": "🟡", "Sin registro": "⚪",
    }

    if st.button("✅ Marcar todos Presentes"):
        for key in list(st.session_state.keys()):
            if key.startswith("estado_"):
                st.session_state[key] = "Presente"

    nuevos_registros = []
    for _, row in estudiantes_df.iterrows():
        estado_actual = row["estado"] if row["estado"] in ESTADOS else "Presente"
        with st.container():
            st.markdown(
                f"<div style='font-size:17px;font-weight:600;padding:6px 0 2px 0;'>"
                f"{COLOR_MAP.get(row['estado'], '⚪')} {row['nombre']}</div>",
                unsafe_allow_html=True,
            )
            nuevo_estado = st.selectbox(
                "Estado", ESTADOS,
                index=ESTADOS.index(estado_actual) if estado_actual in ESTADOS else 0,
                key=f"estado_{row['estudiante_id']}",
                label_visibility="collapsed",
            )
            st.markdown("<hr style='margin:6px 0;opacity:0.15'>", unsafe_allow_html=True)
        nuevos_registros.append((row["estudiante_id"], fecha_sel, nuevo_estado))

    if st.button("💾 Guardar Asistencia", type="primary", use_container_width=True):
        guardar_asistencia(nuevos_registros)
        st.success(f"✅ Asistencia guardada — {grado_sel} — {fecha_sel.strftime('%d/%m/%Y')}")
        st.balloons()


def pagina_resumen():
    st.header("📊 Resumen por Grado")
    grado_sel = st.selectbox("Seleccionar Grado", TODOS_LOS_GRADOS, key="resumen_grado")
    df = get_resumen_grado(grado_sel)

    if df.empty or df["total_dias"].sum() == 0:
        st.info(f"📭 Aún no hay registros para **{grado_sel}**.")
        return

    total_registros = df["total_dias"].sum()
    total_presentes = df["presentes"].sum()
    total_inj = df["inj"].sum()
    total_just = df["just"].sum()
    pct_asistencia = round((total_presentes / total_registros) * 100, 1) if total_registros else 0

    col1, col2 = st.columns(2)
    col1.metric("👥 Estudiantes", len(df))
    col2.metric("✅ % Asistencia General", f"{pct_asistencia}%")
    col3, col4 = st.columns(2)
    col3.metric("🔴 Faltas Injustificadas", total_inj)
    col4.metric("🟡 Faltas Justificadas", total_just)

    st.divider()
    col_pie, col_bar = st.columns(2)

    with col_pie:
        st.subheader("Distribución General")
        fig_pie = px.pie(
            names=["Presentes", "Ausente Injustificado", "Ausente Justificado"],
            values=[total_presentes, total_inj, total_just],
            color_discrete_sequence=["#2ecc71", "#e74c3c", "#f39c12"],
            hole=0.4,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        fig_pie.update_layout(showlegend=False, margin=dict(t=10, b=10))
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_bar:
        st.subheader("Asistencia por Estudiante")
        df_plot = df.copy()
        df_plot["% Asistencia"] = (df_plot["presentes"] / df_plot["total_dias"] * 100).round(1)
        fig_bar = px.bar(
            df_plot, x="nombre", y="% Asistencia",
            color="% Asistencia",
            color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
            range_color=[0, 100],
        )
        fig_bar.update_layout(xaxis_tickangle=-35, coloraxis_showscale=False, margin=dict(t=10, b=80))
        fig_bar.add_hline(y=75, line_dash="dash", line_color="red", annotation_text="Mínimo 75%")
        st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader("📋 Detalle por Estudiante")
    df_tabla = df.rename(columns={
        "nombre": "Nombre", "presentes": "Presentes",
        "inj": "F. Injustificadas", "just": "F. Justificadas", "total_dias": "Días Registrados",
    })
    df_tabla["% Asistencia"] = (df_tabla["Presentes"] / df_tabla["Días Registrados"] * 100).round(1).astype(str) + "%"
    st.dataframe(df_tabla, use_container_width=True, hide_index=True)


def pagina_alertas():
    st.header("🚨 Alertas de Faltas Consecutivas")
    st.caption(f"Estudiantes con **{UMBRAL_FALTAS_CONSECUTIVAS} o más faltas consecutivas**.")

    filtro_grado = st.selectbox("Filtrar por Grado", ["Todos los grados"] + TODOS_LOS_GRADOS, key="alerta_grado")
    alertas_df = detectar_faltas_consecutivas(None if filtro_grado == "Todos los grados" else filtro_grado)

    if alertas_df.empty:
        st.success("✅ ¡Sin alertas! Ningún estudiante tiene faltas consecutivas.")
        return

    st.error(f"⚠️ **{len(alertas_df)} estudiante(s)** requieren atención:")
    st.divider()

    for _, row in alertas_df.iterrows():
        col_info, col_contacto = st.columns([3, 2])
        with col_info:
            st.markdown(f"### 👤 {row['nombre']}")
            st.markdown(f"📚 **Grado:** {row['grado']}")
            st.markdown(f"📅 **Faltas consecutivas:** `{row['faltas_consecutivas']} días`")
            st.markdown(f"🗓️ **Desde:** {row['desde']}")
        with col_contacto:
            st.markdown("### 📞 Contacto")
            st.info(f"**{row['contacto']}**")
        st.divider()

    csv = alertas_df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Descargar CSV", data=csv,
                       file_name=f"alertas_{date.today().isoformat()}.csv", mime="text/csv")


def pagina_gestion():
    st.header("🎓 Gestión de Estudiantes")
    tab_agregar, tab_ver = st.tabs(["➕ Agregar Estudiante", "📋 Ver / Eliminar"])

    with tab_agregar:
        with st.form("form_agregar"):
            nombre = st.text_input("Nombre completo del estudiante")
            grado_sel = st.selectbox("Grado", TODOS_LOS_GRADOS)
            contacto = st.text_input("Número de contacto (padre/tutor)")
            if st.form_submit_button("Agregar Estudiante", type="primary"):
                if nombre.strip():
                    agregar_estudiante(nombre, grado_sel, contacto)
                    st.success(f"✅ **{nombre}** agregado a {grado_sel}.")
                else:
                    st.error("⚠️ El nombre no puede estar vacío.")

    with tab_ver:
        grado_ver = st.selectbox("Seleccionar Grado", TODOS_LOS_GRADOS, key="ver_grado")
        df = get_estudiantes_por_grado(grado_ver)
        if df.empty:
            st.info(f"No hay estudiantes en {grado_ver}.")
        else:
            for _, row in df.iterrows():
                col_nom, col_tel, col_del = st.columns([3, 2, 1])
                col_nom.write(f"👤 {row['nombre']}")
                col_tel.write(f"📞 {row['contacto'] or '—'}")
                if col_del.button("🗑️", key=f"del_{row['id']}", help="Eliminar"):
                    eliminar_estudiante(row["id"])
                    st.rerun()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Asistencia Escolar — MEC Paraguay",
        page_icon="🏫",
        layout="wide",
    )

    try:
        init_db()
        seed_mock_data()
    except Exception as e:
        st.error(f"❌ No se pudo conectar a la base de datos. Verificá las credenciales en Secrets.\n\n`{e}`")
        st.stop()

    inject_tablet_css()

    with st.sidebar:
        st.image("https://upload.wikimedia.org/wikipedia/commons/2/27/Flag_of_Paraguay.svg", width=80)
        st.title("🏫 Asistencia Escolar")
        st.caption("MEC Paraguay · Tercer Ciclo & Nivel Medio")
        st.divider()

        pagina = st.radio(
            "Navegación",
            ["📋 Pasar Lista", "📊 Resumen por Grado", "🚨 Alertas de Faltas", "🎓 Gestión de Estudiantes"],
            label_visibility="collapsed",
        )

        st.divider()
        st.caption(f"📅 Hoy: {date.today().strftime('%d/%m/%Y')}")
        n_est = run_df("SELECT COUNT(*) as c FROM estudiantes")["c"][0]
        n_reg = run_df("SELECT COUNT(*) as c FROM asistencia")["c"][0]
        st.metric("Total Estudiantes", n_est)
        st.metric("Registros de Asistencia", n_reg)

    if pagina == "📋 Pasar Lista":
        pagina_pasar_lista()
    elif pagina == "📊 Resumen por Grado":
        pagina_resumen()
    elif pagina == "🚨 Alertas de Faltas":
        pagina_alertas()
    elif pagina == "🎓 Gestión de Estudiantes":
        pagina_gestion()


if __name__ == "__main__":
    main()

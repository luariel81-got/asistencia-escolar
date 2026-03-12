"""
Sistema de Gestión de Asistencia Escolar - MEC Paraguay
Tercer Ciclo (7°-9°) y Nivel Medio (BTS, BTC, BTI - 1°-3° año)
"""

import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
import os

# ─────────────────────────────────────────────
# CONFIGURACIÓN GENERAL
# ─────────────────────────────────────────────
DB_PATH = "asistencia_escolar.db"
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
# BASE DE DATOS
# ─────────────────────────────────────────────

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS grados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            nivel TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS estudiantes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            grado_id INTEGER NOT NULL,
            contacto TEXT,
            FOREIGN KEY (grado_id) REFERENCES grados(id)
        );

        CREATE TABLE IF NOT EXISTS asistencia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            estudiante_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            estado TEXT NOT NULL CHECK(estado IN ('Presente','Ausente Injustificado','Ausente Justificado')),
            UNIQUE(estudiante_id, fecha),
            FOREIGN KEY (estudiante_id) REFERENCES estudiantes(id)
        );
    """)
    conn.commit()

    # Poblar grados si están vacíos
    for nivel, lista in GRADOS.items():
        for grado in lista:
            c.execute("INSERT OR IGNORE INTO grados (nombre, nivel) VALUES (?, ?)", (grado, nivel))
    conn.commit()
    conn.close()


def seed_mock_data():
    """Genera datos de prueba si no hay estudiantes cargados."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM estudiantes")
    if c.fetchone()[0] > 0:
        conn.close()
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
        c.execute("SELECT id FROM grados WHERE nombre = ?", (grado_nombre,))
        row = c.fetchone()
        if not row:
            continue
        grado_id = row[0]
        for nombre, contacto in alumnos:
            c.execute(
                "INSERT INTO estudiantes (nombre, grado_id, contacto) VALUES (?, ?, ?)",
                (nombre, grado_id, contacto),
            )
            est_id = c.lastrowid
            # Simular asistencia de los últimos 5 días hábiles
            dias_sim = 0
            dia_actual = today
            while dias_sim < 5:
                if dia_actual.weekday() < 5:
                    import random
                    estado = random.choices(
                        ESTADOS, weights=[0.80, 0.12, 0.08], k=1
                    )[0]
                    c.execute(
                        "INSERT OR IGNORE INTO asistencia (estudiante_id, fecha, estado) VALUES (?, ?, ?)",
                        (est_id, dia_actual.isoformat(), estado),
                    )
                    dias_sim += 1
                dia_actual -= timedelta(days=1)

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# FUNCIONES DE CONSULTA
# ─────────────────────────────────────────────

def get_grados_df():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM grados ORDER BY nivel, nombre", conn)
    conn.close()
    return df


def get_estudiantes_por_grado(grado_nombre: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql(
        """
        SELECT e.id, e.nombre, e.contacto
        FROM estudiantes e
        JOIN grados g ON e.grado_id = g.id
        WHERE g.nombre = ?
        ORDER BY e.nombre
        """,
        conn, params=(grado_nombre,),
    )
    conn.close()
    return df


def get_asistencia_fecha(grado_nombre: str, fecha: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql(
        """
        SELECT e.id as estudiante_id, e.nombre, e.contacto,
               COALESCE(a.estado, 'Sin registro') as estado
        FROM estudiantes e
        JOIN grados g ON e.grado_id = g.id
        LEFT JOIN asistencia a ON a.estudiante_id = e.id AND a.fecha = ?
        WHERE g.nombre = ?
        ORDER BY e.nombre
        """,
        conn, params=(fecha, grado_nombre),
    )
    conn.close()
    return df


def guardar_asistencia(registros: list):
    """registros: lista de (estudiante_id, fecha, estado)"""
    conn = get_conn()
    c = conn.cursor()
    for est_id, fecha, estado in registros:
        c.execute(
            """INSERT INTO asistencia (estudiante_id, fecha, estado) VALUES (?, ?, ?)
               ON CONFLICT(estudiante_id, fecha) DO UPDATE SET estado=excluded.estado""",
            (est_id, fecha, estado),
        )
    conn.commit()
    conn.close()


def get_resumen_grado(grado_nombre: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql(
        """
        SELECT e.nombre,
               COUNT(CASE WHEN a.estado = 'Presente' THEN 1 END) as presentes,
               COUNT(CASE WHEN a.estado = 'Ausente Injustificado' THEN 1 END) as inj,
               COUNT(CASE WHEN a.estado = 'Ausente Justificado' THEN 1 END) as just,
               COUNT(a.id) as total_dias
        FROM estudiantes e
        JOIN grados g ON e.grado_id = g.id
        LEFT JOIN asistencia a ON a.estudiante_id = e.id
        WHERE g.nombre = ?
        GROUP BY e.id, e.nombre
        ORDER BY e.nombre
        """,
        conn, params=(grado_nombre,),
    )
    conn.close()
    return df


def detectar_faltas_consecutivas(grado_nombre: str = None) -> pd.DataFrame:
    """
    Algoritmo de detección de racha de faltas consecutivas:
    1. Para cada estudiante, obtiene sus registros ordenados por fecha DESC.
    2. Cuenta cuántos días seguidos (desde el más reciente hacia atrás) el estado
       contiene 'Ausente' (injustificado o justificado).
    3. Si la racha >= UMBRAL, el estudiante aparece en la alerta.
    """
    conn = get_conn()
    filtro_grado = "AND g.nombre = :grado" if grado_nombre else ""
    df = pd.read_sql(
        f"""
        SELECT e.id as estudiante_id, e.nombre, e.contacto, g.nombre as grado,
               a.fecha, a.estado
        FROM asistencia a
        JOIN estudiantes e ON a.estudiante_id = e.id
        JOIN grados g ON e.grado_id = g.id
        WHERE a.estado LIKE 'Ausente%'
        {filtro_grado}
        ORDER BY e.id, a.fecha DESC
        """,
        conn,
        params={"grado": grado_nombre} if grado_nombre else {},
    )
    conn.close()

    if df.empty:
        return pd.DataFrame(columns=["nombre", "grado", "contacto", "faltas_consecutivas", "desde"])

    resultados = []
    for est_id, grupo in df.groupby("estudiante_id"):
        fechas = pd.to_datetime(grupo["fecha"].tolist())
        fechas_sorted = sorted(fechas, reverse=True)

        racha = 1
        for i in range(1, len(fechas_sorted)):
            diff = (fechas_sorted[i - 1] - fechas_sorted[i]).days
            # Permitir saltar fines de semana (diff 1, 2 o 3 días)
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
                "desde": fechas_sorted[-1].date() if racha > 1 else fechas_sorted[0].date(),
            })

    return pd.DataFrame(resultados).sort_values("faltas_consecutivas", ascending=False)


def agregar_estudiante(nombre: str, grado_nombre: str, contacto: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM grados WHERE nombre = ?", (grado_nombre,))
    row = c.fetchone()
    if row:
        c.execute(
            "INSERT INTO estudiantes (nombre, grado_id, contacto) VALUES (?, ?, ?)",
            (nombre.strip(), row[0], contacto.strip()),
        )
        conn.commit()
    conn.close()


def eliminar_estudiante(est_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM asistencia WHERE estudiante_id = ?", (est_id,))
    c.execute("DELETE FROM estudiantes WHERE id = ?", (est_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# PÁGINAS STREAMLIT
# ─────────────────────────────────────────────

def pagina_pasar_lista():
    st.header("📋 Pasar Lista")

    col1, col2 = st.columns([2, 1])
    with col1:
        grado_sel = st.selectbox("Seleccionar Grado", TODOS_LOS_GRADOS, key="lista_grado")
    with col2:
        fecha_sel = st.date_input("Fecha", value=date.today(), key="lista_fecha")

    estudiantes_df = get_asistencia_fecha(grado_sel, fecha_sel.isoformat())

    if estudiantes_df.empty:
        st.warning(f"⚠️ No hay estudiantes registrados en **{grado_sel}**. Agregue estudiantes en la sección 'Gestión de Estudiantes'.")
        return

    st.markdown(f"**{len(estudiantes_df)} estudiantes** — {grado_sel} — {fecha_sel.strftime('%d/%m/%Y')}")
    st.divider()

    COLOR_MAP = {
        "Presente": "🟢",
        "Ausente Injustificado": "🔴",
        "Ausente Justificado": "🟡",
        "Sin registro": "⚪",
    }

    # Botón rápido: marcar todos presentes
    if st.button("✅ Marcar todos Presentes", use_container_width=False):
        for key in list(st.session_state.keys()):
            if key.startswith("estado_"):
                st.session_state[key] = "Presente"

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    nuevos_registros = []
    for _, row in estudiantes_df.iterrows():
        estado_actual = row["estado"] if row["estado"] in ESTADOS else "Presente"
        with st.container():
            st.markdown(
                f"<div style='font-size:17px; font-weight:600; padding: 6px 0 2px 0;'>"
                f"{COLOR_MAP.get(row['estado'], '⚪')} {row['nombre']}</div>",
                unsafe_allow_html=True,
            )
            nuevo_estado = st.selectbox(
                "Estado",
                ESTADOS,
                index=ESTADOS.index(estado_actual) if estado_actual in ESTADOS else 0,
                key=f"estado_{row['estudiante_id']}",
                label_visibility="collapsed",
            )
            st.markdown("<hr style='margin:6px 0; opacity:0.15'>", unsafe_allow_html=True)
        nuevos_registros.append((row["estudiante_id"], fecha_sel.isoformat(), nuevo_estado))

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    if st.button("💾 Guardar Asistencia", type="primary", use_container_width=True):
        guardar_asistencia(nuevos_registros)
        st.success(f"✅ Asistencia guardada correctamente para {grado_sel} — {fecha_sel.strftime('%d/%m/%Y')}")
        st.balloons()


def pagina_resumen():
    st.header("📊 Resumen por Grado")

    grado_sel = st.selectbox("Seleccionar Grado", TODOS_LOS_GRADOS, key="resumen_grado")
    df = get_resumen_grado(grado_sel)

    if df.empty or df["total_dias"].sum() == 0:
        st.info(f"📭 Aún no hay registros de asistencia para **{grado_sel}**.")
        return

    # Métricas generales
    total_registros = df["total_dias"].sum()
    total_presentes = df["presentes"].sum()
    total_inj = df["inj"].sum()
    total_just = df["just"].sum()
    pct_asistencia = round((total_presentes / total_registros) * 100, 1) if total_registros else 0

    # 2x2 grid — más legible en tablet vertical y en PC
    col1, col2 = st.columns(2)
    col1.metric("👥 Estudiantes", len(df))
    col2.metric("✅ % Asistencia General", f"{pct_asistencia}%")
    col3, col4 = st.columns(2)
    col3.metric("🔴 Faltas Injustificadas", total_inj)
    col4.metric("🟡 Faltas Justificadas", total_just)

    st.divider()
    col_pie, col_bar = st.columns(2)

    # Gráfico de pastel general
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

    # Gráfico de barras por estudiante
    with col_bar:
        st.subheader("Asistencia por Estudiante")
        df_plot = df.copy()
        df_plot["% Asistencia"] = (df_plot["presentes"] / df_plot["total_dias"] * 100).round(1)
        fig_bar = px.bar(
            df_plot, x="nombre", y="% Asistencia",
            color="% Asistencia",
            color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
            range_color=[0, 100],
            labels={"nombre": "Estudiante", "% Asistencia": "% Asistencia"},
        )
        fig_bar.update_layout(
            xaxis_tickangle=-35,
            coloraxis_showscale=False,
            margin=dict(t=10, b=80),
        )
        fig_bar.add_hline(y=75, line_dash="dash", line_color="red",
                          annotation_text="Mínimo 75%")
        st.plotly_chart(fig_bar, use_container_width=True)

    # Tabla detallada
    st.subheader("📋 Detalle por Estudiante")
    df_tabla = df.rename(columns={
        "nombre": "Nombre",
        "presentes": "Presentes",
        "inj": "F. Injustificadas",
        "just": "F. Justificadas",
        "total_dias": "Días Registrados",
    })
    df_tabla["% Asistencia"] = (df_tabla["Presentes"] / df_tabla["Días Registrados"] * 100).round(1).astype(str) + "%"
    st.dataframe(df_tabla, use_container_width=True, hide_index=True)


def pagina_alertas():
    st.header("🚨 Alertas de Faltas Consecutivas")
    st.caption(f"Se muestran estudiantes con **{UMBRAL_FALTAS_CONSECUTIVAS} o más faltas consecutivas**.")

    col1, col2 = st.columns([2, 1])
    with col1:
        filtro_grado = st.selectbox(
            "Filtrar por Grado",
            ["Todos los grados"] + TODOS_LOS_GRADOS,
            key="alerta_grado",
        )
    grado_param = None if filtro_grado == "Todos los grados" else filtro_grado

    alertas_df = detectar_faltas_consecutivas(grado_param)

    if alertas_df.empty:
        st.success("✅ ¡Sin alertas! Ningún estudiante tiene faltas consecutivas en este momento.")
        return

    st.error(f"⚠️ **{len(alertas_df)} estudiante(s)** requieren atención:")
    st.divider()

    for _, row in alertas_df.iterrows():
        with st.container():
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

    # Exportar tabla
    st.subheader("📥 Exportar Alertas")
    csv = alertas_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Descargar CSV",
        data=csv,
        file_name=f"alertas_faltas_{date.today().isoformat()}.csv",
        mime="text/csv",
    )


def pagina_gestion():
    st.header("🎓 Gestión de Estudiantes")

    tab_agregar, tab_ver = st.tabs(["➕ Agregar Estudiante", "📋 Ver / Eliminar"])

    with tab_agregar:
        with st.form("form_agregar"):
            nombre = st.text_input("Nombre completo del estudiante")
            grado_sel = st.selectbox("Grado", TODOS_LOS_GRADOS)
            contacto = st.text_input("Número de contacto (padre/tutor)")
            submitted = st.form_submit_button("Agregar Estudiante", type="primary")
            if submitted:
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
                if col_del.button("🗑️", key=f"del_{row['id']}", help="Eliminar estudiante"):
                    eliminar_estudiante(row["id"])
                    st.rerun()


# ─────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────

def inject_tablet_css():
    st.markdown("""
    <style>
    /* ── Fuente base más grande para tablet ── */
    html, body, [class*="css"] {
        font-size: 17px !important;
    }

    /* ── Botones grandes y táctiles ── */
    .stButton > button {
        min-height: 52px !important;
        font-size: 16px !important;
        border-radius: 10px !important;
        padding: 10px 20px !important;
    }

    /* ── Selectboxes y date input más altos ── */
    .stSelectbox > div > div,
    .stDateInput > div > div > input {
        min-height: 48px !important;
        font-size: 16px !important;
        border-radius: 8px !important;
    }

    /* ── Text inputs más altos ── */
    .stTextInput > div > div > input {
        min-height: 48px !important;
        font-size: 16px !important;
        border-radius: 8px !important;
    }

    /* ── Radio buttons más separados (navegación sidebar) ── */
    .stRadio > div {
        gap: 6px !important;
    }
    .stRadio label {
        font-size: 16px !important;
        padding: 10px 12px !important;
        border-radius: 8px !important;
        cursor: pointer;
    }
    .stRadio label:hover {
        background-color: rgba(255,255,255,0.08);
    }

    /* ── Tabs más grandes ── */
    .stTabs [data-baseweb="tab"] {
        min-height: 48px !important;
        font-size: 15px !important;
        padding: 10px 18px !important;
    }

    /* ── Métricas con texto más grande ── */
    [data-testid="metric-container"] {
        font-size: 15px !important;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 26px !important;
    }

    /* ── Filas de asistencia: más alto para tapping ── */
    .fila-asistencia {
        padding: 8px 0 !important;
        min-height: 56px;
        display: flex;
        align-items: center;
    }

    /* ── Sidebar más ancho en tablet ── */
    [data-testid="stSidebar"] {
        min-width: 240px !important;
    }

    /* ── Scroll suave ── */
    .main .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 3rem !important;
        max-width: 1100px;
    }

    /* ── Download button táctil ── */
    .stDownloadButton > button {
        min-height: 52px !important;
        font-size: 16px !important;
    }
    </style>
    """, unsafe_allow_html=True)


def main():
    st.set_page_config(
        page_title="Asistencia Escolar — MEC Paraguay",
        page_icon="🏫",
        layout="wide",
    )

    init_db()
    seed_mock_data()
    inject_tablet_css()

    # Sidebar
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

        # Mini-stats en sidebar
        conn = get_conn()
        n_est = pd.read_sql("SELECT COUNT(*) as c FROM estudiantes", conn)["c"][0]
        n_reg = pd.read_sql("SELECT COUNT(*) as c FROM asistencia", conn)["c"][0]
        conn.close()
        st.metric("Total Estudiantes", n_est)
        st.metric("Registros de Asistencia", n_reg)

    # Renderizar página
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

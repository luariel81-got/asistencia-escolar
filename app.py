"""
Sistema de Gestión de Asistencia Escolar - MEC Paraguay
Versión 2.0 — Con importación PDF, botones P/A/J, exportación Excel,
edición de estudiantes, logo e identidad institucional.
"""

import streamlit as st
import psycopg2
import psycopg2.extras
import pandas as pd
import plotly.express as px
from datetime import date, timedelta
import random
import io
import base64
import pdfplumber
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

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
# CONEXIÓN BASE DE DATOS
# ─────────────────────────────────────────────

@st.cache_resource
def get_conn():
    return psycopg2.connect(
        host=st.secrets["db_host"],
        port=st.secrets["db_port"],
        dbname=st.secrets["db_name"],
        user=st.secrets["db_user"],
        password=st.secrets["db_password"],
        sslmode="require",
        connect_timeout=10,
    )


def run_query(sql, params=None, fetch=True):
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        if fetch:
            return cur.fetchall()
        conn.commit()
        return None


def run_df(sql, params=None) -> pd.DataFrame:
    rows = run_query(sql, params, fetch=True)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ─────────────────────────────────────────────
# INIT BASE DE DATOS
# ─────────────────────────────────────────────

def init_db():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS config (
                clave TEXT PRIMARY KEY,
                valor TEXT
            );
            CREATE TABLE IF NOT EXISTS grados (
                id SERIAL PRIMARY KEY,
                nombre TEXT UNIQUE NOT NULL,
                nivel TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS estudiantes (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                ci TEXT,
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
        # Agregar columna CI si no existe (migración)
        cur.execute("""
            ALTER TABLE estudiantes ADD COLUMN IF NOT EXISTS ci TEXT;
        """)
        for nivel, lista in GRADOS.items():
            for grado in lista:
                cur.execute(
                    "INSERT INTO grados (nombre, nivel) VALUES (%s, %s) ON CONFLICT (nombre) DO NOTHING",
                    (grado, nivel),
                )
        # Config defaults
        for clave, valor in [
            ("institucion_nombre", "Institución Educativa"),
            ("institucion_logo", ""),
        ]:
            cur.execute(
                "INSERT INTO config (clave, valor) VALUES (%s, %s) ON CONFLICT (clave) DO NOTHING",
                (clave, valor),
            )
        conn.commit()


def seed_mock_data():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM estudiantes")
        if cur.fetchone()[0] > 0:
            return
        mock = {
            "7° Grado": [("Ana Martínez", "1234567"), ("Luis Pérez", "2345678"),
                         ("Sofía Rojas", "3456789"), ("Carlos López", "4567890")],
            "8° Grado": [("Miguel Torres", "5678901"), ("Lucía Ramírez", "6789012"),
                         ("Diego Flores", "7890123")],
            "1° BTS":   [("Fernando Ríos", "8901234"), ("Camila Díaz", "9012345")],
        }
        today = date.today()
        for grado_nombre, alumnos in mock.items():
            cur.execute("SELECT id FROM grados WHERE nombre = %s", (grado_nombre,))
            row = cur.fetchone()
            if not row:
                continue
            grado_id = row[0]
            for nombre, ci in alumnos:
                cur.execute(
                    "INSERT INTO estudiantes (nombre, ci, grado_id) VALUES (%s, %s, %s) RETURNING id",
                    (nombre, ci, grado_id),
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
# CONFIG INSTITUCIONAL
# ─────────────────────────────────────────────

def get_config(clave: str) -> str:
    rows = run_query("SELECT valor FROM config WHERE clave = %s", (clave,))
    return rows[0]["valor"] if rows else ""


def set_config(clave: str, valor: str):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO config (clave, valor) VALUES (%s, %s) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
            (clave, valor),
        )
        conn.commit()


# ─────────────────────────────────────────────
# FUNCIONES DE DATOS
# ─────────────────────────────────────────────

def get_estudiantes_por_grado(grado_nombre: str) -> pd.DataFrame:
    return run_df("""
        SELECT e.id, e.nombre, e.ci, e.contacto
        FROM estudiantes e JOIN grados g ON e.grado_id = g.id
        WHERE g.nombre = %s ORDER BY e.nombre
    """, (grado_nombre,))


def get_asistencia_fecha(grado_nombre: str, fecha) -> pd.DataFrame:
    return run_df("""
        SELECT e.id as estudiante_id, e.nombre,
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


def get_asistencia_rango(grado_nombre: str, fecha_ini, fecha_fin) -> pd.DataFrame:
    return run_df("""
        SELECT e.nombre, e.ci, a.fecha, a.estado, g.nombre as grado
        FROM asistencia a
        JOIN estudiantes e ON a.estudiante_id = e.id
        JOIN grados g ON e.grado_id = g.id
        WHERE g.nombre = %s AND a.fecha BETWEEN %s AND %s
        ORDER BY e.nombre, a.fecha
    """, (grado_nombre, fecha_ini, fecha_fin))


def detectar_faltas_consecutivas(grado_nombre=None) -> pd.DataFrame:
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


def agregar_estudiante(nombre, ci, grado_nombre, contacto):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM grados WHERE nombre = %s", (grado_nombre,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "INSERT INTO estudiantes (nombre, ci, grado_id, contacto) VALUES (%s, %s, %s, %s)",
                (nombre.strip(), ci.strip(), row[0], contacto.strip()),
            )
            conn.commit()


def actualizar_estudiante(est_id, nombre, ci, grado_nombre, contacto):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM grados WHERE nombre = %s", (grado_nombre,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE estudiantes SET nombre=%s, ci=%s, grado_id=%s, contacto=%s WHERE id=%s",
                (nombre.strip(), ci.strip(), row[0], contacto.strip(), est_id),
            )
            conn.commit()


def eliminar_estudiante(est_id):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM asistencia WHERE estudiante_id = %s", (est_id,))
        cur.execute("DELETE FROM estudiantes WHERE id = %s", (est_id,))
        conn.commit()


# ─────────────────────────────────────────────
# IMPORTACIÓN PDF
# ─────────────────────────────────────────────

def extraer_alumnos_pdf(pdf_bytes: bytes) -> pd.DataFrame:
    """
    Extrae alumnos de un PDF con tabla fija.
    Busca columnas que contengan 'nombre' y 'ci' (insensible a mayúsculas).
    """
    filas = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pagina in pdf.pages:
            tablas = pagina.extract_tables()
            for tabla in tablas:
                if not tabla:
                    continue
                # Primera fila como encabezado
                header = [str(c).lower().strip() if c else "" for c in tabla[0]]
                # Detectar columnas de nombre y CI
                col_nombre = next((i for i, h in enumerate(header) if "nombre" in h or "apellido" in h), None)
                col_ci = next((i for i, h in enumerate(header) if "ci" in h or "cédula" in h or "cedula" in h or "documento" in h), None)

                if col_nombre is None:
                    # Si no hay header claro, asumir col 0 = nombre, col 1 = CI
                    col_nombre, col_ci = 0, 1

                for fila in tabla[1:]:
                    if not fila or not fila[col_nombre]:
                        continue
                    nombre = str(fila[col_nombre]).strip()
                    ci = str(fila[col_ci]).strip() if col_ci is not None and fila[col_ci] else ""
                    if nombre and nombre.lower() not in ("nombre", "apellido", "alumno", ""):
                        filas.append({"nombre": nombre, "ci": ci})
    return pd.DataFrame(filas)


# ─────────────────────────────────────────────
# EXPORTACIÓN EXCEL
# ─────────────────────────────────────────────

def generar_excel_resumen(grado_nombre: str, fecha_ini, fecha_fin, institucion: str) -> bytes:
    df = get_asistencia_rango(grado_nombre, fecha_ini, fecha_fin)
    resumen = get_resumen_grado(grado_nombre)

    wb = openpyxl.Workbook()

    # ── Hoja 1: Resumen general ──
    ws1 = wb.active
    ws1.title = "Resumen General"

    # Estilos
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    title_font = Font(bold=True, size=14, color="1F4E79")
    border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )
    verde = PatternFill("solid", fgColor="C6EFCE")
    rojo = PatternFill("solid", fgColor="FFC7CE")
    amarillo = PatternFill("solid", fgColor="FFEB9C")

    # Título
    ws1.merge_cells("A1:G1")
    ws1["A1"] = f"{institucion} — Registro de Asistencia"
    ws1["A1"].font = title_font
    ws1["A1"].alignment = Alignment(horizontal="center")

    ws1.merge_cells("A2:G2")
    ws1["A2"] = f"{grado_nombre}   |   Período: {fecha_ini.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}"
    ws1["A2"].alignment = Alignment(horizontal="center")
    ws1["A2"].font = Font(italic=True, size=10)

    # Encabezados tabla
    headers = ["Nombre", "CI", "Presentes", "F. Injustificadas", "F. Justificadas", "Días Registrados", "% Asistencia"]
    for col_idx, h in enumerate(headers, 1):
        cell = ws1.cell(row=4, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        cell.border = border

    # Datos
    est_ci = run_df("SELECT e.nombre, e.ci FROM estudiantes e JOIN grados g ON e.grado_id=g.id WHERE g.nombre=%s ORDER BY e.nombre", (grado_nombre,))
    ci_map = dict(zip(est_ci["nombre"], est_ci["ci"])) if not est_ci.empty else {}

    for row_idx, row in resumen.iterrows():
        pct = round(row["presentes"] / row["total_dias"] * 100, 1) if row["total_dias"] > 0 else 0
        valores = [
            row["nombre"], ci_map.get(row["nombre"], ""),
            row["presentes"], row["inj"], row["just"],
            row["total_dias"], f"{pct}%"
        ]
        for col_idx, val in enumerate(valores, 1):
            cell = ws1.cell(row=row_idx + 4, column=col_idx, value=val)
            cell.border = border
            cell.alignment = Alignment(horizontal="center" if col_idx > 1 else "left")
            if col_idx == 7:
                if pct >= 75:
                    cell.fill = verde
                else:
                    cell.fill = rojo

    # Anchos de columna
    anchos = [30, 12, 12, 18, 16, 16, 14]
    for i, ancho in enumerate(anchos, 1):
        ws1.column_dimensions[get_column_letter(i)].width = ancho

    # ── Hoja 2: Detalle de ausencias ──
    if not df.empty:
        ws2 = wb.create_sheet("Ausencias y Justificados")
        ausencias = df[df["estado"] != "Presente"].copy()

        headers2 = ["Fecha", "Nombre", "CI", "Grado", "Estado"]
        for col_idx, h in enumerate(headers2, 1):
            cell = ws2.cell(row=1, column=col_idx, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
            cell.border = border

        for row_idx, row in ausencias.iterrows():
            valores = [
                row["fecha"].strftime("%d/%m/%Y") if hasattr(row["fecha"], "strftime") else str(row["fecha"]),
                row["nombre"], row.get("ci", ""), row["grado"], row["estado"]
            ]
            for col_idx, val in enumerate(valores, 1):
                cell = ws2.cell(row=row_idx + 1, column=col_idx, value=val)
                cell.border = border
                cell.alignment = Alignment(horizontal="center" if col_idx != 2 else "left")
                if col_idx == 5:
                    cell.fill = rojo if "Injustificado" in str(val) else amarillo

        for i, ancho in enumerate([14, 30, 12, 16, 22], 1):
            ws2.column_dimensions[get_column_letter(i)].width = ancho

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────
# CSS TABLET
# ─────────────────────────────────────────────

def inject_css():
    st.markdown("""
    <style>
    html, body, [class*="css"] { font-size: 17px !important; }
    .stButton > button {
        min-height: 48px !important; font-size: 15px !important;
        border-radius: 10px !important; padding: 8px 16px !important;
    }
    /* Botones P / A / J */
    .btn-p button { background-color: #2ecc71 !important; color: white !important; font-weight: bold !important; font-size: 18px !important; min-height: 52px !important; border-radius: 10px !important; }
    .btn-a button { background-color: #e74c3c !important; color: white !important; font-weight: bold !important; font-size: 18px !important; min-height: 52px !important; border-radius: 10px !important; }
    .btn-j button { background-color: #f39c12 !important; color: white !important; font-weight: bold !important; font-size: 18px !important; min-height: 52px !important; border-radius: 10px !important; }
    .stSelectbox > div > div, .stDateInput > div > div > input {
        min-height: 48px !important; font-size: 16px !important; border-radius: 8px !important;
    }
    .stTextInput > div > div > input { min-height: 48px !important; font-size: 16px !important; border-radius: 8px !important; }
    .stRadio > div { gap: 6px !important; }
    .stRadio label { font-size: 16px !important; padding: 10px 12px !important; border-radius: 8px !important; }
    .stTabs [data-baseweb="tab"] { min-height: 48px !important; font-size: 15px !important; padding: 10px 18px !important; }
    [data-testid="metric-container"] [data-testid="stMetricValue"] { font-size: 26px !important; }
    [data-testid="stSidebar"] { min-width: 240px !important; }
    .main .block-container { padding-top: 1.5rem !important; padding-bottom: 3rem !important; max-width: 1100px; }
    </style>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# PÁGINAS
# ─────────────────────────────────────────────

def pagina_pasar_lista():
    st.header("📋 Pasar Lista")
    col1, col2 = st.columns([2, 1])
    with col1:
        grado_sel = st.selectbox("Grado", TODOS_LOS_GRADOS, key="lista_grado")
    with col2:
        fecha_sel = st.date_input("Fecha", value=date.today(), key="lista_fecha")

    df = get_asistencia_fecha(grado_sel, fecha_sel)
    if df.empty:
        st.warning(f"⚠️ No hay estudiantes en **{grado_sel}**.")
        return

    # Inicializar estados en session_state
    for _, row in df.iterrows():
        key = f"est_{row['estudiante_id']}"
        if key not in st.session_state:
            e = row["estado"] if row["estado"] in ESTADOS else "Presente"
            st.session_state[key] = e

    st.markdown(f"**{len(df)} estudiantes** — {grado_sel} — {fecha_sel.strftime('%d/%m/%Y')}")

    # Botón marcar todos presentes
    if st.button("✅ Marcar todos Presentes"):
        for _, row in df.iterrows():
            st.session_state[f"est_{row['estudiante_id']}"] = "Presente"
        st.rerun()

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    ICONO = {"Presente": "🟢", "Ausente Injustificado": "🔴", "Ausente Justificado": "🟡", "Sin registro": "⚪"}

    for _, row in df.iterrows():
        key = f"est_{row['estudiante_id']}"
        estado_actual = st.session_state.get(key, "Presente")

        st.markdown(
            f"<div style='font-size:17px;font-weight:600;padding:8px 0 4px 0;'>"
            f"{ICONO.get(estado_actual,'⚪')} {row['nombre']}</div>",
            unsafe_allow_html=True,
        )

        col_p, col_a, col_j = st.columns(3)

        with col_p:
            st.markdown('<div class="btn-p">', unsafe_allow_html=True)
            if st.button("P  Presente", key=f"p_{row['estudiante_id']}"):
                st.session_state[key] = "Presente"
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        with col_a:
            st.markdown('<div class="btn-a">', unsafe_allow_html=True)
            if st.button("A  Ausente", key=f"a_{row['estudiante_id']}"):
                st.session_state[key] = "Ausente Injustificado"
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        with col_j:
            st.markdown('<div class="btn-j">', unsafe_allow_html=True)
            if st.button("J  Justificado", key=f"j_{row['estudiante_id']}"):
                st.session_state[key] = "Ausente Justificado"
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("<hr style='margin:4px 0;opacity:0.12'>", unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    if st.button("💾 Guardar Asistencia", type="primary", use_container_width=True):
        registros = [
            (row["estudiante_id"], fecha_sel, st.session_state.get(f"est_{row['estudiante_id']}", "Presente"))
            for _, row in df.iterrows()
        ]
        guardar_asistencia(registros)
        st.success(f"✅ Asistencia guardada — {grado_sel} — {fecha_sel.strftime('%d/%m/%Y')}")
        st.balloons()


def pagina_resumen():
    st.header("📊 Resumen por Grado")
    institucion = get_config("institucion_nombre")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        grado_sel = st.selectbox("Grado", TODOS_LOS_GRADOS, key="resumen_grado")
    with col2:
        fecha_ini = st.date_input("Desde", value=date.today().replace(day=1), key="res_ini")
    with col3:
        fecha_fin = st.date_input("Hasta", value=date.today(), key="res_fin")

    df = get_resumen_grado(grado_sel)
    if df.empty or df["total_dias"].sum() == 0:
        st.info(f"📭 Aún no hay registros para **{grado_sel}**.")
        return

    total_reg = df["total_dias"].sum()
    total_p = df["presentes"].sum()
    total_inj = df["inj"].sum()
    total_just = df["just"].sum()
    pct = round((total_p / total_reg) * 100, 1) if total_reg else 0

    col1, col2 = st.columns(2)
    col1.metric("👥 Estudiantes", len(df))
    col2.metric("✅ % Asistencia", f"{pct}%")
    col3, col4 = st.columns(2)
    col3.metric("🔴 F. Injustificadas", total_inj)
    col4.metric("🟡 F. Justificadas", total_just)

    st.divider()
    col_pie, col_bar = st.columns(2)
    with col_pie:
        st.subheader("Distribución")
        fig = px.pie(
            names=["Presentes", "Inj.", "Just."],
            values=[total_p, total_inj, total_just],
            color_discrete_sequence=["#2ecc71", "#e74c3c", "#f39c12"], hole=0.4,
        )
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(showlegend=False, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with col_bar:
        st.subheader("Por Estudiante")
        df_plot = df.copy()
        df_plot["% Asistencia"] = (df_plot["presentes"] / df_plot["total_dias"] * 100).round(1)
        fig2 = px.bar(df_plot, x="nombre", y="% Asistencia", color="% Asistencia",
                      color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"], range_color=[0, 100])
        fig2.update_layout(xaxis_tickangle=-35, coloraxis_showscale=False, margin=dict(t=10, b=80))
        fig2.add_hline(y=75, line_dash="dash", line_color="red", annotation_text="Mínimo 75%")
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("📋 Detalle")
    df_t = df.rename(columns={"nombre": "Nombre", "presentes": "Presentes",
                               "inj": "F. Injustificadas", "just": "F. Justificadas", "total_dias": "Días"})
    df_t["% Asistencia"] = (df_t["Presentes"] / df_t["Días"] * 100).round(1).astype(str) + "%"
    st.dataframe(df_t, use_container_width=True, hide_index=True)

    # Exportar Excel
    st.divider()
    st.subheader("📥 Exportar a Excel")
    periodo = st.radio("Período", ["Día", "Semana", "Mes", "Personalizado"], horizontal=True)
    hoy = date.today()
    if periodo == "Día":
        f_ini, f_fin = hoy, hoy
    elif periodo == "Semana":
        f_ini = hoy - timedelta(days=hoy.weekday())
        f_fin = hoy
    elif periodo == "Mes":
        f_ini = hoy.replace(day=1)
        f_fin = hoy
    else:
        f_ini, f_fin = fecha_ini, fecha_fin

    if st.button("📊 Generar Excel", type="primary"):
        excel_bytes = generar_excel_resumen(grado_sel, f_ini, f_fin, institucion)
        st.download_button(
            label="⬇️ Descargar Excel",
            data=excel_bytes,
            file_name=f"asistencia_{grado_sel.replace('°','').replace(' ','_')}_{f_ini}_{f_fin}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def pagina_alertas():
    st.header("🚨 Alertas de Faltas Consecutivas")
    st.caption(f"Estudiantes con **{UMBRAL_FALTAS_CONSECUTIVAS} o más faltas consecutivas**.")

    filtro = st.selectbox("Filtrar por Grado", ["Todos los grados"] + TODOS_LOS_GRADOS, key="alerta_grado")
    df = detectar_faltas_consecutivas(None if filtro == "Todos los grados" else filtro)

    if df.empty:
        st.success("✅ ¡Sin alertas! Ningún estudiante tiene faltas consecutivas.")
        return

    st.error(f"⚠️ **{len(df)} estudiante(s)** requieren atención:")
    st.divider()
    for _, row in df.iterrows():
        col1, col2 = st.columns([3, 2])
        with col1:
            st.markdown(f"### 👤 {row['nombre']}")
            st.markdown(f"📚 **Grado:** {row['grado']}")
            st.markdown(f"📅 **Faltas consecutivas:** `{row['faltas_consecutivas']} días`")
            st.markdown(f"🗓️ **Desde:** {row['desde']}")
        with col2:
            st.markdown("### 📞 Contacto")
            st.info(f"**{row['contacto']}**")
        st.divider()

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Descargar CSV", data=csv,
                       file_name=f"alertas_{date.today()}.csv", mime="text/csv")


def pagina_gestion():
    st.header("🎓 Gestión de Estudiantes")
    tabs = st.tabs(["➕ Agregar", "📥 Importar PDF", "✏️ Editar / Mover", "🗑️ Eliminar"])

    # ── Tab 1: Agregar individual ──
    with tabs[0]:
        with st.form("form_agregar"):
            nombre = st.text_input("Nombre y apellido")
            ci = st.text_input("CI (Cédula de Identidad)")
            grado_sel = st.selectbox("Grado", TODOS_LOS_GRADOS)
            contacto = st.text_input("Contacto padre/tutor (opcional)")
            if st.form_submit_button("Agregar Estudiante", type="primary"):
                if nombre.strip():
                    agregar_estudiante(nombre, ci, grado_sel, contacto)
                    st.success(f"✅ **{nombre}** agregado a {grado_sel}.")
                else:
                    st.error("⚠️ El nombre no puede estar vacío.")

    # ── Tab 2: Importar PDF ──
    with tabs[1]:
        st.subheader("📥 Importar listado desde PDF")
        st.info("El PDF debe tener una tabla con columnas de **Nombre** y **CI**. Los contactos se pueden agregar después.")

        grado_import = st.selectbox("Grado destino", TODOS_LOS_GRADOS, key="grado_import")
        pdf_file = st.file_uploader("Subir PDF", type=["pdf"])

        if pdf_file:
            try:
                df_preview = extraer_alumnos_pdf(pdf_file.read())
                if df_preview.empty:
                    st.error("❌ No se encontraron alumnos en el PDF. Verificá que tenga una tabla con columnas de Nombre y CI.")
                else:
                    st.success(f"✅ Se encontraron **{len(df_preview)} alumnos**. Verificá antes de importar:")
                    st.dataframe(df_preview, use_container_width=True, hide_index=True)

                    if st.button("📥 Confirmar Importación", type="primary"):
                        conn = get_conn()
                        with conn.cursor() as cur:
                            cur.execute("SELECT id FROM grados WHERE nombre = %s", (grado_import,))
                            grado_row = cur.fetchone()
                            if grado_row:
                                count = 0
                                for _, r in df_preview.iterrows():
                                    if r["nombre"].strip():
                                        cur.execute(
                                            "INSERT INTO estudiantes (nombre, ci, grado_id) VALUES (%s, %s, %s)",
                                            (r["nombre"].strip(), r.get("ci", ""), grado_row[0]),
                                        )
                                        count += 1
                                conn.commit()
                                st.success(f"✅ {count} alumnos importados a **{grado_import}**.")
            except Exception as e:
                st.error(f"❌ Error al leer el PDF: {e}")

    # ── Tab 3: Editar / Mover ──
    with tabs[2]:
        st.subheader("✏️ Editar datos o mover de grado")
        grado_ver = st.selectbox("Ver estudiantes de", TODOS_LOS_GRADOS, key="editar_grado")
        df_est = get_estudiantes_por_grado(grado_ver)

        if df_est.empty:
            st.info(f"No hay estudiantes en {grado_ver}.")
        else:
            alumno_nombres = df_est["nombre"].tolist()
            alumno_sel = st.selectbox("Seleccionar alumno", alumno_nombres, key="alumno_editar")
            alumno_row = df_est[df_est["nombre"] == alumno_sel].iloc[0]

            with st.form("form_editar"):
                nuevo_nombre = st.text_input("Nombre", value=alumno_row["nombre"])
                nuevo_ci = st.text_input("CI", value=alumno_row.get("ci", "") or "")
                nuevo_grado = st.selectbox("Grado", TODOS_LOS_GRADOS,
                                           index=TODOS_LOS_GRADOS.index(grado_ver))
                nuevo_contacto = st.text_input("Contacto", value=alumno_row.get("contacto", "") or "")
                if st.form_submit_button("💾 Guardar Cambios", type="primary"):
                    actualizar_estudiante(alumno_row["id"], nuevo_nombre, nuevo_ci, nuevo_grado, nuevo_contacto)
                    st.success(f"✅ Datos de **{nuevo_nombre}** actualizados.")
                    st.rerun()

    # ── Tab 4: Eliminar ──
    with tabs[3]:
        st.subheader("🗑️ Eliminar estudiante")
        grado_del = st.selectbox("Grado", TODOS_LOS_GRADOS, key="del_grado")
        df_del = get_estudiantes_por_grado(grado_del)

        if df_del.empty:
            st.info(f"No hay estudiantes en {grado_del}.")
        else:
            for _, row in df_del.iterrows():
                col1, col2, col3 = st.columns([3, 2, 1])
                col1.write(f"👤 {row['nombre']}")
                col2.write(f"🪪 {row.get('ci', '') or '—'}")
                if col3.button("🗑️", key=f"del_{row['id']}"):
                    eliminar_estudiante(row["id"])
                    st.rerun()


def pagina_configuracion():
    st.header("⚙️ Configuración Institucional")

    nombre_actual = get_config("institucion_nombre")
    logo_actual = get_config("institucion_logo")

    with st.form("form_config"):
        st.subheader("🏫 Identidad de la institución")
        nuevo_nombre = st.text_input("Nombre de la institución", value=nombre_actual)

        st.subheader("🖼️ Logo institucional")
        logo_file = st.file_uploader("Subir logo (PNG o JPG, máx. 1MB)", type=["png", "jpg", "jpeg"])
        if logo_actual:
            st.markdown("**Logo actual:**")
            st.markdown(
                f'<img src="data:image/png;base64,{logo_actual}" style="max-height:80px;border-radius:8px;">',
                unsafe_allow_html=True,
            )

        if st.form_submit_button("💾 Guardar Configuración", type="primary"):
            set_config("institucion_nombre", nuevo_nombre.strip())
            if logo_file:
                logo_b64 = base64.b64encode(logo_file.read()).decode("utf-8")
                set_config("institucion_logo", logo_b64)
            st.success("✅ Configuración guardada.")
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
        st.error(f"❌ No se pudo conectar a la base de datos.\n\n`{e}`")
        st.stop()

    inject_css()

    # Cargar config institucional
    institucion_nombre = get_config("institucion_nombre")
    logo_b64 = get_config("institucion_logo")

    with st.sidebar:
        # Logo institucional o bandera Paraguay
        if logo_b64:
            st.markdown(
                f'<img src="data:image/png;base64,{logo_b64}" style="max-height:80px;border-radius:8px;margin-bottom:8px;">',
                unsafe_allow_html=True,
            )
        else:
            st.image("https://upload.wikimedia.org/wikipedia/commons/2/27/Flag_of_Paraguay.svg", width=80)

        st.title("🏫 " + institucion_nombre)
        st.caption("MEC Paraguay · Tercer Ciclo & Nivel Medio")
        st.divider()

        pagina = st.radio(
            "Navegación",
            ["📋 Pasar Lista", "📊 Resumen por Grado", "🚨 Alertas de Faltas",
             "🎓 Gestión de Estudiantes", "⚙️ Configuración"],
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
    elif pagina == "⚙️ Configuración":
        pagina_configuracion()


if __name__ == "__main__":
    main()

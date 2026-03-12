"""
Sistema de Gestión de Asistencia Escolar - MEC Paraguay
Versión 2.1 — Login, botones P/A/J estilo card, exportación Excel,
importación PDF, edición de estudiantes, logo institucional.
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
# LOGIN
# ─────────────────────────────────────────────

def pagina_login():
    """Pantalla de inicio de sesión."""
    st.markdown("""
    <style>
    .login-box {
        max-width: 420px;
        margin: 80px auto 0 auto;
        background: #1e2130;
        border-radius: 18px;
        padding: 40px 36px 32px 36px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.35);
    }
    .login-title {
        font-size: 26px;
        font-weight: 700;
        color: #ffffff;
        text-align: center;
        margin-bottom: 6px;
    }
    .login-sub {
        font-size: 13px;
        color: #8a8fa8;
        text-align: center;
        margin-bottom: 28px;
    }
    </style>
    """, unsafe_allow_html=True)

    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown('<div class="login-box">', unsafe_allow_html=True)
        st.markdown('<div class="login-title">🏫 Asistencia Escolar</div>', unsafe_allow_html=True)
        st.markdown('<div class="login-sub">MEC Paraguay · Tercer Ciclo & Nivel Medio</div>', unsafe_allow_html=True)

        usuario = st.text_input("👤 Usuario", placeholder="Ingresá tu usuario")
        contrasena = st.text_input("🔒 Contraseña", type="password", placeholder="Ingresá tu contraseña")

        if st.button("Ingresar", type="primary", use_container_width=True):
            usuario_ok = st.secrets.get("app_usuario", "Lucasmen")
            clave_ok   = st.secrets.get("app_password", "123456")
            if usuario == usuario_ok and contrasena == clave_ok:
                st.session_state["autenticado"] = True
                st.rerun()
            else:
                st.error("❌ Usuario o contraseña incorrectos.")

        st.markdown('</div>', unsafe_allow_html=True)


def verificar_login():
    """Devuelve True si el usuario está autenticado."""
    return st.session_state.get("autenticado", False)


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
        cur.execute("ALTER TABLE estudiantes ADD COLUMN IF NOT EXISTS ci TEXT;")
        for nivel, lista in GRADOS.items():
            for grado in lista:
                cur.execute(
                    "INSERT INTO grados (nombre, nivel) VALUES (%s, %s) ON CONFLICT (nombre) DO NOTHING",
                    (grado, nivel),
                )
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
                            "INSERT INTO asistencia (estudiante_id, fecha, estado) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                            (est_id, dia_actual, estado),
                        )
                        dias_sim += 1
                    dia_actual -= timedelta(days=1)
        conn.commit()


# ─────────────────────────────────────────────
# CONFIG INSTITUCIONAL
# ─────────────────────────────────────────────

def get_config(clave):
    rows = run_query("SELECT valor FROM config WHERE clave = %s", (clave,))
    return rows[0]["valor"] if rows else ""


def set_config(clave, valor):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO config (clave,valor) VALUES (%s,%s) ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
            (clave, valor),
        )
        conn.commit()


# ─────────────────────────────────────────────
# FUNCIONES DE DATOS
# ─────────────────────────────────────────────

def get_estudiantes_por_grado(grado_nombre):
    return run_df("""
        SELECT e.id, e.nombre, e.ci, e.contacto
        FROM estudiantes e JOIN grados g ON e.grado_id = g.id
        WHERE g.nombre = %s ORDER BY e.nombre
    """, (grado_nombre,))


def get_asistencia_fecha(grado_nombre, fecha):
    return run_df("""
        SELECT e.id as estudiante_id, e.nombre, e.ci,
               COALESCE(a.estado, 'Sin registro') as estado
        FROM estudiantes e JOIN grados g ON e.grado_id = g.id
        LEFT JOIN asistencia a ON a.estudiante_id = e.id AND a.fecha = %s
        WHERE g.nombre = %s ORDER BY e.nombre
    """, (fecha, grado_nombre))


def guardar_asistencia(registros):
    conn = get_conn()
    with conn.cursor() as cur:
        for est_id, fecha, estado in registros:
            cur.execute("""
                INSERT INTO asistencia (estudiante_id, fecha, estado) VALUES (%s,%s,%s)
                ON CONFLICT (estudiante_id, fecha) DO UPDATE SET estado=EXCLUDED.estado
            """, (est_id, fecha, estado))
        conn.commit()


def get_resumen_grado(grado_nombre):
    return run_df("""
        SELECT e.nombre,
               COUNT(CASE WHEN a.estado='Presente' THEN 1 END) as presentes,
               COUNT(CASE WHEN a.estado='Ausente Injustificado' THEN 1 END) as inj,
               COUNT(CASE WHEN a.estado='Ausente Justificado' THEN 1 END) as just,
               COUNT(a.id) as total_dias
        FROM estudiantes e JOIN grados g ON e.grado_id=g.id
        LEFT JOIN asistencia a ON a.estudiante_id=e.id
        WHERE g.nombre=%s GROUP BY e.id, e.nombre ORDER BY e.nombre
    """, (grado_nombre,))


def get_asistencia_rango(grado_nombre, fecha_ini, fecha_fin):
    return run_df("""
        SELECT e.nombre, e.ci, a.fecha, a.estado, g.nombre as grado
        FROM asistencia a
        JOIN estudiantes e ON a.estudiante_id=e.id
        JOIN grados g ON e.grado_id=g.id
        WHERE g.nombre=%s AND a.fecha BETWEEN %s AND %s
        ORDER BY e.nombre, a.fecha
    """, (grado_nombre, fecha_ini, fecha_fin))


def detectar_faltas_consecutivas(grado_nombre=None):
    filtro = "AND g.nombre = %s" if grado_nombre else ""
    params = (grado_nombre,) if grado_nombre else ()
    df = run_df(f"""
        SELECT e.id as estudiante_id, e.nombre, e.contacto, g.nombre as grado,
               a.fecha, a.estado
        FROM asistencia a
        JOIN estudiantes e ON a.estudiante_id=e.id
        JOIN grados g ON e.grado_id=g.id
        WHERE a.estado LIKE 'Ausente%%' {filtro}
        ORDER BY e.id, a.fecha DESC
    """, params)

    if df.empty:
        return pd.DataFrame(columns=["nombre","grado","contacto","faltas_consecutivas","desde"])

    resultados = []
    for est_id, grupo in df.groupby("estudiante_id"):
        fechas = sorted(pd.to_datetime(grupo["fecha"]).tolist(), reverse=True)
        racha = 1
        for i in range(1, len(fechas)):
            diff = (fechas[i-1] - fechas[i]).days
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
        cur.execute("SELECT id FROM grados WHERE nombre=%s", (grado_nombre,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "INSERT INTO estudiantes (nombre,ci,grado_id,contacto) VALUES (%s,%s,%s,%s)",
                (nombre.strip(), ci.strip(), row[0], contacto.strip()),
            )
            conn.commit()


def actualizar_estudiante(est_id, nombre, ci, grado_nombre, contacto):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM grados WHERE nombre=%s", (grado_nombre,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE estudiantes SET nombre=%s,ci=%s,grado_id=%s,contacto=%s WHERE id=%s",
                (nombre.strip(), ci.strip(), row[0], contacto.strip(), est_id),
            )
            conn.commit()


def eliminar_estudiante(est_id):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM asistencia WHERE estudiante_id=%s", (est_id,))
        cur.execute("DELETE FROM estudiantes WHERE id=%s", (est_id,))
        conn.commit()


# ─────────────────────────────────────────────
# IMPORTACIÓN PDF
# ─────────────────────────────────────────────

def extraer_alumnos_pdf(pdf_bytes):
    filas = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pagina in pdf.pages:
            for tabla in (pagina.extract_tables() or []):
                if not tabla:
                    continue
                header = [str(c).lower().strip() if c else "" for c in tabla[0]]
                col_nombre = next((i for i, h in enumerate(header) if "nombre" in h or "apellido" in h), 0)
                col_ci = next((i for i, h in enumerate(header) if "ci" in h or "cédula" in h or "cedula" in h), 1)
                for fila in tabla[1:]:
                    if not fila or not fila[col_nombre]:
                        continue
                    nombre = str(fila[col_nombre]).strip()
                    ci = str(fila[col_ci]).strip() if col_ci < len(fila) and fila[col_ci] else ""
                    if nombre and nombre.lower() not in ("nombre","apellido","alumno",""):
                        filas.append({"nombre": nombre, "ci": ci})
    return pd.DataFrame(filas)


# ─────────────────────────────────────────────
# EXPORTACIÓN EXCEL
# ─────────────────────────────────────────────

def generar_excel_resumen(grado_nombre, fecha_ini, fecha_fin, institucion):
    df = get_asistencia_rango(grado_nombre, fecha_ini, fecha_fin)
    resumen = get_resumen_grado(grado_nombre)
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Resumen General"

    hfill  = PatternFill("solid", fgColor="1F4E79")
    hfont  = Font(color="FFFFFF", bold=True, size=11)
    tfont  = Font(bold=True, size=14, color="1F4E79")
    brd    = Border(left=Side(style="thin"), right=Side(style="thin"),
                    top=Side(style="thin"), bottom=Side(style="thin"))
    verde  = PatternFill("solid", fgColor="C6EFCE")
    rojo   = PatternFill("solid", fgColor="FFC7CE")
    amarillo = PatternFill("solid", fgColor="FFEB9C")

    ws1.merge_cells("A1:G1")
    ws1["A1"] = f"{institucion} — Registro de Asistencia"
    ws1["A1"].font = tfont
    ws1["A1"].alignment = Alignment(horizontal="center")

    ws1.merge_cells("A2:G2")
    ws1["A2"] = f"{grado_nombre}   |   {fecha_ini.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}"
    ws1["A2"].alignment = Alignment(horizontal="center")
    ws1["A2"].font = Font(italic=True, size=10)

    for ci, h in enumerate(["Nombre","CI","Presentes","F. Injustificadas","F. Justificadas","Días","% Asistencia"], 1):
        c = ws1.cell(row=4, column=ci, value=h)
        c.fill = hfill; c.font = hfont
        c.alignment = Alignment(horizontal="center"); c.border = brd

    est_ci = run_df("SELECT e.nombre, e.ci FROM estudiantes e JOIN grados g ON e.grado_id=g.id WHERE g.nombre=%s ORDER BY e.nombre", (grado_nombre,))
    ci_map = dict(zip(est_ci["nombre"], est_ci["ci"])) if not est_ci.empty else {}

    for ri, row in resumen.iterrows():
        pct = round(row["presentes"]/row["total_dias"]*100, 1) if row["total_dias"] > 0 else 0
        for ci, val in enumerate([row["nombre"], ci_map.get(row["nombre"],""),
                                   row["presentes"], row["inj"], row["just"],
                                   row["total_dias"], f"{pct}%"], 1):
            c = ws1.cell(row=ri+4, column=ci, value=val)
            c.border = brd
            c.alignment = Alignment(horizontal="left" if ci==1 else "center")
            if ci == 7:
                c.fill = verde if pct >= 75 else rojo

    for i, w in enumerate([30,12,12,18,16,12,14], 1):
        ws1.column_dimensions[get_column_letter(i)].width = w

    if not df.empty:
        ws2 = wb.create_sheet("Ausencias y Justificados")
        aus = df[df["estado"] != "Presente"].copy()
        for ci, h in enumerate(["Fecha","Nombre","CI","Grado","Estado"], 1):
            c = ws2.cell(row=1, column=ci, value=h)
            c.fill = hfill; c.font = hfont
            c.alignment = Alignment(horizontal="center"); c.border = brd
        for ri, row in aus.iterrows():
            fecha_str = row["fecha"].strftime("%d/%m/%Y") if hasattr(row["fecha"],"strftime") else str(row["fecha"])
            for ci, val in enumerate([fecha_str, row["nombre"], row.get("ci",""), row["grado"], row["estado"]], 1):
                c = ws2.cell(row=ri+1, column=ci, value=val)
                c.border = brd
                c.alignment = Alignment(horizontal="left" if ci==2 else "center")
                if ci == 5:
                    c.fill = rojo if "Injustificado" in str(val) else amarillo
        for i, w in enumerate([14,30,12,16,22], 1):
            ws2.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────

def inject_css():
    st.markdown("""
    <style>
    html, body, [class*="css"] { font-size: 16px !important; }

    /* ── Card alumno ── */
    .alumno-card {
        background: #1e2130;
        border-radius: 14px;
        padding: 14px 18px;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 2px 8px rgba(0,0,0,0.18);
    }
    .alumno-info { flex: 1; }
    .alumno-nombre {
        font-size: 15px;
        font-weight: 700;
        color: #f0f2f6;
        text-transform: uppercase;
        letter-spacing: 0.3px;
    }
    .alumno-ci { font-size: 12px; color: #8a8fa8; margin-top: 2px; }

    /* ── Botones P/A/J circulares ── */
    .paj-btns {
        display: flex;
        gap: 10px;
        align-items: center;
    }
    .paj-btn {
        width: 44px; height: 44px;
        border-radius: 50%;
        border: 2px solid;
        font-weight: 700;
        font-size: 16px;
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        transition: all 0.15s;
        flex-shrink: 0;
    }
    .paj-P-off { border-color:#2ecc71; color:#2ecc71; background:transparent; }
    .paj-P-on  { border-color:#2ecc71; color:#fff;    background:#2ecc71; }
    .paj-A-off { border-color:#e74c3c; color:#e74c3c; background:transparent; }
    .paj-A-on  { border-color:#e74c3c; color:#fff;    background:#e74c3c; }
    .paj-J-off { border-color:#f39c12; color:#f39c12; background:transparent; }
    .paj-J-on  { border-color:#f39c12; color:#fff;    background:#f39c12; }

    /* ── Botones streamlit generales ── */
    .stButton > button {
        min-height: 48px !important;
        font-size: 15px !important;
        border-radius: 10px !important;
    }
    .stSelectbox > div > div,
    .stDateInput > div > div > input {
        min-height: 48px !important;
        font-size: 15px !important;
        border-radius: 8px !important;
    }
    .stTextInput > div > div > input {
        min-height: 48px !important;
        font-size: 15px !important;
        border-radius: 8px !important;
    }
    .stRadio label { font-size: 15px !important; padding: 8px 10px !important; border-radius: 8px !important; }
    .stTabs [data-baseweb="tab"] { min-height: 46px !important; font-size: 14px !important; }
    [data-testid="metric-container"] [data-testid="stMetricValue"] { font-size: 26px !important; }
    [data-testid="stSidebar"] { min-width: 240px !important; }
    .main .block-container { padding-top: 1.2rem !important; padding-bottom: 3rem !important; max-width: 1100px; }
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

    # Inicializar estados
    for _, row in df.iterrows():
        key = f"est_{row['estudiante_id']}"
        if key not in st.session_state:
            st.session_state[key] = row["estado"] if row["estado"] in ESTADOS else "Presente"

    st.markdown(f"**{len(df)} estudiantes** — {grado_sel} — {fecha_sel.strftime('%d/%m/%Y')}")

    if st.button("✅ Marcar todos Presentes"):
        for _, row in df.iterrows():
            st.session_state[f"est_{row['estudiante_id']}"] = "Presente"
        st.rerun()

    # Mapa de estado → letra
    ESTADO_LETRA = {"Presente": "P", "Ausente Injustificado": "A", "Ausente Justificado": "J"}
    LETRA_ESTADO = {"P": "Presente", "A": "Ausente Injustificado", "J": "Ausente Justificado"}

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    for _, row in df.iterrows():
        key = f"est_{row['estudiante_id']}"
        estado_actual = st.session_state.get(key, "Presente")
        letra_actual = ESTADO_LETRA.get(estado_actual, "P")
        ci_text = row.get("ci", "") or ""

        # Card con HTML + botones Streamlit superpuestos
        p_on = "paj-P-on" if letra_actual == "P" else "paj-P-off"
        a_on = "paj-A-on" if letra_actual == "A" else "paj-A-off"
        j_on = "paj-J-on" if letra_actual == "J" else "paj-J-off"

        col_info, col_p, col_a, col_j = st.columns([5, 1, 1, 1])

        with col_info:
            st.markdown(
                f"""<div style='padding:10px 0 6px 0;'>
                <div class='alumno-nombre'>{row['nombre']}</div>
                <div class='alumno-ci'>{ci_text}</div>
                </div>""",
                unsafe_allow_html=True,
            )

        with col_p:
            btn_style = "background:#2ecc71;color:white;" if letra_actual=="P" else "background:transparent;color:#2ecc71;"
            st.markdown(
                f"<style>#btn_p_{row['estudiante_id']} button{{border-radius:50%!important;width:48px!important;height:48px!important;padding:0!important;font-weight:700!important;font-size:17px!important;border:2px solid #2ecc71!important;{btn_style}}}</style>",
                unsafe_allow_html=True,
            )
            if st.button("P", key=f"p_{row['estudiante_id']}", help="Presente"):
                st.session_state[key] = "Presente"
                st.rerun()

        with col_a:
            btn_style = "background:#e74c3c;color:white;" if letra_actual=="A" else "background:transparent;color:#e74c3c;"
            st.markdown(
                f"<style>#btn_a_{row['estudiante_id']} button{{border-radius:50%!important;width:48px!important;height:48px!important;padding:0!important;font-weight:700!important;font-size:17px!important;border:2px solid #e74c3c!important;{btn_style}}}</style>",
                unsafe_allow_html=True,
            )
            if st.button("A", key=f"a_{row['estudiante_id']}", help="Ausente"):
                st.session_state[key] = "Ausente Injustificado"
                st.rerun()

        with col_j:
            btn_style = "background:#f39c12;color:white;" if letra_actual=="J" else "background:transparent;color:#f39c12;"
            st.markdown(
                f"<style>#btn_j_{row['estudiante_id']} button{{border-radius:50%!important;width:48px!important;height:48px!important;padding:0!important;font-weight:700!important;font-size:17px!important;border:2px solid #f39c12!important;{btn_style}}}</style>",
                unsafe_allow_html=True,
            )
            if st.button("J", key=f"j_{row['estudiante_id']}", help="Justificado"):
                st.session_state[key] = "Ausente Justificado"
                st.rerun()

        st.markdown("<hr style='margin:2px 0;opacity:0.1'>", unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    if st.button("💾 Guardar Asistencia", type="primary", use_container_width=True):
        registros = [
            (row["estudiante_id"], fecha_sel,
             st.session_state.get(f"est_{row['estudiante_id']}", "Presente"))
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
    total_p   = df["presentes"].sum()
    total_inj = df["inj"].sum()
    total_just= df["just"].sum()
    pct = round((total_p/total_reg)*100, 1) if total_reg else 0

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
            names=["Presentes","Inj.","Just."],
            values=[total_p, total_inj, total_just],
            color_discrete_sequence=["#2ecc71","#e74c3c","#f39c12"], hole=0.4,
        )
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(showlegend=False, margin=dict(t=10,b=10))
        st.plotly_chart(fig, use_container_width=True)

    with col_bar:
        st.subheader("Por Estudiante")
        df_p = df.copy()
        df_p["% Asistencia"] = (df_p["presentes"]/df_p["total_dias"]*100).round(1)
        fig2 = px.bar(df_p, x="nombre", y="% Asistencia", color="% Asistencia",
                      color_continuous_scale=["#e74c3c","#f39c12","#2ecc71"], range_color=[0,100])
        fig2.update_layout(xaxis_tickangle=-35, coloraxis_showscale=False, margin=dict(t=10,b=80))
        fig2.add_hline(y=75, line_dash="dash", line_color="red", annotation_text="Mínimo 75%")
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("📋 Detalle")
    df_t = df.rename(columns={"nombre":"Nombre","presentes":"Presentes",
                               "inj":"F. Injustificadas","just":"F. Justificadas","total_dias":"Días"})
    df_t["% Asistencia"] = (df_t["Presentes"]/df_t["Días"]*100).round(1).astype(str)+"%"
    st.dataframe(df_t, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📥 Exportar a Excel")
    periodo = st.radio("Período", ["Día","Semana","Mes","Personalizado"], horizontal=True)
    hoy = date.today()
    if periodo == "Día":
        f_ini, f_fin = hoy, hoy
    elif periodo == "Semana":
        f_ini = hoy - timedelta(days=hoy.weekday()); f_fin = hoy
    elif periodo == "Mes":
        f_ini = hoy.replace(day=1); f_fin = hoy
    else:
        f_ini, f_fin = fecha_ini, fecha_fin

    if st.button("📊 Generar Excel", type="primary"):
        excel_bytes = generar_excel_resumen(grado_sel, f_ini, f_fin, institucion)
        st.download_button(
            "⬇️ Descargar Excel", data=excel_bytes,
            file_name=f"asistencia_{grado_sel.replace('°','').replace(' ','_')}_{f_ini}_{f_fin}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def pagina_alertas():
    st.header("🚨 Alertas de Faltas Consecutivas")
    st.caption(f"Estudiantes con **{UMBRAL_FALTAS_CONSECUTIVAS} o más faltas consecutivas**.")

    filtro = st.selectbox("Filtrar por Grado", ["Todos los grados"]+TODOS_LOS_GRADOS, key="alerta_grado")
    df = detectar_faltas_consecutivas(None if filtro=="Todos los grados" else filtro)

    if df.empty:
        st.success("✅ ¡Sin alertas!")
        return

    st.error(f"⚠️ **{len(df)} estudiante(s)** requieren atención:")
    st.divider()
    for _, row in df.iterrows():
        c1, c2 = st.columns([3,2])
        with c1:
            st.markdown(f"### 👤 {row['nombre']}")
            st.markdown(f"📚 **Grado:** {row['grado']}")
            st.markdown(f"📅 **Faltas consecutivas:** `{row['faltas_consecutivas']} días`")
            st.markdown(f"🗓️ **Desde:** {row['desde']}")
        with c2:
            st.markdown("### 📞 Contacto")
            st.info(f"**{row['contacto']}**")
        st.divider()

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Descargar CSV", data=csv,
                       file_name=f"alertas_{date.today()}.csv", mime="text/csv")


def pagina_gestion():
    st.header("🎓 Gestión de Estudiantes")
    tabs = st.tabs(["➕ Agregar","📥 Importar PDF","✏️ Editar / Mover","🗑️ Eliminar"])

    with tabs[0]:
        with st.form("form_agregar"):
            nombre   = st.text_input("Nombre y apellido")
            ci       = st.text_input("CI (Cédula de Identidad)")
            grado_s  = st.selectbox("Grado", TODOS_LOS_GRADOS)
            contacto = st.text_input("Contacto padre/tutor (opcional)")
            if st.form_submit_button("Agregar Estudiante", type="primary"):
                if nombre.strip():
                    agregar_estudiante(nombre, ci, grado_s, contacto)
                    st.success(f"✅ **{nombre}** agregado a {grado_s}.")
                else:
                    st.error("⚠️ El nombre no puede estar vacío.")

    with tabs[1]:
        st.subheader("📥 Importar listado desde PDF")
        st.info("El PDF debe tener tabla con columnas **Nombre** y **CI**.")
        grado_import = st.selectbox("Grado destino", TODOS_LOS_GRADOS, key="grado_import")
        pdf_file = st.file_uploader("Subir PDF", type=["pdf"])
        if pdf_file:
            try:
                df_prev = extraer_alumnos_pdf(pdf_file.read())
                if df_prev.empty:
                    st.error("❌ No se encontraron alumnos. Verificá que el PDF tenga tabla con Nombre y CI.")
                else:
                    st.success(f"✅ **{len(df_prev)} alumnos** encontrados. Verificá:")
                    st.dataframe(df_prev, use_container_width=True, hide_index=True)
                    if st.button("📥 Confirmar Importación", type="primary"):
                        conn = get_conn()
                        with conn.cursor() as cur:
                            cur.execute("SELECT id FROM grados WHERE nombre=%s", (grado_import,))
                            gr = cur.fetchone()
                            if gr:
                                count = 0
                                for _, r in df_prev.iterrows():
                                    if r["nombre"].strip():
                                        cur.execute(
                                            "INSERT INTO estudiantes (nombre,ci,grado_id) VALUES (%s,%s,%s)",
                                            (r["nombre"].strip(), r.get("ci",""), gr[0]),
                                        )
                                        count += 1
                                conn.commit()
                                st.success(f"✅ {count} alumnos importados a **{grado_import}**.")
            except Exception as e:
                st.error(f"❌ Error al leer el PDF: {e}")

    with tabs[2]:
        st.subheader("✏️ Editar datos o mover de grado")
        grado_ver = st.selectbox("Ver estudiantes de", TODOS_LOS_GRADOS, key="editar_grado")
        df_est = get_estudiantes_por_grado(grado_ver)
        if df_est.empty:
            st.info(f"No hay estudiantes en {grado_ver}.")
        else:
            alumno_sel = st.selectbox("Seleccionar alumno", df_est["nombre"].tolist(), key="alumno_editar")
            ar = df_est[df_est["nombre"]==alumno_sel].iloc[0]
            with st.form("form_editar"):
                nn = st.text_input("Nombre", value=ar["nombre"])
                nc = st.text_input("CI", value=ar.get("ci","") or "")
                ng = st.selectbox("Grado", TODOS_LOS_GRADOS, index=TODOS_LOS_GRADOS.index(grado_ver))
                nco= st.text_input("Contacto", value=ar.get("contacto","") or "")
                if st.form_submit_button("💾 Guardar Cambios", type="primary"):
                    actualizar_estudiante(ar["id"], nn, nc, ng, nco)
                    st.success(f"✅ Datos de **{nn}** actualizados.")
                    st.rerun()

    with tabs[3]:
        st.subheader("🗑️ Eliminar estudiante")
        grado_del = st.selectbox("Grado", TODOS_LOS_GRADOS, key="del_grado")
        df_del = get_estudiantes_por_grado(grado_del)
        if df_del.empty:
            st.info(f"No hay estudiantes en {grado_del}.")
        else:
            for _, row in df_del.iterrows():
                c1, c2, c3 = st.columns([3,2,1])
                c1.write(f"👤 {row['nombre']}")
                c2.write(f"🪪 {row.get('ci','') or '—'}")
                if c3.button("🗑️", key=f"del_{row['id']}"):
                    eliminar_estudiante(row["id"])
                    st.rerun()


def pagina_configuracion():
    st.header("⚙️ Configuración Institucional")
    nombre_actual = get_config("institucion_nombre")
    logo_actual   = get_config("institucion_logo")

    with st.form("form_config"):
        st.subheader("🏫 Nombre de la institución")
        nuevo_nombre = st.text_input("Nombre", value=nombre_actual)

        st.subheader("🖼️ Logo institucional")
        logo_file = st.file_uploader("Subir logo (PNG/JPG)", type=["png","jpg","jpeg"])
        if logo_actual:
            st.markdown("**Logo actual:**")
            st.markdown(
                f'<img src="data:image/png;base64,{logo_actual}" style="max-height:80px;border-radius:8px;">',
                unsafe_allow_html=True,
            )

        if st.form_submit_button("💾 Guardar", type="primary"):
            set_config("institucion_nombre", nuevo_nombre.strip())
            if logo_file:
                set_config("institucion_logo", base64.b64encode(logo_file.read()).decode("utf-8"))
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

    # ── LOGIN ──
    if not verificar_login():
        pagina_login()
        st.stop()

    # ── APP ──
    try:
        init_db()
        seed_mock_data()
    except Exception as e:
        st.error(f"❌ No se pudo conectar a la base de datos.\n\n`{e}`")
        st.stop()

    inject_css()

    institucion_nombre = get_config("institucion_nombre")
    logo_b64 = get_config("institucion_logo")

    with st.sidebar:
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
            ["📋 Pasar Lista","📊 Resumen por Grado","🚨 Alertas de Faltas",
             "🎓 Gestión de Estudiantes","⚙️ Configuración"],
            label_visibility="collapsed",
        )

        st.divider()
        st.caption(f"📅 Hoy: {date.today().strftime('%d/%m/%Y')}")
        n_est = run_df("SELECT COUNT(*) as c FROM estudiantes")["c"][0]
        n_reg = run_df("SELECT COUNT(*) as c FROM asistencia")["c"][0]
        st.metric("Total Estudiantes", n_est)
        st.metric("Registros de Asistencia", n_reg)

        st.divider()
        if st.button("🚪 Cerrar sesión"):
            st.session_state["autenticado"] = False
            st.rerun()

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

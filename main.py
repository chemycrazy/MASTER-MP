import flet as ft
import os
import psycopg2
import logging
import json
import math
import datetime
import base64
from contextlib import contextmanager
from fpdf import FPDF
import sys

# Aumentar la recursividad para evitar errores en interfaces complejas
sys.setrecursionlimit(2000)

# --- CONFIGURACIÓN Y LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Definición global para almacenar el usuario activo
current_user = {"id": None, "name": "GUEST", "role": "GUEST"}

# --- CONEXIÓN A BASE DE DATOS ---
# Asegúrate de que esta URL sea la correcta de tu proyecto Supabase
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:MPMASTER57667115@db.rhuudiwamxpfkinpgkzs.supabase.co:5432/postgres")

# --- CAPA DE DATOS ---
class DBManager:
    def __init__(self):
        self.init_db()

    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = psycopg2.connect(DATABASE_URL)
            yield conn
        except Exception as e:
            logger.error(f"Error de conexión DB: {e}")
            raise e
        finally:
            if conn:
                conn.close()

    def execute_query(self, query, params=(), fetch=False):
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    if fetch:
                        return cur.fetchall()
                    conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Error Query: {query} | Error: {e}")
            return None
def init_db(self):
        commands = [
            """CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(50) NOT NULL,
                role VARCHAR(20) DEFAULT 'OPERADOR',
                is_locked BOOLEAN DEFAULT FALSE
            )""",
            """CREATE TABLE IF NOT EXISTS materials (
                id SERIAL PRIMARY KEY,
                code VARCHAR(20) UNIQUE,
                name VARCHAR(100),
                category VARCHAR(50),
                is_active BOOLEAN DEFAULT TRUE
            )""",
            """CREATE TABLE IF NOT EXISTS standard_tests (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                method VARCHAR(100)
            )""",
            """CREATE TABLE IF NOT EXISTS material_profile (
                id SERIAL PRIMARY KEY,
                material_id INTEGER REFERENCES materials(id) ON DELETE CASCADE,
                test_id INTEGER REFERENCES standard_tests(id),
                specification VARCHAR(200),
                UNIQUE(material_id, test_id)
            )""",
            """CREATE TABLE IF NOT EXISTS inventory (
                id SERIAL PRIMARY KEY,
                material_id INTEGER REFERENCES materials(id),
                lot_internal VARCHAR(50),
                lot_vendor VARCHAR(50),
                expiry_date DATE,
                quantity FLOAT,
                status VARCHAR(20) DEFAULT 'CUARENTENA',
                manufacturer VARCHAR(100)
            )""",
            """CREATE TABLE IF NOT EXISTS lab_results (
                id SERIAL PRIMARY KEY,
                inventory_id INTEGER REFERENCES inventory(id),
                analyst VARCHAR(50),
                result_data JSONB,
                conclusion VARCHAR(20),
                date_analyzed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                analysis_num VARCHAR(50),
                bib_reference VARCHAR(100),
                reanalysis_date DATE,
                observations TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS audit_trail (
                id SERIAL PRIMARY KEY,
                user_name VARCHAR(50),
                action VARCHAR(50),
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        ]
        
        create_admin = """
            INSERT INTO users (username, password, role)
            VALUES ('admin', 'admin', 'ADMIN')
            ON CONFLICT (username) DO NOTHING
        """

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    for cmd in commands:
                        cur.execute(cmd)
                    cur.execute(create_admin)
                    conn.commit()
        except Exception as e:
            logger.critical(f"Fallo inicialización DB: {e}")

db = DBManager()

# --- FUNCIONES AUXILIARES ---
def log_audit(user, action, details):
    db.execute_query("INSERT INTO audit_trail (user_name, action, details) VALUES (%s, %s, %s)", (user, action, details))

# --- FUNCIÓN PDF (Compatible Flet Moderno) ---
def open_pdf_in_browser(page, filename, content_dict, test_results):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, "CERTIFICADO DE ANALISIS", ln=1, align="C")
        pdf.set_font("Arial", size=10)
        pdf.ln(5)

        # Función para limpiar texto (evita errores de caracteres)
        def clean_text(text):
            return str(text).encode('latin-1', 'replace').decode('latin-1')

        for key, value in content_dict.items():
            if key not in ["Observaciones", "Conclusión"]:
                pdf.set_font("Arial", "B", 10)
                pdf.cell(50, 8, txt=clean_text(f"{key}:"), border=0)
                pdf.set_font("Arial", size=10)
                pdf.cell(0, 8, txt=clean_text(value), ln=1, border=0)

        if "Conclusión" in content_dict:
            pdf.set_font("Arial", "B", 10)
            pdf.cell(50, 8, txt="Dictamen:", border=0)
            pdf.set_font("Arial", size=10)
            pdf.cell(0, 8, txt=clean_text(content_dict["Conclusión"]), ln=1, border=0)

        pdf.ln(5)
        
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(60, 8, clean_text("Prueba"), 1, fill=True)
        pdf.cell(70, 8, clean_text("Especificación"), 1, fill=True)
        pdf.cell(60, 8, clean_text("Resultado"), 1, ln=1, fill=True)

        pdf.set_font("Arial", size=10)
        for test in test_results:
            pdf.cell(60, 8, clean_text(test.get('test', '')), 1)
            pdf.cell(70, 8, clean_text(test.get('spec', '')), 1)
            pdf.cell(60, 8, clean_text(test.get('result', '')), 1, ln=1)

        pdf.ln(10)
        if "Observaciones" in content_dict and content_dict["Observaciones"]:
            pdf.set_font("Arial", "B", 10)
            pdf.cell(0, 8, clean_text("Observaciones Adicionales:"), ln=1)
            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 6, clean_text(content_dict["Observaciones"]))

        # Generación Base64
        pdf_bytes = pdf.output(dest='S').encode('latin-1')
        b64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')

        page.run_js(f"""
            var link = document.createElement('a');
            link.href = "data:application/pdf;base64,{b64_pdf}";
            link.download = "{filename}";
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        """)
        return True

    except Exception as e:
        logger.error(f"Error PDF: {e}")
        return False
# --- MÓDULOS DE LA UI ---

def build_catalog_view(page, content_column, current_user):
    tab_content = ft.Column(expand=True)

    def render_catalog_content(index):
        tab_content.controls.clear()
        if index == 0: # MATERIAS PRIMAS
            materials = db.execute_query("SELECT id, code, name, is_active FROM materials ORDER BY id DESC", fetch=True) or []
            for m in materials:
                tab_content.controls.append(
                    ft.Card(content=ft.ListTile(
                        leading=ft.Icon(ft.Icons.CIRCLE, color=ft.Colors.GREEN if m[3] else ft.Colors.RED),
                        title=ft.Text(f"{m[1]} - {m[2]}"),
                        trailing=ft.IconButton(ft.Icons.SETTINGS, tooltip="Configurar Perfil",
                            on_click=lambda e, mid=m[0], name=m[2]: open_profile_dialog(page, mid, name))
                    ))
                )
            tab_content.controls.insert(0, ft.ElevatedButton("Nueva Materia Prima", icon=ft.Icons.ADD,
                on_click=lambda e: add_material_dialog(page, content_column, current_user)))
        
        elif index == 1: # PRUEBAS MASTER
            tests = db.execute_query("SELECT id, name, method FROM standard_tests ORDER BY name", fetch=True) or []
            for t in tests:
                tab_content.controls.append(
                    ft.ListTile(title=ft.Text(t[1]), subtitle=ft.Text(f"Método: {t[2]}"), leading=ft.Icon(ft.Icons.CHECK_BOX))
                )
            tab_content.controls.insert(0, ft.ElevatedButton("Nueva Prueba Estándar", icon=ft.Icons.ADD,
                on_click=lambda e: add_test_dialog(page, content_column, current_user)))
        page.update()

    tabs = ft.Tabs(
        selected_index=0,
        tabs=[ft.Tab(text="Materias Primas", icon=ft.Icons.LAYERS), ft.Tab(text="Pruebas Master", icon=ft.Icons.LIST_ALT)],
        on_change=lambda e: render_catalog_content(e.control.selected_index)
    )
    
    content_column.controls = [ft.Text("Gestión de Catálogos", size=20, weight="bold"), tabs, tab_content]
    render_catalog_content(0)
    page.update()

# --- DIALOGOS CATALOGO ---
def open_profile_dialog(page, material_id, material_name):
    list_col = ft.Column(height=200, scroll=ft.ScrollMode.ALWAYS)
    
    def refresh_list():
        current_tests = db.execute_query("SELECT mp.id, st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id = st.id WHERE mp.material_id = %s", (material_id,), fetch=True) or []
        list_col.controls.clear()
        for t in current_tests:
            list_col.controls.append(ft.ListTile(
                title=ft.Text(t[1]), subtitle=ft.Text(f"Spec: {t[2]}"),
                trailing=ft.IconButton(ft.Icons.DELETE, icon_color=ft.Colors.RED, on_click=lambda e, pid=t[0]: delete_profile_item(pid))
            ))
        page.update()

    def delete_profile_item(pid):
        db.execute_query("DELETE FROM material_profile WHERE id=%s", (pid,))
        refresh_list()

    all_tests = db.execute_query("SELECT id, name FROM standard_tests", fetch=True) or []
    dd_tests = ft.Dropdown(label="Seleccionar Prueba", options=[ft.dropdown.Option(str(t[0]), t[1]) for t in all_tests], expand=True)
    spec_tf = ft.TextField(label="Especificación", expand=True)

    def add_test_to_profile(e):
        if not dd_tests.value or not spec_tf.value:
            return
        try:
            db.execute_query("INSERT INTO material_profile (material_id, test_id, specification) VALUES (%s, %s, %s)", (material_id, dd_tests.value, spec_tf.value))
            spec_tf.value = ""
            refresh_list()
        except Exception:
            page.snack_bar = ft.SnackBar(ft.Text("Error: Prueba ya asignada"))
            page.snack_bar.open = True
            page.update()

    refresh_list()
    page.dialog = ft.AlertDialog(
        title=ft.Text(f"Perfil: {material_name}"),
        content=ft.Column([ft.Text("Pruebas Lab:"), ft.Row([dd_tests, spec_tf]), ft.ElevatedButton("Agregar", on_click=add_test_to_profile), ft.Divider(), list_col], tight=True),
    )
    page.dialog.open = True
    page.update()

def add_material_dialog(page, content_column, current_user):
    code = ft.TextField(label="Código")
    name = ft.TextField(label="Nombre")
    cat = ft.Dropdown(label="Categoría", options=[ft.dropdown.Option("API"), ft.dropdown.Option("EXCIPIENTE")])

    def save(e):
        if not code.value or not name.value: return
        db.execute_query("INSERT INTO materials (code, name, category) VALUES (%s, %s, %s)", (code.value, name.value, cat.value))
        page.dialog.open = False
        build_catalog_view(page, content_column, current_user)
        page.update()

    page.dialog = ft.AlertDialog(title=ft.Text("Crear Material"), content=ft.Column([code, name, cat], tight=True), actions=[ft.TextButton("Guardar", on_click=save)])
    page.dialog.open = True
    page.update()

def add_test_dialog(page, content_column, current_user):
    name = ft.TextField(label="Nombre Prueba")
    method = ft.TextField(label="Método")

    def save(e):
        if not name.value: return
        db.execute_query("INSERT INTO standard_tests (name, method) VALUES (%s, %s)", (name.value, method.value))
        page.dialog.open = False
        build_catalog_view(page, content_column, current_user)
        page.update()

    page.dialog = ft.AlertDialog(title=ft.Text("Crear Prueba"), content=ft.Column([name, method], tight=True), actions=[ft.TextButton("Guardar", on_click=save)])
    page.dialog.open = True
    page.update()
# --- ALMACEN ---
def build_inventory_view(page, content_column, current_user):
    materials = db.execute_query("SELECT id, name, code FROM materials WHERE is_active=TRUE ORDER BY name", fetch=True) or []
    mat_opts = [ft.dropdown.Option(key=str(m[0]), text=f"{m[1]} ({m[2]})") for m in materials]
    
    mat_dd = ft.Dropdown(label="Materia Prima", options=mat_opts, expand=True)
    lot_int = ft.TextField(label="Lote Interno", expand=True)
    lot_ven = ft.TextField(label="Lote Proveedor", expand=True)
    manufacturer = ft.TextField(label="Fabricante", expand=True)
    qty = ft.TextField(label="Cantidad (kg)", keyboard_type=ft.KeyboardType.NUMBER, expand=True)
    expiry = ft.TextField(label="Caducidad (YYYY-MM-DD)", expand=True)

    def receive_material(e):
        if not all([mat_dd.value, lot_int.value, qty.value]):
            page.snack_bar = ft.SnackBar(ft.Text("Campos obligatorios vacíos"))
            page.snack_bar.open = True
            page.update()
            return
        try:
            db.execute_query("INSERT INTO inventory (material_id, lot_internal, lot_vendor, manufacturer, expiry_date, quantity, status) VALUES (%s, %s, %s, %s, %s, %s, 'CUARENTENA')",
                             (mat_dd.value, lot_int.value, lot_ven.value, manufacturer.value, expiry.value, float(qty.value)))
            log_audit(current_user["name"], "RECEIPT", f"Ingreso Lote {lot_int.value}")
            page.snack_bar = ft.SnackBar(ft.Text("Material Ingresado"))
            page.snack_bar.open = True
            # Limpiar
            lot_int.value = ""
            qty.value = ""
            page.update()
        except Exception as ex:
            logger.error(ex)
            page.snack_bar = ft.SnackBar(ft.Text("Error al guardar"))
            page.snack_bar.open = True
            page.update()

    content_column.controls = [
        ft.Text("Recepción Almacén", size=20, weight="bold"),
        mat_dd, ft.Row([lot_int, lot_ven]), manufacturer, ft.Row([qty, expiry]),
        ft.ElevatedButton("Ingresar", icon=ft.Icons.SAVE_ALT, on_click=receive_material, bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE)
    ]
    page.update()
# --- MUESTREO ---
def build_sampling_view(page, content_column, current_user):
    items = db.execute_query("SELECT i.id, m.name, i.lot_internal, i.quantity FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='CUARENTENA'", fetch=True) or []
    lv = ft.ListView(expand=True, spacing=10)

    def open_sampling_dialog(item_id, name, lot, current_qty):
        tf_n = ft.TextField(label="N Envases", keyboard_type=ft.KeyboardType.NUMBER, autofocus=True)
        txt_formula = ft.Text("A abrir: 0", color=ft.Colors.BLUE)
        tf_removed = ft.TextField(label="Cant. Muestreada (kg)", value="0.0")

        def calc_formula(e):
            if tf_n.value:
                try:
                    res = math.ceil(math.sqrt(int(tf_n.value)) + 1)
                    txt_formula.value = f"A abrir: {res}"
                    page.update()
                except: pass

        tf_n.on_change = calc_formula

        def save_sampling(e):
            try:
                rem = float(tf_removed.value)
                if rem > current_qty:
                    tf_removed.error_text = "Excede stock"
                    page.update()
                    return
                new_qty = current_qty - rem
                db.execute_query("UPDATE inventory SET quantity=%s, status='MUESTREADO' WHERE id=%s", (new_qty, item_id))
                log_audit(current_user["name"], "SAMPLING", f"Muestreo Lote {lot}")
                page.dialog.open = False
                build_sampling_view(page, content_column, current_user)
                page.update()
            except: pass

        page.dialog = ft.AlertDialog(
            title=ft.Text(f"Muestreo: {lot}"),
            content=ft.Column([ft.Text(f"Stock: {current_qty}"), tf_n, txt_formula, tf_removed], tight=True),
            actions=[ft.ElevatedButton("Confirmar", on_click=save_sampling)]
        )
        page.dialog.open = True
        page.update()

    if not items:
        lv.controls.append(ft.Text("No hay lotes en Cuarentena"))
    
    for i in items:
        lv.controls.append(ft.Card(content=ft.ListTile(
            leading=ft.Icon(ft.Icons.SCIENCE, color=ft.Colors.ORANGE),
            title=ft.Text(i[1]), subtitle=ft.Text(f"Lote: {i[2]} | Stock: {i[3]}"),
            trailing=ft.IconButton(ft.Icons.ARROW_FORWARD, on_click=lambda e, x=i: open_sampling_dialog(x[0], x[1], x[2], x[3]))
        )))

    content_column.controls = [ft.Text("Muestreo", size=20, weight="bold"), lv]
    page.update()
# --- LAB ---
def build_lab_view(page, content_column, current_user):
    pending = db.execute_query("SELECT i.id, m.name, i.lot_internal, i.material_id FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='MUESTREADO'", fetch=True) or []
    lv = ft.ListView(expand=True, spacing=10)

    def open_analysis(inv_id, mat_id, mat_name, lot):
        profile = db.execute_query("SELECT st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id = st.id WHERE mp.material_id=%s", (mat_id,), fetch=True) or []
        
        if not profile:
            page.snack_bar = ft.SnackBar(ft.Text("Sin perfil de pruebas configurado"))
            page.snack_bar.open = True
            page.update()
            return

        tf_num = ft.TextField(label="No. Análisis")
        tf_obs = ft.TextField(label="Obs")
        dd_con = ft.Dropdown(label="Dictamen", options=[ft.dropdown.Option("APROBADO"), ft.dropdown.Option("RECHAZADO")], value="APROBADO")
        inputs = [ft.TextField(label=f"{p[0]} ({p[1]})", data={"test": p[0], "spec": p[1]}) for p in profile]

        def save(e):
            if not tf_num.value: return
            res_json = {f.data['test']: f.value for f in inputs if f.value}
            res_list = [{"test": f.data['test'], "spec": f.data['spec'], "result": f.value} for f in inputs]
            
            try:
                db.execute_query("INSERT INTO lab_results (inventory_id, analyst, result_data, conclusion, analysis_num, observations) VALUES (%s, %s, %s, %s, %s, %s)",
                                 (inv_id, current_user["name"], json.dumps(res_json), dd_con.value, tf_num.value, tf_obs.value))
                st = "LIBERADO" if dd_con.value == "APROBADO" else "RECHAZADO"
                db.execute_query("UPDATE inventory SET status=%s WHERE id=%s", (st, inv_id))
                log_audit(current_user["name"], "LAB_RELEASE", f"Analisis Lote {lot}")
                
                # PDF
                pdf_content = {"Producto": mat_name, "Lote": lot, "Conclusión": dd_con.value}
                open_pdf_in_browser(page, f"CoA_{lot}.pdf", pdf_content, res_list)
                
                page.dialog.open = False
                build_lab_view(page, content_column, current_user)
                page.update()
            except Exception as ex:
                logger.error(ex)

        page.dialog = ft.AlertDialog(
            title=ft.Text(f"Análisis {lot}"),
            content=ft.Column([tf_num] + inputs + [dd_con, tf_obs], tight=True, scroll=ft.ScrollMode.ALWAYS, height=400),
            actions=[ft.ElevatedButton("Guardar", on_click=save)]
        )
        page.dialog.open = True
        page.update()

    for p in pending:
        lv.controls.append(ft.Card(content=ft.ListTile(
            title=ft.Text(p[1]), subtitle=ft.Text(p[2]),
            trailing=ft.IconButton(ft.Icons.PLAY_ARROW, on_click=lambda e, x=p: open_analysis(x[0], x[3], x[1], x[2]))
        )))

    content_column.controls = [ft.Text("Laboratorio", size=20, weight="bold"), lv]
    page.update()
# --- CONSULTA ---
def build_query_view(page, content_column, current_user):
    search_tf = ft.TextField(label="Buscar", suffix_icon=ft.Icons.SEARCH)
    res_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    def show_details(data):
        # data = [id, code, name, lot_int, status, qty]
        item_id = data[0]
        # Recuperar datos completos y lab results
        inv_data = db.execute_query("SELECT manufacturer, lot_vendor, expiry_date FROM inventory WHERE id=%s", (item_id,), fetch=True)[0]
        lab_data = db.execute_query("SELECT analysis_num, conclusion, result_data, observations FROM lab_results WHERE inventory_id=%s", (item_id,), fetch=True)
        
        info = [
            ft.Text(f"Producto: {data[2]}"),
            ft.Text(f"Lote Interno: {data[3]}"),
            ft.Text(f"Fabricante: {inv_data[0]}"),
            ft.Text(f"Lote Prov: {inv_data[1]}"),
            ft.Text(f"Caducidad: {inv_data[2]}"),
            ft.Divider()
        ]
        
        if lab_data:
            ld = lab_data[0]
            info.append(ft.Text(f"Análisis: {ld[0]}"))
            info.append(ft.Text(f"Dictamen: {ld[1]}", color=ft.Colors.GREEN if ld[1]=="APROBADO" else ft.Colors.RED))
            
            # Tabla resultados
            try:
                res_json = ld[2] if isinstance(ld[2], dict) else json.loads(ld[2])
                dt = ft.DataTable(columns=[ft.DataColumn(ft.Text("Prueba")), ft.DataColumn(ft.Text("Resultado"))], rows=[])
                for k,v in res_json.items():
                    dt.rows.append(ft.DataRow(cells=[ft.DataCell(ft.Text(k)), ft.DataCell(ft.Text(str(v)))]))
                info.append(dt)
            except: pass

            def print_copy(e):
                res_list = [{"test": k, "spec": "-", "result": str(v)} for k,v in res_json.items()]
                open_pdf_in_browser(page, f"COPY_{data[3]}.pdf", {"Producto": data[2], "Lote": data[3], "Conclusión": ld[1]}, res_list)

            info.append(ft.ElevatedButton("Descargar Copia", icon=ft.Icons.PRINT, on_click=print_copy))
        else:
            info.append(ft.Text("Sin análisis"))

        page.dialog = ft.AlertDialog(title=ft.Text("Detalle"), content=ft.Column(info, tight=True, scroll=ft.ScrollMode.ALWAYS, height=400))
        page.dialog.open = True
        page.update()

    def search(e):
        term = f"%{search_tf.value}%"
        items = db.execute_query("SELECT i.id, m.code, m.name, i.lot_internal, i.status, i.quantity FROM inventory i JOIN materials m ON i.material_id=m.id WHERE m.name ILIKE %s OR i.lot_internal ILIKE %s", (term, term), fetch=True) or []
        res_col.controls.clear()
        for i in items:
            res_col.controls.append(ft.Card(content=ft.ListTile(
                title=ft.Text(i[2]), subtitle=ft.Text(f"{i[3]} - {i[4]}"),
                leading=ft.Icon(ft.Icons.CIRCLE, color=ft.Colors.GREEN if i[4]=="LIBERADO" else ft.Colors.ORANGE),
                trailing=ft.IconButton(ft.Icons.VISIBILITY, on_click=lambda e, x=i: show_details(x))
            )))
        page.update()

    search_tf.on_submit = search
    content_column.controls = [ft.Text("Consulta", size=20, weight="bold"), search_tf, res_col]
    page.update()

# --- CORRECCIÓN (DATA INTEGRITY) ---
def build_correction_view(page, content_column, current_user):
    if current_user["role"] not in ["ADMIN", "CALIDAD"]:
        content_column.controls = [ft.Text("Acceso Denegado")]
        page.update()
        return

    tf_search = ft.TextField(label="Buscar Lote a Corregir", suffix_icon=ft.Icons.SEARCH)
    col_res = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    def open_correct_dialog(data):
        # data: [id, name, lot, vendor, mfg, qty, exp, status, mat_id]
        item_id = data[0]
        
        # Campos Editables
        tf_ven = ft.TextField(label="Lote Prov", value=data[3])
        tf_mfg = ft.TextField(label="Fabricante", value=data[4])
        tf_qty = ft.TextField(label="Cantidad", value=str(data[5]))
        tf_exp = ft.TextField(label="Caducidad", value=str(data[6]))
        tf_reason = ft.TextField(label="MOTIVO (ALCOA)", multiline=True, border_color=ft.Colors.RED)

        def save_correction(e):
            if not tf_reason.value or len(tf_reason.value) < 5:
                tf_reason.error_text = "Motivo obligatorio"
                page.update()
                return
            
            try:
                db.execute_query("UPDATE inventory SET lot_vendor=%s, manufacturer=%s, quantity=%s, expiry_date=%s WHERE id=%s",
                                 (tf_ven.value, tf_mfg.value, float(tf_qty.value), tf_exp.value, item_id))
                
                log_audit(current_user["name"], "DATA_CORRECTION", f"Lote {data[2]} corregido. Motivo: {tf_reason.value}")
                page.dialog.open = False
                page.snack_bar = ft.SnackBar(ft.Text("Corrección guardada"))
                page.snack_bar.open = True
                page.update()
            except Exception as ex:
                logger.error(ex)

        page.dialog = ft.AlertDialog(
            title=ft.Text(f"Corregir: {data[2]}"),
            content=ft.Column([tf_ven, tf_mfg, tf_qty, tf_exp, ft.Divider(), tf_reason], tight=True),
            actions=[ft.ElevatedButton("Confirmar", on_click=save_correction, bgcolor=ft.Colors.RED, color=ft.Colors.WHITE)]
        )
        page.dialog.open = True
        page.update()

    def search(e):
        t = f"%{tf_search.value}%"
        # Query corregido
        rows = db.execute_query("""
            SELECT i.id, m.name, i.lot_internal, i.lot_vendor, i.manufacturer, i.quantity, i.expiry_date, i.status, i.material_id 
            FROM inventory i JOIN materials m ON i.material_id = m.id 
            WHERE i.lot_internal ILIKE %s OR m.name ILIKE %s
        """, (t, t), fetch=True) or []
        
        col_res.controls.clear()
        for r in rows:
            col_res.controls.append(ft.Card(content=ft.ListTile(
                title=ft.Text(r[1]), subtitle=ft.Text(r[2]),
                trailing=ft.IconButton(ft.Icons.EDIT, on_click=lambda e, x=r: open_correct_dialog(x))
            )))
        page.update()

    tf_search.on_submit = search
    content_column.controls = [ft.Text("Corrección de Datos", size=20, weight="bold"), tf_search, col_res]
    page.update()
# --- USUARIOS ---
def build_users_view(page, content_column, current_user):
    if current_user["role"] != "ADMIN":
        content_column.controls = [ft.Text("Acceso Denegado")]
        page.update()
        return

    users_list = ft.Column()
    
    def render():
        users_list.controls.clear()
        data = db.execute_query("SELECT id, username, role, is_locked FROM users", fetch=True) or []
        for u in data:
            icon = ft.Icons.BLOCK if u[3] else ft.Icons.VERIFIED_USER
            color = ft.Colors.GREY if u[3] else ft.Colors.BLUE
            
            def toggle_lock(e, uid=u[0], locked=u[3]):
                new_lock = not locked
                db.execute_query("UPDATE users SET is_locked=%s WHERE id=%s", (new_lock, uid))
                render()

            users_list.controls.append(ft.ListTile(
                leading=ft.Icon(icon, color=color), 
                title=ft.Text(u[1]), 
                subtitle=ft.Text(u[2]),
                trailing=ft.IconButton(ft.Icons.LOCK_OPEN if u[3] else ft.Icons.LOCK, on_click=lambda e, x=u[0], y=u[3]: toggle_lock(e, x, y))
            ))
        page.update()

    def add_user(e):
        tf_u = ft.TextField(label="User")
        tf_p = ft.TextField(label="Pass")
        dd_r = ft.Dropdown(label="Rol", options=[
            ft.dropdown.Option("OPERADOR"), 
            ft.dropdown.Option("ALMACEN"), 
            ft.dropdown.Option("CALIDAD"), 
            ft.dropdown.Option("ADMIN")
        ])
        
        def save(e):
            try:
                db.execute_query("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", (tf_u.value, tf_p.value, dd_r.value))
                page.dialog.open = False
                render()
            except:
                page.snack_bar = ft.SnackBar(ft.Text("Error creando usuario"))
                page.snack_bar.open = True
                page.update()
        
        page.dialog = ft.AlertDialog(title=ft.Text("Nuevo Usuario"), content=ft.Column([tf_u, tf_p, dd_r], tight=True), actions=[ft.ElevatedButton("Crear", on_click=save)])
        page.dialog.open = True
        page.update()

    render()
    content_column.controls = [ft.Text("Usuarios", size=20, weight="bold"), ft.ElevatedButton("Nuevo", on_click=add_user), users_list]
    page.update()

# --- ADMIN ---
def build_audit_view(page, content_column, current_user):
    logs = db.execute_query("SELECT timestamp, user_name, action, details FROM audit_trail ORDER BY id DESC LIMIT 50", fetch=True) or []
    lv = ft.ListView(expand=True)
    for l in logs:
        lv.controls.append(ft.Text(f"{l[0]} | {l[1]}: {l[2]} - {l[3]}", size=12))
    content_column.controls = [ft.Text("Audit Trail", size=20), lv]
    page.update()

# --- MAIN NAVIGATION ---
MODULES_MAP = {
    "CATALOGO": {"icon": ft.Icons.BOOK, "label": "Catálogo", "func": build_catalog_view},
    "ALMACEN": {"icon": ft.Icons.INVENTORY, "label": "Almacén", "func": build_inventory_view},
    "MUESTREO": {"icon": ft.Icons.SCIENCE, "label": "Muestreo", "func": build_sampling_view},
    "LAB": {"icon": ft.Icons.ASSIGNMENT, "label": "Lab", "func": build_lab_view},
    "CONSULTA": {"icon": ft.Icons.SEARCH, "label": "Consulta", "func": build_query_view},
    "CORRECCION": {"icon": ft.Icons.EDIT_DOCUMENT, "label": "Corregir", "func": build_correction_view},
    "USUARIOS": {"icon": ft.Icons.PEOPLE, "label": "Usuarios", "func": build_users_view},
    "ADMIN": {"icon": ft.Icons.SECURITY, "label": "Admin", "func": build_audit_view},
}

ROLE_PERMISSIONS = {
    "ADMIN": ["CATALOGO", "ALMACEN", "MUESTREO", "LAB", "CONSULTA", "CORRECCION", "USUARIOS", "ADMIN"],
    "CALIDAD": ["CATALOGO", "MUESTREO", "LAB", "CONSULTA", "CORRECCION"],
    "ALMACEN": ["ALMACEN", "CONSULTA"],
    "OPERADOR": ["ALMACEN"]
}

def main(page: ft.Page):
    page.title = "MASTER MP"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.ADAPTIVE
    
    content_col = ft.Column(expand=True)
    nav_bar = ft.NavigationBar(visible=False)
    
    def login(e):
        u = user_tf.value
        p = pass_tf.value
        res = db.execute_query("SELECT id, username, role, is_locked FROM users WHERE username=%s AND password=%s", (u, p), fetch=True)
        
        if res:
            if res[0][3]: # is_locked
                page.snack_bar = ft.SnackBar(ft.Text("Usuario Bloqueado"))
                page.snack_bar.open = True
                page.update()
                return

            current_user["id"] = res[0][0]
            current_user["name"] = res[0][1]
            current_user["role"] = res[0][2]
            
            # Configurar menu
            allowed = ROLE_PERMISSIONS.get(current_user["role"], [])
            
            # --- CAMBIO IMPORTANTE FLET MODERNO ---
            # Usamos ft.NavigationBarDestination en lugar de NavigationDestination
            nav_bar.destinations = [
                ft.NavigationBarDestination(icon=MODULES_MAP[k]["icon"], label=MODULES_MAP[k]["label"]) 
                for k in allowed if k in MODULES_MAP
            ]
            
            current_mods = [k for k in allowed if k in MODULES_MAP]
            
            def nav_change(e):
                idx = e.control.selected_index
                if idx < len(current_mods):
                    mod = current_mods[idx]
                    content_col.controls.clear()
                    MODULES_MAP[mod]["func"](page, content_col, current_user)
                    page.update()

            nav_bar.on_change = nav_change
            nav_bar.visible = True
            
            page.clean()
            page.add(content_col)
            page.navigation_bar = nav_bar
            # Cargar primer modulo
            if current_mods:
                MODULES_MAP[current_mods[0]]["func"](page, content_col, current_user)
            page.update()
        else:
            page.snack_bar = ft.SnackBar(ft.Text("Error Login"))
            page.snack_bar.open = True
            page.update()

    user_tf = ft.TextField(label="Usuario")
    pass_tf = ft.TextField(label="Password", password=True)
    
    page.add(ft.Column([
        ft.Icon(ft.Icons.LOCAL_PHARMACY, size=60, color=ft.Colors.BLUE),
        ft.Text("MASTER MP", size=30, weight="bold"),
        user_tf, pass_tf, 
        ft.ElevatedButton("Entrar", on_click=login)
    ], alignment=ft.MainAxisAlignment.CENTER, expand=True))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=port, host="0.0.0.0")

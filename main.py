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

# --- CONFIGURACIÓN ---
# Aumentar limite de recursividad para interfaces complejas
sys.setrecursionlimit(2000)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Usuario global
current_user = {"id": None, "name": "GUEST", "role": "GUEST"}

# --- BASE DE DATOS ---
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:MPMASTER57667115@db.rhuudiwamxpfkinpgkzs.supabase.co:5432/postgres")

class DBManager:
    def __init__(self):
        try:
            self.init_db()
        except Exception as e:
            logger.error(f"Error inicializando DB: {e}")

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

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                for cmd in commands:
                    cur.execute(cmd)
                cur.execute(create_admin)
                conn.commit()

db = DBManager()

# --- UTILERIAS ---
def log_audit(user, action, details):
    db.execute_query("INSERT INTO audit_trail (user_name, action, details) VALUES (%s, %s, %s)", (user, action, details))

# --- FUNCIÓN PDF ---
def open_pdf_in_browser(page, filename, content_dict, test_results):
    print(f"Generando PDF: {filename}")
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        
        def clean(txt): 
            return str(txt).encode('latin-1', 'replace').decode('latin-1')

        pdf.cell(0, 10, text=clean("CERTIFICADO DE ANALISIS"), new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.set_font("Helvetica", size=10)
        pdf.ln(5)

        for key, value in content_dict.items():
            if key not in ["Observaciones", "Conclusión"]:
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(50, 8, text=clean(f"{key}:"), border=0)
                pdf.set_font("Helvetica", size=10)
                pdf.cell(0, 8, text=clean(value), new_x="LMARGIN", new_y="NEXT", border=0)

        if "Conclusión" in content_dict:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(50, 8, text="Dictamen:", border=0)
            pdf.set_font("Helvetica", size=10)
            pdf.cell(0, 8, text=clean(content_dict["Conclusión"]), new_x="LMARGIN", new_y="NEXT", border=0)

        pdf.ln(5)
        
        # Tabla
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(60, 8, text=clean("Prueba"), border=1, fill=True)
        pdf.cell(70, 8, text=clean("Especificación"), border=1, fill=True)
        pdf.cell(60, 8, text=clean("Resultado"), border=1, new_x="LMARGIN", new_y="NEXT", fill=True)

        pdf.set_font("Helvetica", size=10)
        for test in test_results:
            pdf.cell(60, 8, text=clean(test.get('test', '')), border=1)
            pdf.cell(70, 8, text=clean(test.get('spec', '')), border=1)
            pdf.cell(60, 8, text=clean(test.get('result', '')), border=1, new_x="LMARGIN", new_y="NEXT")

        pdf.ln(10)
        if "Observaciones" in content_dict and content_dict["Observaciones"]:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 8, text=clean("Observaciones Adicionales:"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
            pdf.multi_cell(0, 6, text=clean(content_dict["Observaciones"]))

        # --- GENERACIÓN DE BYTES Y DESCARGA (COMPATIBLE) ---
        raw_output = pdf.output() 
        if isinstance(raw_output, str):
            pdf_bytes = raw_output.encode('latin-1')
        else:
            pdf_bytes = raw_output

        b64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
        page.launch_url(f"data:application/pdf;base64,{b64_pdf}")
        return True

    except Exception as e:
        logger.error(f"Error generando PDF: {e}")
        return False

# --- VISTAS ---

def build_catalog_view(page, content_column, current_user):
    tab_content = ft.Column(expand=True)

    def render_content(index):
        tab_content.controls.clear()
        if index == 0:
            materials = db.execute_query("SELECT id, code, name, is_active FROM materials ORDER BY id DESC", fetch=True) or []
            for m in materials:
               tab_content.controls.append(ft.Card(content=ft.ListTile(
                   leading=ft.Icon(ft.Icons.CIRCLE, color=ft.Colors.GREEN if m[3] else ft.Colors.RED),
                   title=ft.Text(f"{m[1]} - {m[2]}"),
                   trailing=ft.IconButton(ft.Icons.SETTINGS, on_click=lambda e, x=m[0], y=m[2]: open_profile_dialog(page, x, y))
                )))
            tab_content.controls.insert(0, ft.ElevatedButton("Nueva Materia Prima", icon=ft.Icons.ADD, on_click=lambda e: add_material_dialog(page, content_column, current_user)))
        
        elif index == 1:
            tests = db.execute_query("SELECT id, name, method FROM standard_tests ORDER BY name", fetch=True) or []
            for t in tests:
               tab_content.controls.append(ft.ListTile(title=ft.Text(t[1]), subtitle=ft.Text(f"Método: {t[2]}"), leading=ft.Icon(ft.Icons.CHECK_BOX)))
            tab_content.controls.insert(0, ft.ElevatedButton("Nueva Prueba Estándar", icon=ft.Icons.ADD, on_click=lambda e: add_test_dialog(page, content_column, current_user)))
        page.update()

    tabs = ft.Tabs(selected_index=0, on_change=lambda e: render_content(e.control.selected_index), tabs=[
        ft.Tab(text="Materias Primas", icon=ft.Icons.LAYERS),
        ft.Tab(text="Pruebas Master", icon=ft.Icons.LIST_ALT)
    ])
    content_column.controls = [ft.Text("Catálogos", size=20, weight="bold"), tabs, tab_content]
    render_content(0)
    page.update()

def open_profile_dialog(page, mat_id, mat_name):
    list_col = ft.Column(height=200, scroll=ft.ScrollMode.ALWAYS)
    
    def refresh():
        rows = db.execute_query("SELECT mp.id, st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id = st.id WHERE mp.material_id=%s", (mat_id,), fetch=True) or []
        list_col.controls = [ft.ListTile(title=ft.Text(r[1]), subtitle=ft.Text(f"Spec: {r[2]}"), trailing=ft.IconButton(ft.Icons.DELETE, icon_color="red", on_click=lambda e, x=r[0]: delete_item(x))) for r in rows]
        page.update()

    def delete_item(pid):
        db.execute_query("DELETE FROM material_profile WHERE id=%s", (pid,))
        refresh()

    all_tests = db.execute_query("SELECT id, name FROM standard_tests", fetch=True) or []
    dd = ft.Dropdown(label="Prueba", options=[ft.dropdown.Option(str(t[0]), t[1]) for t in all_tests], expand=True)
    tf = ft.TextField(label="Especificación", expand=True)

    def add(e):
        if dd.value and tf.value:
            db.execute_query("INSERT INTO material_profile (material_id, test_id, specification) VALUES (%s, %s, %s)", (mat_id, dd.value, tf.value))
            tf.value = ""
            refresh()

    refresh()
    dlg = ft.AlertDialog(title=ft.Text(f"Perfil: {mat_name}"), content=ft.Column([ft.Row([dd, tf]), ft.ElevatedButton("Agregar", on_click=add), ft.Divider(), list_col], tight=True))
    page.open(dlg)

def add_material_dialog(page, col, user):
    c, n = ft.TextField(label="Código"), ft.TextField(label="Nombre")
    cat = ft.Dropdown(label="Categoría", options=[ft.dropdown.Option("API"), ft.dropdown.Option("EXCIPIENTE")])
    
    def save(e):
        if c.value and n.value:
           db.execute_query("INSERT INTO materials (code, name, category) VALUES (%s, %s, %s)", (c.value, n.value, cat.value))
           page.close(dlg)
           build_catalog_view(page, col, user)
           page.update()
           
    dlg = ft.AlertDialog(title=ft.Text("Nuevo Material"), content=ft.Column([c, n, cat], tight=True), actions=[ft.ElevatedButton("Guardar", on_click=save)])
    page.open(dlg)

def add_test_dialog(page, col, user):
    n, m = ft.TextField(label="Nombre"), ft.TextField(label="Método")
    def save(e):
        if n.value:
           db.execute_query("INSERT INTO standard_tests (name, method) VALUES (%s, %s)", (n.value, m.value))
           page.close(dlg)
           build_catalog_view(page, col, user)
           page.update()
           
    dlg = ft.AlertDialog(title=ft.Text("Nueva Prueba"), content=ft.Column([n, m], tight=True), actions=[ft.ElevatedButton("Guardar", on_click=save)])
    page.open(dlg)

def build_inventory_view(page, content_column, current_user):
    mats = db.execute_query("SELECT id, name, code FROM materials WHERE is_active=TRUE ORDER BY name", fetch=True) or []
    mat_opts = [ft.dropdown.Option(str(m[0]), f"{m[1]} ({m[2]})") for m in mats]
    
    dd_mat = ft.Dropdown(label="Material", options=mat_opts, expand=True)
    tf_li, tf_lv = ft.TextField(label="Lote Interno", expand=True), ft.TextField(label="Lote Prov", expand=True)
    tf_mfg, tf_qty = ft.TextField(label="Fabricante", expand=True), ft.TextField(label="Cantidad (Kg)", expand=True)
    tf_exp = ft.TextField(label="Caducidad (YYYY-MM-DD)", expand=True)

    def save(e):
        if dd_mat.value and tf_li.value and tf_qty.value:
            try:
               db.execute_query("INSERT INTO inventory (material_id, lot_internal, lot_vendor, manufacturer, expiry_date, quantity, status) VALUES (%s, %s, %s, %s, %s, %s, 'CUARENTENA')",
                                (dd_mat.value, tf_li.value, tf_lv.value, tf_mfg.value, tf_exp.value, float(tf_qty.value)))
               log_audit(current_user["name"], "RECEIPT", f"Ingreso {tf_li.value}")
               page.snack_bar = ft.SnackBar(ft.Text("Guardado"))
               page.snack_bar.open = True
               tf_li.value = ""
               page.update()
            except Exception as ex:
                logger.error(ex)
    
    content_column.controls = [ft.Text("Recepción", size=20, weight="bold"), dd_mat, ft.Row([tf_li, tf_lv]), ft.Row([tf_mfg, tf_qty]), tf_exp, ft.ElevatedButton("Ingresar", icon=ft.Icons.SAVE, on_click=save)]
    page.update()

def build_sampling_view(page, content_column, current_user):
    items = db.execute_query("SELECT i.id, m.name, i.lot_internal, i.quantity FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='CUARENTENA'", fetch=True) or []
    lv = ft.ListView(expand=True, spacing=10)

    def open_sam(iid, name, lot, qty):
        tf_n = ft.TextField(label="Envases Totales (N)", on_change=lambda e: update_calc(e.control.value))
        txt_res = ft.Text("Muestrear: 0")
        tf_rem = ft.TextField(label="Retirado (Kg)", value="0")
        
        def update_calc(val):
            try:
                if val: txt_res.value = f"Muestrear: {math.ceil(math.sqrt(int(val)) + 1)}"
                page.update()
            except: pass

        def confirm(e):
            try:
                rem = float(tf_rem.value)
                new_q = qty - rem
                db.execute_query("UPDATE inventory SET quantity=%s, status='MUESTREADO' WHERE id=%s", (new_q, iid))
                log_audit(current_user["name"], "SAMPLING", f"Muestreo {lot}")
                page.close(dlg)
                build_sampling_view(page, content_column, current_user)
                page.update()
            except: pass

        dlg = ft.AlertDialog(title=ft.Text(f"Muestreo: {lot}"), content=ft.Column([ft.Text(f"Stock: {qty}"), tf_n, txt_res, tf_rem], tight=True), actions=[ft.ElevatedButton("Confirmar", on_click=confirm)])
        page.open(dlg)

    for i in items:
       lv.controls.append(ft.Card(content=ft.ListTile(title=ft.Text(i[1]), subtitle=ft.Text(f"Lote: {i[2]} | Stock: {i[3]}"), leading=ft.Icon(ft.Icons.SCIENCE, color="orange"), trailing=ft.IconButton(ft.Icons.ARROW_FORWARD, on_click=lambda e, x=i: open_sam(x[0], x[1], x[2], x[3])))))
    
    content_column.controls = [ft.Text("Muestreo", size=20, weight="bold"), lv]
    page.update()

def build_lab_view(page, content_column, current_user):
    pending = db.execute_query("SELECT i.id, m.name, i.lot_internal, i.material_id FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='MUESTREADO'", fetch=True) or []
    lv = ft.ListView(expand=True, spacing=10)

    def open_lab(iid, mat_id, name, lot):
        prof = db.execute_query("SELECT st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id=st.id WHERE mp.material_id=%s", (mat_id,), fetch=True) or []
        if not prof: 
            page.snack_bar = ft.SnackBar(ft.Text("Sin perfil de pruebas")); page.snack_bar.open=True; page.update(); return

        inputs = [ft.TextField(label=f"{p[0]} ({p[1]})", data={"k": p[0], "s": p[1]}) for p in prof]
        tf_an = ft.TextField(label="No. Análisis")
        dd_dec = ft.Dropdown(label="Dictamen", options=[ft.dropdown.Option("APROBADO"), ft.dropdown.Option("RECHAZADO")])
        
        def save(e):
            if dd_dec.value and tf_an.value:
                res_json = {i.data['k']: i.value for i in inputs}
                res_list = [{"test": i.data['k'], "spec": i.data['s'], "result": i.value} for i in inputs]
                db.execute_query("INSERT INTO lab_results (inventory_id, analyst, result_data, conclusion, analysis_num) VALUES (%s, %s, %s, %s, %s)",
                                 (iid, current_user["name"], json.dumps(res_json), dd_dec.value, tf_an.value))
                st = "LIBERADO" if dd_dec.value == "APROBADO" else "RECHAZADO"
                db.execute_query("UPDATE inventory SET status=%s WHERE id=%s", (st, iid))
                
                open_pdf_in_browser(page, f"CoA_{lot}.pdf", {"Producto": name, "Lote": lot, "Conclusión": dd_dec.value}, res_list)
                
                page.close(dlg)
                build_lab_view(page, content_column, current_user)
                page.update()

        dlg = ft.AlertDialog(title=ft.Text(f"Análisis {lot}"), content=ft.Column([tf_an] + inputs + [dd_dec], tight=True, scroll=ft.ScrollMode.ALWAYS, height=400), actions=[ft.ElevatedButton("Guardar", on_click=save)])
        page.open(dlg)

    for p in pending:
       lv.controls.append(ft.Card(content=ft.ListTile(title=ft.Text(p[1]), subtitle=ft.Text(p[2]), trailing=ft.IconButton(ft.Icons.PLAY_ARROW, on_click=lambda e, x=p: open_lab(x[0], x[3], x[1], x[2])))))
    
    content_column.controls = [ft.Text("Laboratorio", size=20, weight="bold"), lv]
    page.update()

# --- NUEVO MÓDULO: CORRECCIÓN ALCOA ---
def build_edition_view(page, content_column, current_user):
    # Verificación de Rol
    if current_user["role"] not in ["ADMIN", "CALIDAD"]:
        content_column.controls = [ft.Text("Acceso Restringido: Requiere rol ADMIN o CALIDAD", color="red", size=20, weight="bold")]
        page.update()
        return

    tf_search = ft.TextField(label="Buscar Lote para Corregir", suffix_icon=ft.Icons.SEARCH)
    results_col = ft.Column()

    def edit_record(item):
        # item: [id, material_name, lot_internal, lot_vendor, quantity, expiry_date]
        iid = item[0]
        
        # Campos de edición (Almacén y Datos Críticos)
        tf_qty = ft.TextField(label="Cantidad (Kg)", value=str(item[4]))
        tf_lot_v = ft.TextField(label="Lote Proveedor", value=str(item[3]))
        tf_exp = ft.TextField(label="Caducidad (YYYY-MM-DD)", value=str(item[5]))
        
        # CAMPO OBLIGATORIO ALCOA
        tf_reason = ft.TextField(
            label="Justificación del Cambio (Requerido para ALCOA)", 
            multiline=True, 
            icon=ft.Icons.WARNING,
            helper_text="Explique detalladamente por qué se modifica el registro original."
        )
        
        def save_changes(e):
            # Validación ALCOA: Sin justificación no hay cambio
            if not tf_reason.value or len(tf_reason.value) < 5:
                page.snack_bar = ft.SnackBar(ft.Text("⚠️ ALCOA: Debe ingresar una justificación válida."))
                page.snack_bar.open = True
                page.update()
                return

            try:
                # Detectar cambios para el Audit Trail
                changes = []
                if float(tf_qty.value) != float(item[4]): changes.append(f"Qty: {item[4]} -> {tf_qty.value}")
                if tf_lot_v.value != str(item[3]): changes.append(f"LotV: {item[3]} -> {tf_lot_v.value}")
                if tf_exp.value != str(item[5]): changes.append(f"Exp: {item[5]} -> {tf_exp.value}")

                if not changes:
                    page.close(dlg); return

                # Update Seguro
                db.execute_query(
                    "UPDATE inventory SET quantity=%s, lot_vendor=%s, expiry_date=%s WHERE id=%s",
                    (float(tf_qty.value), tf_lot_v.value, tf_exp.value, iid)
                )
                
                # Registro ALCOA en Audit Trail
                log_details = f"CORRECCION DATOS | {'; '.join(changes)} | Justificación: {tf_reason.value}"
                log_audit(current_user["name"], "EDIT_RECORD", log_details)
                
                page.snack_bar = ft.SnackBar(ft.Text("✅ Registro corregido y auditado."), bgcolor="green")
                page.snack_bar.open = True
                page.close(dlg)
                search_lot(None) # Refrescar lista
                page.update()

            except Exception as ex:
                logger.error(f"Error edit: {ex}")
                page.snack_bar = ft.SnackBar(ft.Text("Error al guardar corrección"))
                page.snack_bar.open = True
                page.update()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Corregir Lote: {item[2]}"),
            content=ft.Column([
                ft.Text("Modifique solo los datos erróneos:", size=12),
                tf_qty, tf_lot_v, tf_exp,
                ft.Divider(),
                tf_reason
            ], tight=True),
            actions=[
                ft.ElevatedButton("Cancelar", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton("Guardar Corrección", on_click=save_changes, bgcolor=ft.Colors.RED, color=ft.Colors.WHITE)
            ]
        )
        page.open(dlg)

    def search_lot(e):
        term = f"%{tf_search.value}%"
        # Buscamos datos generales de inventario
        rows = db.execute_query(
            "SELECT i.id, m.name, i.lot_internal, i.lot_vendor, i.quantity, i.expiry_date FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.lot_internal ILIKE %s", 
            (term,), fetch=True
        ) or []
        
        results_col.controls.clear()
        if not rows:
            results_col.controls.append(ft.Text("No se encontró el lote."))
        
        for r in rows:
            results_col.controls.append(ft.Card(content=ft.ListTile(
                leading=ft.Icon(ft.Icons.EDIT, color="orange"),
                title=ft.Text(f"{r[1]} ({r[2]})"),
                subtitle=ft.Text(f"Qty: {r[4]} | Exp: {r[5]}"),
                trailing=ft.ElevatedButton("Corregir", on_click=lambda e, x=r: edit_record(x))
            )))
        page.update()

    tf_search.on_submit = search_lot
    content_column.controls = [
        ft.Text("Corrección de Registros (ALCOA)", size=20, weight="bold", color="red"),
        ft.Text("Todos los cambios son auditados. Ingrese motivo.", size=12, italic=True),
        tf_search,
        results_col
    ]
    page.update()

def build_query_view(page, content_column, current_user):
    tf_s = ft.TextField(label="Buscar por Lote o Nombre", suffix_icon=ft.Icons.SEARCH)
    col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    def show_details(data):
        item_id = data[0]
        try:
            inv_rows = db.execute_query("SELECT manufacturer, lot_vendor, expiry_date, quantity FROM inventory WHERE id=%s", (item_id,), fetch=True)
            inv = inv_rows[0] if inv_rows else ["N/A", "N/A", "N/A", 0]
            
            lab = db.execute_query("SELECT analysis_num, conclusion, result_data, observations FROM lab_results WHERE inventory_id=%s", (item_id,), fetch=True)
            
            info = [
               ft.Text(f"Producto: {data[1]}", weight="bold", size=16),
               ft.Text(f"Lote Interno: {data[2]}", color=ft.Colors.BLUE, weight="bold"),
               ft.Divider(),
               ft.Text(f"Fabricante: {inv[0]}"),
               ft.Text(f"Lote Prov: {inv[1]}"),
               ft.Text(f"Caducidad: {inv[2]}"),
               ft.Text(f"Cantidad: {inv[3]} kg"),
               ft.Divider()
            ]

            if lab:
                l_res = lab[0]
                info.append(ft.Text(f"Análisis: {l_res[0]}", weight="bold"))
                info.append(ft.Text(f"Dictamen: {l_res[1]}", color=ft.Colors.GREEN if l_res[1]=="APROBADO" else ft.Colors.RED, weight="bold"))
                
                try:
                    res_json = l_res[2] if isinstance(l_res[2], dict) else json.loads(l_res[2])
                    dt = ft.DataTable(columns=[ft.DataColumn(ft.Text("Prueba")), ft.DataColumn(ft.Text("Resultado"))], rows=[])
                    for k,v in res_json.items():
                       dt.rows.append(ft.DataRow(cells=[ft.DataCell(ft.Text(str(k))), ft.DataCell(ft.Text(str(v)))]))
                    info.append(dt)
                    
                    res_list = [{"test": k, "spec": "-", "result": str(v)} for k,v in res_json.items()]
                except:
                    res_list = []

                if l_res[3]: info.append(ft.Text(f"Obs: {l_res[3]}", italic=True))

                def print_pdf(e):
                    content = {"Producto": data[1], "Lote": data[2], "Conclusión": l_res[1], "Observaciones": l_res[3]}
                    if open_pdf_in_browser(page, f"Cert_{data[2]}.pdf", content, res_list):
                        page.snack_bar = ft.SnackBar(ft.Text("Descargando PDF..."))
                        page.snack_bar.open = True
                        page.update()

                info.append(ft.ElevatedButton("Descargar Certificado", icon=ft.Icons.PICTURE_AS_PDF, bgcolor=ft.Colors.GREEN, color=ft.Colors.WHITE, on_click=print_pdf))
            else:
                info.append(ft.Text("⚠️ Sin análisis de laboratorio", color=ft.Colors.ORANGE))

            dlg = ft.AlertDialog(title=ft.Text("Detalle"), content=ft.Column(info, tight=True, scroll=ft.ScrollMode.ALWAYS, height=450), actions=[ft.TextButton("Cerrar", on_click=lambda e: page.close(dlg))])
            page.open(dlg)

        except Exception as ex:
            logger.error(f"Error detalle: {ex}")

    def search(e):
        t = f"%{tf_s.value}%"
        rows = db.execute_query("SELECT i.id, m.name, i.lot_internal, i.status FROM inventory i JOIN materials m ON i.material_id=m.id WHERE m.name ILIKE %s OR i.lot_internal ILIKE %s", (t, t), fetch=True) or []
        
        col.controls.clear()
        if not rows:
           col.controls.append(ft.Text("No se encontraron resultados."))

        for r in rows:
           col.controls.append(ft.Card(content=ft.ListTile(
               title=ft.Text(r[1]), 
               subtitle=ft.Text(f"{r[2]} - {r[3]}"), 
               leading=ft.Icon(ft.Icons.CIRCLE, color=ft.Colors.GREEN if r[3]=="LIBERADO" else ft.Colors.ORANGE),
               trailing=ft.IconButton(ft.Icons.VISIBILITY, tooltip="Ver Detalle", on_click=lambda e, x=r: show_details(x))
            )))
        page.update()
    
    tf_s.on_submit = search
    content_column.controls = [ft.Text("Consulta", size=20, weight="bold"), tf_s, col]
    page.update()

def build_users_view(page, content_column, current_user):
    if current_user["role"] != "ADMIN": content_column.controls=[ft.Text("Acceso Denegado")]; page.update(); return
    
    lst = ft.Column()
    def render():
        rows = db.execute_query("SELECT username, role FROM users", fetch=True) or []
        lst.controls = [ft.ListTile(title=ft.Text(r[0]), subtitle=ft.Text(r[1]), leading=ft.Icon(ft.Icons.PERSON)) for r in rows]
        page.update()
    
    def add(e):
        u, p, r = ft.TextField(label="User"), ft.TextField(label="Pass"), ft.Dropdown(options=[ft.dropdown.Option("OPERADOR"), ft.dropdown.Option("ADMIN"), ft.dropdown.Option("CALIDAD")])
        def save(e):
            db.execute_query("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", (u.value, p.value, r.value)); page.close(dlg); render()
        dlg = ft.AlertDialog(content=ft.Column([u,p,r], tight=True), actions=[ft.ElevatedButton("Crear", on_click=save)])
        page.open(dlg)

    render()
    content_column.controls = [ft.Text("Usuarios", size=20, weight="bold"), ft.ElevatedButton("Nuevo", on_click=add), lst]
    page.update()

def build_audit_view(page, content_column, current_user):
    rows = db.execute_query("SELECT timestamp, user_name, action, details FROM audit_trail ORDER BY id DESC LIMIT 50", fetch=True) or []
    lv = ft.ListView(expand=True, controls=[ft.Text(f"{r[0]} | {r[1]}: {r[2]} - {r[3]}") for r in rows])
    content_column.controls = [ft.Text("Audit Trail", size=20), lv]
    page.update()

# --- MAIN ---
MODULES = {
    "CATALOGO": {"icon": ft.Icons.BOOK, "label": "Catálogo", "func": build_catalog_view},
    "ALMACEN": {"icon": ft.Icons.INVENTORY, "label": "Almacén", "func": build_inventory_view},
    "MUESTREO": {"icon": ft.Icons.SCIENCE, "label": "Muestreo", "func": build_sampling_view},
    "LAB": {"icon": ft.Icons.ASSIGNMENT, "label": "Lab", "func": build_lab_view},
    "CONSULTA": {"icon": ft.Icons.SEARCH, "label": "Consulta", "func": build_query_view},
    "CORRECCION": {"icon": ft.Icons.EDIT, "label": "Corrección", "func": build_edition_view},
    "USUARIOS": {"icon": ft.Icons.PEOPLE, "label": "Usuarios", "func": build_users_view},
    "ADMIN": {"icon": ft.Icons.SECURITY, "label": "Admin", "func": build_audit_view},
}

PERMS = {
    "ADMIN": list(MODULES.keys()),
    "CALIDAD": ["CATALOGO", "MUESTREO", "LAB", "CONSULTA", "CORRECCION"],
    "ALMACEN": ["ALMACEN", "CONSULTA"],
    "OPERADOR": ["ALMACEN"]
}

def main(page: ft.Page):
    page.title = "MASTER MP"
    page.scroll = ft.ScrollMode.ADAPTIVE
    col = ft.Column(expand=True)
    nav = ft.NavigationBar(visible=False)

    def login(e):
        res = db.execute_query("SELECT id, username, role FROM users WHERE username=%s AND password=%s", (user_tf.value, pass_tf.value), fetch=True)
        if res:
            current_user.update({"id": res[0][0], "name": res[0][1], "role": res[0][2]})
            allowed = PERMS.get(current_user["role"], [])
            
            nav.destinations = [ft.NavigationBarDestination(icon=MODULES[k]["icon"], label=MODULES[k]["label"]) for k in allowed if k in MODULES]
            
            active_mods = [k for k in allowed if k in MODULES]
            def nav_click(e):
                MODULES[active_mods[e.control.selected_index]]["func"](page, col, current_user)
                page.update()
            
            nav.on_change = nav_click
            nav.visible = True
            page.clean(); page.add(col); page.navigation_bar = nav
            if active_mods: MODULES[active_mods[0]]["func"](page, col, current_user)
            page.update()
        else:
            page.snack_bar = ft.SnackBar(ft.Text("Error Login")); page.snack_bar.open=True; page.update()

    user_tf, pass_tf = ft.TextField(label="User"), ft.TextField(label="Pass", password=True)
    page.add(ft.Column([ft.Icon(ft.Icons.LOCAL_PHARMACY, size=60, color="blue"), ft.Text("LOGIN"), user_tf, pass_tf, ft.ElevatedButton("Entrar", on_click=login)], alignment=ft.MainAxisAlignment.CENTER, expand=True))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=port, host="0.0.0.0")


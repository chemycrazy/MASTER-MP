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
            """CREATE TABLE IF NOT EXISTS roles (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL,
                permissions JSONB DEFAULT '[]'
            )""",
            """CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(50) NOT NULL,
                role VARCHAR(50) NOT NULL, 
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
        
        # Insertar Rol ADMIN por defecto si no existe (con acceso a todo)
        # Nota: La lista de módulos debe coincidir con las llaves de MODULES al final del script
        all_modules = ["CATALOGO", "ALMACEN", "MUESTREO", "LAB", "CONSULTA", "CORRECCION", "USUARIOS", "PERFILES", "ADMIN"]
        create_admin_role = """
            INSERT INTO roles (name, permissions)
            VALUES ('ADMIN', %s)
            ON CONFLICT (name) DO NOTHING
        """
        
        create_admin_user = """
            INSERT INTO users (username, password, role)
            VALUES ('admin', 'admin', 'ADMIN')
            ON CONFLICT (username) DO NOTHING
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                for cmd in commands:
                    cur.execute(cmd)
                cur.execute(create_admin_role, (json.dumps(all_modules),))
                cur.execute(create_admin_user)
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
    # Buscamos materiales que están en estado 'MUESTREADO'
    pending = db.execute_query("SELECT i.id, m.name, i.lot_internal, i.material_id FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='MUESTREADO'", fetch=True) or []
    lv = ft.ListView(expand=True, spacing=10)

    def open_lab(iid, mat_id, name, lot):
        # Buscamos el perfil de pruebas (specs)
        prof = db.execute_query("SELECT st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id=st.id WHERE mp.material_id=%s", (mat_id,), fetch=True) or []
        
        if not prof: 
            page.snack_bar = ft.SnackBar(ft.Text("⚠️ Sin perfil de pruebas configurado para este material.")); page.snack_bar.open=True; page.update(); return

        # --- CAMPOS DE RESULTADOS (Dinámicos según perfil) ---
        inputs = [ft.TextField(label=f"{p[0]} ({p[1]})", data={"k": p[0], "s": p[1]}) for p in prof]
        
        # --- CAMPOS FALTANTES AGREGADOS ---
        tf_an = ft.TextField(label="No. Análisis / Reporte")
        tf_bib = ft.TextField(label="Referencia Bibliográfica (Ej: FEUM 13.0)")
        tf_reanal = ft.TextField(label="Fecha Reanálisis (YYYY-MM-DD)", icon=ft.Icons.CALENDAR_MONTH)
        tf_obs = ft.TextField(label="Observaciones Generales", multiline=True)
        
        dd_dec = ft.Dropdown(label="Dictamen Final", options=[ft.dropdown.Option("APROBADO"), ft.dropdown.Option("RECHAZADO")])
        
        def save(e):
            if dd_dec.value and tf_an.value:
                # Recopilar resultados dinámicos
                res_json = {i.data['k']: i.value for i in inputs}
                
                # Lista para el PDF
                res_list = [{"test": i.data['k'], "spec": i.data['s'], "result": i.value} for i in inputs]
                
                try:
                    # --- INSERT CORREGIDO: AHORA INCLUYE LOS CAMPOS FALTANTES ---
                    query = """
                        INSERT INTO lab_results 
                        (inventory_id, analyst, result_data, conclusion, analysis_num, bib_reference, reanalysis_date, observations) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    # Manejo de fecha vacía (para que no falle SQL si el usuario no pone fecha)
                    reanal_val = tf_reanal.value if tf_reanal.value else None

                    db.execute_query(query, (
                        iid, 
                        current_user["name"], # El analista es el usuario actual
                        json.dumps(res_json), 
                        dd_dec.value, 
                        tf_an.value,
                        tf_bib.value,
                        reanal_val,
                        tf_obs.value
                    ))
                    
                    # Actualizar estado del inventario
                    st = "LIBERADO" if dd_dec.value == "APROBADO" else "RECHAZADO"
                    db.execute_query("UPDATE inventory SET status=%s WHERE id=%s", (st, iid))
                    
                    # Log de auditoría
                    log_audit(current_user["name"], "LAB_ANALYSIS", f"Análisis {tf_an.value} para lote {lot} - {dd_dec.value}")
                    
                    # Generar PDF con todos los datos
                    full_content = {
                        "Producto": name, 
                        "Lote": lot, 
                        "Conclusión": dd_dec.value,
                        "Referencia": tf_bib.value,
                        "Reanálisis": tf_reanal.value if tf_reanal.value else "N/A",
                        "Observaciones": tf_obs.value,
                        "Analista": current_user["name"]
                    }
                    
                    open_pdf_in_browser(page, f"CoA_{lot}.pdf", full_content, res_list)
                    
                    page.close(dlg)
                    build_lab_view(page, content_column, current_user)
                    page.snack_bar = ft.SnackBar(ft.Text("Resultados guardados correctamente"), bgcolor="green"); page.snack_bar.open=True
                    page.update()
                
                except Exception as ex:
                    logger.error(f"Error guardando laboratorio: {ex}")
                    page.snack_bar = ft.SnackBar(ft.Text(f"Error al guardar: Verifique formato de fecha (YYYY-MM-DD)")); page.snack_bar.open=True; page.update()
            else:
                page.snack_bar = ft.SnackBar(ft.Text("Campos obligatorios: No. Análisis y Dictamen")); page.snack_bar.open=True; page.update()

        # Diálogo con scroll para que quepan todos los campos
        dlg = ft.AlertDialog(
            title=ft.Text(f"Análisis de Laboratorio: {lot}"),
            content=ft.Column(
                [
                    ft.Text("Resultados de Pruebas:", weight="bold"),
                    *inputs,
                    ft.Divider(),
                    ft.Text("Datos del Informe:", weight="bold"),
                    tf_an,
                    tf_bib, 
                    tf_reanal,
                    tf_obs,
                    dd_dec
                ], 
                tight=True, 
                scroll=ft.ScrollMode.ALWAYS, 
                height=500  # Altura fija para evitar desbordes
            ),
            actions=[ft.ElevatedButton("Guardar y Emitir CoA", on_click=save)]
        )
        page.open(dlg)

    for p in pending:
       lv.controls.append(ft.Card(content=ft.ListTile(
           title=ft.Text(p[1]), 
           subtitle=ft.Text(f"Lote: {p[2]}"), 
           leading=ft.Icon(ft.Icons.SCIENCE, color="blue"), 
           trailing=ft.IconButton(ft.Icons.PLAY_ARROW, on_click=lambda e, x=p: open_lab(x[0], x[3], x[1], x[2]))
        )))
    
    content_column.controls = [ft.Text("Laboratorio - Pendientes", size=20, weight="bold"), lv]
    page.update()

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
        
        # --- 1. DATOS DE ALMACÉN ---
        tf_qty = ft.TextField(label="Cantidad (Kg)", value=str(item[4]))
        tf_lot_v = ft.TextField(label="Lote Proveedor", value=str(item[3]))
        tf_exp = ft.TextField(label="Caducidad (YYYY-MM-DD)", value=str(item[5]))
        
        # --- 2. DATOS DE LABORATORIO ---
        # Agregamos result_data a la consulta
        lab_row = db.execute_query("""
            SELECT id, analysis_num, conclusion, bib_reference, reanalysis_date, observations, result_data 
            FROM lab_results WHERE inventory_id=%s
        """, (iid,), fetch=True)
        
        has_lab = False
        lab_id = None
        orig_results = {}
        result_inputs = {} # Diccionario para guardar los controles de los resultados
        
        # Controles Generales de Lab
        tf_an = ft.TextField(label="No. Análisis")
        dd_dec = ft.Dropdown(label="Dictamen", options=[ft.dropdown.Option("APROBADO"), ft.dropdown.Option("RECHAZADO")])
        tf_bib = ft.TextField(label="Referencia Bibliográfica")
        tf_reanal = ft.TextField(label="Fecha Reanálisis (YYYY-MM-DD)")
        tf_obs = ft.TextField(label="Observaciones Lab", multiline=True)

        # Contenedor visual para los inputs de resultados
        results_container = ft.Column()

        if lab_row:
            has_lab = True
            l_data = lab_row[0] # [id, num, concl, ref, reanal, obs, result_data]
            lab_id = l_data[0]
            
            tf_an.value = str(l_data[1])
            dd_dec.value = str(l_data[2])
            tf_bib.value = str(l_data[3]) if l_data[3] else ""
            tf_reanal.value = str(l_data[4]) if l_data[4] else ""
            tf_obs.value = str(l_data[5]) if l_data[5] else ""
            
            # --- CARGA DINÁMICA DE RESULTADOS ---
            try:
                raw_json = l_data[6]
                if raw_json:
                    orig_results = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
                    
                    results_container.controls.append(ft.Text("Resultados de Pruebas:", weight="bold", size=14))
                    
                    for test_name, test_val in orig_results.items():
                        # Creamos un input para cada prueba
                        tb = ft.TextField(label=test_name, value=str(test_val), border_color=ft.Colors.BLUE_400)
                        result_inputs[test_name] = tb
                        results_container.controls.append(tb)
            except Exception as e:
                logger.error(f"Error parseando JSON: {e}")
                results_container.controls.append(ft.Text("Error cargando resultados detallados", color="red"))

        else:
            tf_an.disabled = True; tf_an.value = "Sin Análisis"
            dd_dec.disabled = True
            tf_bib.disabled = True
            tf_reanal.disabled = True
            tf_obs.disabled = True

        # --- 3. JUSTIFICACIÓN ALCOA ---
        tf_reason = ft.TextField(
            label="Justificación del Cambio (Requerido para ALCOA)", 
            multiline=True, 
            icon=ft.Icons.WARNING,
            helper_text="Explique detalladamente por qué se modifica el registro original."
        )
        
        def save_changes(e):
            if not tf_reason.value or len(tf_reason.value) < 5:
                page.snack_bar = ft.SnackBar(ft.Text("⚠️ ALCOA: Debe ingresar una justificación válida."))
                page.snack_bar.open = True; page.update(); return

            try:
                changes = []
                
                # A) ALMACÉN
                if float(tf_qty.value) != float(item[4]): changes.append(f"Qty: {item[4]} -> {tf_qty.value}")
                if tf_lot_v.value != str(item[3]): changes.append(f"LotV: {item[3]} -> {tf_lot_v.value}")
                if tf_exp.value != str(item[5]): changes.append(f"Exp: {item[5]} -> {tf_exp.value}")

                # B) LABORATORIO (Datos Generales)
                lab_changed = False
                new_results_json = orig_results.copy() # Copia para modificar
                
                if has_lab and lab_row:
                    orig = lab_row[0]
                    if tf_an.value != str(orig[1]): 
                        changes.append(f"Análisis: {orig[1]} -> {tf_an.value}"); lab_changed=True
                    
                    if dd_dec.value != str(orig[2]): 
                        changes.append(f"Dictamen: {orig[2]} -> {dd_dec.value}"); lab_changed=True
                        new_status = "LIBERADO" if dd_dec.value == "APROBADO" else "RECHAZADO"
                        db.execute_query("UPDATE inventory SET status=%s WHERE id=%s", (new_status, iid))
                        changes.append(f"Status Inv: {new_status}")

                    if tf_bib.value != (str(orig[3]) if orig[3] else ""):
                        changes.append(f"Ref: {orig[3]} -> {tf_bib.value}"); lab_changed=True
                        
                    if tf_reanal.value != (str(orig[4]) if orig[4] else ""):
                        changes.append(f"Reanálisis: {orig[4]} -> {tf_reanal.value}"); lab_changed=True

                    if tf_obs.value != (str(orig[5]) if orig[5] else ""):
                        changes.append(f"Obs: {orig[5]} -> {tf_obs.value}"); lab_changed=True
                    
                    # C) LABORATORIO (Resultados Específicos)
                    for t_name, t_input in result_inputs.items():
                        old_val = str(orig_results.get(t_name, ""))
                        new_val = t_input.value
                        if old_val != new_val:
                            changes.append(f"Test '{t_name}': {old_val} -> {new_val}")
                            new_results_json[t_name] = new_val # Actualizamos el diccionario
                            lab_changed = True

                if not changes:
                    page.close(dlg); return

                # --- EJECUCIÓN DE UPDATES ---
                # 1. Update Inventario
                db.execute_query(
                    "UPDATE inventory SET quantity=%s, lot_vendor=%s, expiry_date=%s WHERE id=%s",
                    (float(tf_qty.value), tf_lot_v.value, tf_exp.value, iid)
                )
                
                # 2. Update Lab (incluyendo el JSON nuevo)
                if lab_changed and has_lab:
                    reanal_val = tf_reanal.value if tf_reanal.value else None
                    db.execute_query("""
                        UPDATE lab_results 
                        SET analysis_num=%s, conclusion=%s, bib_reference=%s, reanalysis_date=%s, observations=%s, result_data=%s
                        WHERE id=%s
                    """, (tf_an.value, dd_dec.value, tf_bib.value, reanal_val, tf_obs.value, json.dumps(new_results_json), lab_id))

                # 3. Registro Audit Trail
                log_details = f"CORRECCION DATOS | {'; '.join(changes)} | Justificación: {tf_reason.value}"
                log_audit(current_user["name"], "EDIT_RECORD", log_details)
                
                page.snack_bar = ft.SnackBar(ft.Text("✅ Registro corregido y auditado."), bgcolor="green")
                page.snack_bar.open = True
                page.close(dlg)
                search_lot(None)
                page.update()

            except Exception as ex:
                logger.error(f"Error edit: {ex}")
                page.snack_bar = ft.SnackBar(ft.Text(f"Error al guardar. Verifique datos."))
                page.snack_bar.open = True
                page.update()

        # Contenido del diálogo
        content_dlg = ft.Column([
            ft.Text("Datos de Almacén:", weight="bold", color=ft.Colors.BLUE),
            tf_qty, tf_lot_v, tf_exp,
            ft.Divider(),
            ft.Text("Datos Generales Lab:", weight="bold", color=ft.Colors.BLUE),
            tf_an if has_lab else ft.Text("No aplica"),
            dd_dec if has_lab else ft.Container(),
            tf_bib if has_lab else ft.Container(),
            tf_reanal if has_lab else ft.Container(),
            tf_obs if has_lab else ft.Container(),
            ft.Divider(),
            # Aquí insertamos los campos dinámicos de las pruebas
            results_container if has_lab else ft.Container(), 
            ft.Divider(),
            tf_reason
        ], tight=True, scroll=ft.ScrollMode.ALWAYS, height=500)

        dlg = ft.AlertDialog(
            title=ft.Text(f"Corregir Lote: {item[2]}"),
            content=content_dlg,
            actions=[
                ft.ElevatedButton("Cancelar", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton("Guardar Corrección", on_click=save_changes, bgcolor=ft.Colors.RED, color=ft.Colors.WHITE)
            ]
        )
        page.open(dlg)

    def search_lot(e):
        term = f"%{tf_search.value}%"
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
            # 1. Datos de Inventario
            inv_rows = db.execute_query("SELECT manufacturer, lot_vendor, expiry_date, quantity FROM inventory WHERE id=%s", (item_id,), fetch=True)
            inv = inv_rows[0] if inv_rows else ["N/A", "N/A", "N/A", 0]
            
            # 2. Datos de Laboratorio (CORREGIDO: Ahora traemos todo)
            # Indices: 0:Num, 1:Concl, 2:Data, 3:Obs, 4:Analista, 5:Ref, 6:Reanalisis, 7:FechaAnalisis
            lab = db.execute_query("""
                SELECT analysis_num, conclusion, result_data, observations, 
                       analyst, bib_reference, reanalysis_date, date_analyzed 
                FROM lab_results WHERE inventory_id=%s
            """, (item_id,), fetch=True)
            
            # Cabecera del reporte
            info = [
               ft.Text(f"Producto: {data[1]}", weight="bold", size=18, color=ft.Colors.BLUE_GREY_900),
               ft.Text(f"Lote Interno: {data[2]}", color=ft.Colors.BLUE, weight="bold", size=16),
               ft.Divider(),
               ft.Row([ft.Text("Fabricante:", weight="bold"), ft.Text(f"{inv[0]}")], spacing=5),
               ft.Row([ft.Text("Lote Prov:", weight="bold"), ft.Text(f"{inv[1]}")], spacing=5),
               ft.Row([ft.Text("Caducidad:", weight="bold"), ft.Text(f"{inv[2]}")], spacing=5),
               ft.Row([ft.Text("Cantidad:", weight="bold"), ft.Text(f"{inv[3]} kg")], spacing=5),
               ft.Divider(),
               ft.Text("Resultados de Calidad", size=16, weight="bold")
            ]

            if lab:
                l_res = lab[0]
                # Variables para facilitar lectura
                analisis_num = l_res[0]
                dictamen = l_res[1]
                raw_json = l_res[2]
                obs = l_res[3]
                analista = l_res[4]
                referencia = l_res[5]
                reanalisis = l_res[6]
                fecha_analisis = l_res[7]

                # Información General del Análisis
                info.append(ft.Row([ft.Text("No. Análisis:", weight="bold"), ft.Text(f"{analisis_num}")], spacing=5))
                info.append(ft.Row([ft.Text("Analista:", weight="bold"), ft.Text(f"{analista}")], spacing=5))
                info.append(ft.Row([ft.Text("Fecha Análisis:", weight="bold"), ft.Text(f"{fecha_analisis}")], spacing=5))
                
                if referencia:
                    info.append(ft.Row([ft.Text("Referencia:", weight="bold"), ft.Text(f"{referencia}")], spacing=5))
                if reanalisis:
                    info.append(ft.Row([ft.Text("Reanálisis:", weight="bold"), ft.Text(f"{reanalisis}")], spacing=5))

                dictamen_color = ft.Colors.GREEN if dictamen=="APROBADO" else ft.Colors.RED
                info.append(ft.Container(
                    content=ft.Text(f"DICTAMEN: {dictamen}", weight="bold", color=ft.Colors.WHITE, size=16),
                    bgcolor=dictamen_color,
                    padding=10,
                    border_radius=5,
                    alignment=ft.alignment.center
                ))
                
                # Tabla de Resultados
                try:
                    res_json = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
                    dt = ft.DataTable(
                        columns=[ft.DataColumn(ft.Text("Prueba")), ft.DataColumn(ft.Text("Resultado"))],
                        rows=[],
                        border=ft.border.all(1, ft.Colors.GREY_300),
                        vertical_lines=ft.border.all(1, ft.Colors.GREY_300),
                    )
                    for k,v in res_json.items():
                       dt.rows.append(ft.DataRow(cells=[ft.DataCell(ft.Text(str(k))), ft.DataCell(ft.Text(str(v)))]))
                    info.append(dt)
                    
                    # Preparar datos para PDF
                    res_list = [{"test": k, "spec": "-", "result": str(v)} for k,v in res_json.items()]
                except:
                    res_list = []

                if obs: 
                    info.append(ft.Text("Observaciones:", weight="bold"))
                    info.append(ft.Text(f"{obs}", italic=True))

                # Botón PDF Actualizado con TODOS los datos
                def print_pdf(e):
                    content = {
                        "Producto": data[1], 
                        "Lote": data[2], 
                        "Conclusión": dictamen, 
                        "Observaciones": obs,
                        "Referencia": referencia if referencia else "N/A",
                        "Reanálisis": str(reanalisis) if reanalisis else "N/A",
                        "Analista": analista
                    }
                    if open_pdf_in_browser(page, f"Cert_{data[2]}.pdf", content, res_list):
                        page.snack_bar = ft.SnackBar(ft.Text("Descargando PDF..."))
                        page.snack_bar.open = True
                        page.update()

                info.append(ft.ElevatedButton("Descargar Certificado", icon=ft.Icons.PICTURE_AS_PDF, bgcolor=ft.Colors.GREEN, color=ft.Colors.WHITE, on_click=print_pdf))
            else:
                info.append(ft.Text("⚠️ Pendiente de Análisis", color=ft.Colors.ORANGE, size=16, weight="bold"))

            dlg = ft.AlertDialog(title=ft.Text("Detalle del Lote"), content=ft.Column(info, tight=True, scroll=ft.ScrollMode.ALWAYS, height=500), actions=[ft.TextButton("Cerrar", on_click=lambda e: page.close(dlg))])
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

# --- NUEVAS VISTAS DE GESTIÓN DE ROLES Y USUARIOS ---

def build_roles_view(page, content_column, current_user):
    # Gestión dinámica de roles
    list_roles = ft.Column()

    def render_roles():
        rows = db.execute_query("SELECT id, name, permissions FROM roles ORDER BY name", fetch=True) or []
        list_roles.controls.clear()
        for r in rows:
            # Parseamos el JSON de permisos
            perms = r[2] if isinstance(r[2], list) else json.loads(r[2])
            perm_str = ", ".join(perms)
            list_roles.controls.append(ft.Card(content=ft.ListTile(
                title=ft.Text(r[1], weight="bold"),
                subtitle=ft.Text(f"Accesos: {perm_str}", size=12),
                leading=ft.Icon(ft.Icons.SECURITY)
            )))
        page.update()

    def open_add_role_dialog(e):
        tf_name = ft.TextField(label="Nombre del Perfil (Ej: Auditor)")
        # Crear checkboxes para cada módulo disponible
        checks = {}
        for mod_key in MODULES.keys():
            # Excluir 'ADMIN' para que no se auto-asignen superpoderes fácilmente, o dejarlo si se requiere
            checks[mod_key] = ft.Checkbox(label=MODULES[mod_key]["label"], value=False)
        
        def save_role(e):
            if not tf_name.value: return
            selected_perms = [k for k, cb in checks.items() if cb.value]
            try:
                db.execute_query("INSERT INTO roles (name, permissions) VALUES (%s, %s)", (tf_name.value, json.dumps(selected_perms)))
                page.close(dlg)
                render_roles()
                page.snack_bar = ft.SnackBar(ft.Text("Perfil creado exitosamente")); page.snack_bar.open=True; page.update()
            except Exception as ex:
                page.snack_bar = ft.SnackBar(ft.Text(f"Error: {ex}")); page.snack_bar.open=True; page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Nuevo Perfil de Usuario"),
            content=ft.Column([tf_name, ft.Text("Permisos:")] + list(checks.values()), tight=True, scroll=ft.ScrollMode.AUTO, height=400),
            actions=[ft.ElevatedButton("Guardar", on_click=save_role)]
        )
        page.open(dlg)

    render_roles()
    content_column.controls = [
        ft.Text("Perfiles y Permisos", size=20, weight="bold"),
        ft.ElevatedButton("Crear Nuevo Perfil", icon=ft.Icons.ADD_MODERATOR, on_click=open_add_role_dialog),
        list_roles
    ]
    page.update()

def build_users_view(page, content_column, current_user):
    # Seguridad: Solo ADMIN puede ver esto
    if current_user["role"] != "ADMIN": 
        content_column.controls=[ft.Text("Acceso Denegado: Se requiere rol ADMIN", color="red", size=20)]
        page.update()
        return
    
    list_users = ft.Column()
    
    # --- FUNCION PARA EDITAR USUARIO ---
    def edit_user_dialog(user_data):
        # user_data: [id, username, role, is_locked]
        uid, uname, urole, ulocked = user_data
        
        # Proteccion: No editar al superadmin
        if uname == "admin":
            page.snack_bar = ft.SnackBar(ft.Text("No se puede modificar al superusuario 'admin'."))
            page.snack_bar.open = True
            page.update()
            return

        # Traer roles disponibles para el dropdown
        roles_db = db.execute_query("SELECT name FROM roles", fetch=True) or []
        role_options = [ft.dropdown.Option(r[0]) for r in roles_db]

        # Controles
        dd_role = ft.Dropdown(label="Perfil / Rol", options=role_options, value=urole)
        sw_lock = ft.Switch(label="Bloquear Acceso", value=ulocked, active_color=ft.Colors.RED)
        
        def update_user(e):
            if dd_role.value:
                try:
                    db.execute_query(
                        "UPDATE users SET role=%s, is_locked=%s WHERE id=%s", 
                        (dd_role.value, sw_lock.value, uid)
                    )
                    
                    action_detail = f"Editó usuario '{uname}': Rol={dd_role.value}, Bloqueado={sw_lock.value}"
                    log_audit(current_user["name"], "USER_EDIT", action_detail)
                    
                    page.close(dlg)
                    render_users() # Refrescar lista
                    page.snack_bar = ft.SnackBar(ft.Text(f"Usuario {uname} actualizado"), bgcolor="green")
                    page.snack_bar.open = True
                    page.update()
                except Exception as ex:
                    logger.error(f"Error update user: {ex}")
            else:
                page.snack_bar = ft.SnackBar(ft.Text("El rol es obligatorio"))
                page.snack_bar.open = True
                page.update()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Editar Usuario: {uname}"),
            content=ft.Column([
                ft.Text("Modificar Permisos y Acceso:", size=12),
                dd_role,
                ft.Divider(),
                sw_lock
            ], tight=True, height=200),
            actions=[
                ft.ElevatedButton("Cancelar", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton("Guardar Cambios", on_click=update_user)
            ]
        )
        page.open(dlg)

    # --- RENDERIZADO DE LISTA ---
    def render_users():
        # Traemos ID, Username, Role y Status de Bloqueo
        rows = db.execute_query("SELECT id, username, role, is_locked FROM users ORDER BY username", fetch=True) or []
        
        list_users.controls.clear()
        
        for r in rows:
            # r: [0:id, 1:user, 2:role, 3:locked]
            is_locked = r[3]
            
            # USO DE STRINGS EN LUGAR DE CONSTANTES PARA EVITAR ERRORES
            icon_name = "lock" if is_locked else "person"
            icon_color = ft.Colors.RED if is_locked else ft.Colors.BLUE
            subtitle_text = f"Rol: {r[2]} | {'🔴 BLOQUEADO' if is_locked else '🟢 ACTIVO'}"
            
            list_users.controls.append(ft.Card(
                content=ft.ListTile(
                    leading=ft.Icon(name=icon_name, color=icon_color, size=30),
                    title=ft.Text(r[1], weight="bold"),
                    subtitle=ft.Text(subtitle_text),
                    trailing=ft.IconButton(
                        icon="edit", # String directo
                        tooltip="Editar / Bloquear", 
                        on_click=lambda e, x=r: edit_user_dialog(x)
                    )
                )
            ))
        page.update()
    
    # --- CREAR NUEVO USUARIO ---
    def open_add_user_dialog(e):
        roles_db = db.execute_query("SELECT name FROM roles", fetch=True) or []
        role_options = [ft.dropdown.Option(r[0]) for r in roles_db]

        u = ft.TextField(label="Usuario")
        p = ft.TextField(label="Contraseña", password=True, can_reveal_password=True)
        dd_role = ft.Dropdown(label="Seleccionar Perfil", options=role_options)

        def save_user(e):
            if u.value and p.value and dd_role.value:
                try:
                    db.execute_query("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", (u.value, p.value, dd_role.value))
                    page.close(dlg)
                    render_users()
                    log_audit(current_user["name"], "CREATE_USER", f"Creado usuario {u.value} con rol {dd_role.value}")
                    page.snack_bar = ft.SnackBar(ft.Text("Usuario creado exitosamente"), bgcolor="green")
                    page.snack_bar.open=True
                    page.update()
                except Exception as ex:
                    page.snack_bar = ft.SnackBar(ft.Text(f"Error (posible usuario duplicado): {ex}"))
                    page.snack_bar.open=True
                    page.update()
            else:
                page.snack_bar = ft.SnackBar(ft.Text("Todos los campos son obligatorios"))
                page.snack_bar.open=True
                page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Nuevo Usuario"),
            content=ft.Column([u, p, dd_role], tight=True, height=250),
            actions=[ft.ElevatedButton("Crear Usuario", on_click=save_user)]
        )
        page.open(dlg)

    # Inicializar
    render_users()
    
    content_column.controls = [
        ft.Row([
            ft.Text("Gestión de Usuarios", size=20, weight="bold"),
            ft.Container(expand=True),
            ft.ElevatedButton("Nuevo Usuario", icon="person_add", on_click=open_add_user_dialog) # String directo
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Divider(),
        list_users
    ]
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
    "CORRECCION": {"icon": ft.Icons.EDIT, "label": "Corrección (ALCOA)", "func": build_edition_view},
    "USUARIOS": {"icon": ft.Icons.PEOPLE, "label": "Usuarios", "func": build_users_view},
    "PERFILES": {"icon": ft.Icons.SECURITY, "label": "Perfiles", "func": build_roles_view}, # Nueva vista
    "ADMIN": {"icon": ft.Icons.ADMIN_PANEL_SETTINGS, "label": "Audit Trail", "func": build_audit_view},
}

def main(page: ft.Page):
    page.title = "MASTER MP"
    page.scroll = ft.ScrollMode.ADAPTIVE
    col = ft.Column(expand=True)
    nav = ft.NavigationBar(visible=False)

    # Definimos los campos de texto AQUÍ para que existan en todo el ámbito de main
    user_tf = ft.TextField(label="User")
    pass_tf = ft.TextField(label="Pass", password=True)

    # --- ENCAPSULAMOS TU DISEÑO EXACTO PARA PODER LLAMARLO AL SALIR ---
    def render_login():
        page.clean()
        page.navigation_bar.visible = False
        page.appbar = None
        
        # --- TUS LÍNEAS DE CÓDIGO EXACTAS (Diseño Login) ---
        page.add(ft.Column([ft.Icon(ft.Icons.LOCAL_PHARMACY, size=60,
        color="blue"), ft.Text("LOGIN"), user_tf, pass_tf,
        ft.ElevatedButton("Entrar", on_click=login)], alignment=ft.MainAxisAlignment.CENTER,
        expand=True))
        # ---------------------------------------------------
        
        page.update()

    # --- LÓGICA DE SALIR ---
    def logout(e):
        # 1. Resetear usuario
        current_user.update({"id": None, "name": "GUEST", "role": "GUEST"})
        # 2. Volver a pintar tu pantalla de login
        render_login()

    # --- LÓGICA DE ENTRAR ---
    def login(e):
        # Usamos los valores de tus textfields
        res = db.execute_query("SELECT id, username, role FROM users WHERE username=%s AND password=%s", (user_tf.value, pass_tf.value), fetch=True)
        
        if res:
            role_name = res[0][2]
            current_user.update({"id": res[0][0], "name": res[0][1], "role": role_name})
            
            # Obtener permisos
            role_data = db.execute_query("SELECT permissions FROM roles WHERE name=%s", (role_name,), fetch=True)
            allowed_modules = []
            if role_data:
                raw_perms = role_data[0][0]
                allowed_modules = raw_perms if isinstance(raw_perms, list) else json.loads(raw_perms)
            else:
                allowed_modules = ["ALMACEN"] 

            # Configurar Navegación
            nav.destinations = [ft.NavigationBarDestination(icon=MODULES[k]["icon"], label=MODULES[k]["label"]) for k in allowed_modules if k in MODULES]
            active_mods = [k for k in allowed_modules if k in MODULES]
            
            def nav_click(e):
                idx = e.control.selected_index
                if idx < len(active_mods):
                    MODULES[active_mods[idx]]["func"](page, col, current_user)
                    page.update()
            
            nav.on_change = nav_click
            nav.visible = True
            
            # --- AQUÍ AÑADIMOS LA BARRA SUPERIOR CON EL BOTÓN SALIR ---
            page.appbar = ft.AppBar(
                leading=ft.Icon(ft.Icons.PHARMACY),
                title=ft.Text(f"Hola, {current_user['name']}"),
                bgcolor=ft.Colors.BLUE,
                color=ft.Colors.WHITE,
                actions=[
                    ft.IconButton(ft.Icons.LOGOUT, tooltip="Cerrar Sesión", on_click=logout, icon_color=ft.Colors.WHITE)
                ]
            )

            # Limpiar login y cargar dashboard
            page.clean()
            page.add(col)
            page.navigation_bar = nav
            
            if active_mods: 
                MODULES[active_mods[0]]["func"](page, col, current_user)
            else:
                col.controls = [ft.Text("Su perfil no tiene módulos asignados.", color="red")]
            
            page.update()
        else:
            page.snack_bar = ft.SnackBar(ft.Text("Error Login")); page.snack_bar.open=True; page.update()

    # Arrancar mostrando tu diseño
    render_login()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=port, host="0.0.0.0")

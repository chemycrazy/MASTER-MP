import flet as ft
import os
import psycopg2
import logging
import json
import math
import datetime
from contextlib import contextmanager
from fpdf import FPDF

# --- CONFIGURACIÓN Y LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "dbname=postgres user=postgres password=postgres host=localhost")

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
        # Definición de tablas actualizada
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
                status VARCHAR(20) DEFAULT 'CUARENTENA'
            )""",
            """CREATE TABLE IF NOT EXISTS lab_results (
                id SERIAL PRIMARY KEY,
                inventory_id INTEGER REFERENCES inventory(id),
                analyst VARCHAR(50),
                result_data JSONB,
                conclusion VARCHAR(20),
                date_analyzed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS audit_trail (
                id SERIAL PRIMARY KEY,
                user_name VARCHAR(50),
                action VARCHAR(50),
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        ]
        create_admin = "INSERT INTO users (username, password, role) VALUES ('admin', 'admin', 'ADMIN') ON CONFLICT DO NOTHING"
        
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

def generate_pdf(filename, content_dict, test_results):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "CERTIFICADO DE CALIDAD", ln=1, align="C")
    
    pdf.set_font("Arial", size=12)
    pdf.ln(10)
    for key, value in content_dict.items():
        pdf.cell(0, 8, txt=f"{key}: {value}", ln=1)
    
    pdf.ln(10)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(60, 10, "Prueba", 1)
    pdf.cell(70, 10, "Especificación", 1)
    pdf.cell(60, 10, "Resultado", 1)
    pdf.ln()
    
    pdf.set_font("Arial", size=11)
    for test in test_results:
        pdf.cell(60, 10, str(test['test']), 1)
        pdf.cell(70, 10, str(test['spec']), 1)
        pdf.cell(60, 10, str(test['result']), 1)
        pdf.ln()

    pdf.output(filename)
    return filename

# --- UI ---
def main(page: ft.Page):
    page.title = "MASTER MP - PWA"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.window_width = 390 # Simulación Mobile
    
    current_user = {"name": None, "role": None}

    def change_tab(e):
        idx = e.control.selected_index
        content_column.controls.clear()
        if idx == 0: build_catalog_view()
        elif idx == 1: build_inventory_view()
        elif idx == 2: build_sampling_view()
        elif idx == 3: build_lab_view()
        elif idx == 4: build_query_view() # <--- NUEVO 
        elif idx == 5: build_audit_view()
        page.update()

    nav_bar = ft.NavigationBar(
        destinations=[
            ft.NavigationDestination(icon=ft.icons.BOOK, label="Catálogo"),
            ft.NavigationDestination(icon=ft.icons.INVENTORY, label="Almacén"),
            ft.NavigationDestination(icon=ft.icons.SCIENCE, label="Muestreo"),
            ft.NavigationDestination(icon=ft.icons.ASSIGNMENT, label="Lab"),
            ft.NavigationDestination(icon=ft.icons.SEARCH, label="Consulta"),
            ft.NavigationDestination(icon=ft.icons.SECURITY, label="Admin"),
        ],
        on_change=change_tab,
        visible=False
    )
    
    content_column = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    # 1. LOGIN
    def build_login():
        user_tf = ft.TextField(label="Usuario")
        pass_tf = ft.TextField(label="Contraseña", password=True)
        error_txt = ft.Text(color="red")
        
        def auth(e):
            res = db.execute_query("SELECT * FROM users WHERE username=%s AND password=%s", (user_tf.value, pass_tf.value), fetch=True)
            if res:
                current_user["name"] = res[0][1]
                current_user["role"] = res[0][3]
                nav_bar.visible = True
                page.clean()
                page.add(content_column)
                page.navigation_bar = nav_bar
                build_catalog_view()
                page.update()
            else:
                error_txt.value = "Error de credenciales"
                page.update()

        page.add(ft.Container(
            content=ft.Column([
                ft.Icon(ft.icons.LOCAL_PHARMACY, size=60, color="blue"),
                ft.Text("MASTER MP", size=24, weight="bold"),
                user_tf, pass_tf, error_txt,
                ft.ElevatedButton("Entrar", on_click=auth)
            ], alignment=ft.MainAxisAlignment.CENTER),
            alignment=ft.alignment.center, padding=20
        ))

    # 2. CATÁLOGO & PERFILES
    def build_catalog_view():
        # Tabs internos: Materias vs Pruebas
        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(text="Materias Primas", icon=ft.icons.LAYERS),
                ft.Tab(text="Pruebas Master", icon=ft.icons.LIST_ALT),
            ],
            on_change=lambda e: render_catalog_content(e.control.selected_index)
        )
        
        tab_content = ft.Column()

        def render_catalog_content(index):
            tab_content.controls.clear()
            
            if index == 0: # MATERIAS PRIMAS
                materials = db.execute_query("SELECT id, code, name, is_active FROM materials ORDER BY id DESC", fetch=True) or []
                for m in materials:
                    tab_content.controls.append(
                        ft.Card(content=ft.ListTile(
                            leading=ft.Icon(ft.icons.CIRCLE, color="green" if m[3] else "red"),
                            title=ft.Text(f"{m[1]} - {m[2]}"),
                            trailing=ft.IconButton(ft.icons.SETTINGS, tooltip="Configurar Perfil", on_click=lambda e, mid=m[0], name=m[2]: open_profile_dialog(mid, name))
                        ))
                    )
                # Botón flotante para agregar materia
                tab_content.controls.insert(0, ft.ElevatedButton("Nueva Materia Prima", icon=ft.icons.ADD, on_click=add_material_dialog))

            elif index == 1: # PRUEBAS MASTER
                tests = db.execute_query("SELECT id, name, method FROM standard_tests ORDER BY name", fetch=True) or []
                for t in tests:
                    tab_content.controls.append(
                         ft.ListTile(title=ft.Text(t[1]), subtitle=ft.Text(f"Método: {t[2]}"), leading=ft.Icon(ft.icons.CHECK_BOX))
                    )
                tab_content.controls.insert(0, ft.ElevatedButton("Nueva Prueba Estándar", icon=ft.icons.ADD, on_click=add_test_dialog))
            
            page.update()

        content_column.controls = [ft.Text("Gestión de Catálogos", size=20, weight="bold"), tabs, tab_content]
        render_catalog_content(0)
        page.update()

    # --- DIALOGOS DE CATALOGO ---
    def add_material_dialog(e):
        code = ft.TextField(label="Código")
        name = ft.TextField(label="Nombre")
        cat = ft.Dropdown(label="Categoría", options=[ft.dropdown.Option("API"), ft.dropdown.Option("EXCIPIENTE")])
        
        def save(e):
            db.execute_query("INSERT INTO materials (code, name, category) VALUES (%s, %s, %s)", (code.value, name.value, cat.value))
            log_audit(current_user["name"], "CREATE_MAT", f"Created {code.value}")
            page.dialog.open = False
            build_catalog_view()
        
        page.dialog = ft.AlertDialog(title=ft.Text("Crear Material"), content=ft.Column([code, name, cat], tight=True), actions=[ft.TextButton("Guardar", on_click=save)])
        page.dialog.open = True
        page.update()

    def add_test_dialog(e):
        name = ft.TextField(label="Nombre de Prueba (Ej: pH)")
        method = ft.TextField(label="Método Referencia")
        
        def save(e):
            db.execute_query("INSERT INTO standard_tests (name, method) VALUES (%s, %s)", (name.value, method.value))
            page.dialog.open = False
            build_catalog_view()
            
        page.dialog = ft.AlertDialog(title=ft.Text("Crear Prueba Master"), content=ft.Column([name, method], tight=True), actions=[ft.TextButton("Guardar", on_click=save)])
        page.dialog.open = True
        page.update()

    def open_profile_dialog(material_id, material_name):
        # Muestra pruebas actuales y permite agregar nuevas
        
        def refresh_list():
            current_tests = db.execute_query(
                "SELECT mp.id, st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id = st.id WHERE mp.material_id = %s",
                (material_id,), fetch=True
            ) or []
            
            list_col.controls.clear()
            for t in current_tests:
                list_col.controls.append(ft.ListTile(
                    title=ft.Text(t[1]), 
                    subtitle=ft.Text(f"Spec: {t[2]}"),
                    trailing=ft.IconButton(ft.icons.DELETE, icon_color="red", on_click=lambda e, pid=t[0]: delete_profile_item(pid))
                ))
            page.update()

        def add_test_to_profile(e):
            if not dd_tests.value or not spec_tf.value: return
            try:
                db.execute_query(
                    "INSERT INTO material_profile (material_id, test_id, specification) VALUES (%s, %s, %s)",
                    (material_id, dd_tests.value, spec_tf.value)
                )
                refresh_list()
                spec_tf.value = ""
            except Exception as ex:
                logger.error(ex)

        def delete_profile_item(pid):
            db.execute_query("DELETE FROM material_profile WHERE id=%s", (pid,))
            refresh_list()

        # Componentes del Dialogo
        all_tests = db.execute_query("SELECT id, name FROM standard_tests", fetch=True) or []
        dd_tests = ft.Dropdown(label="Seleccionar Prueba", options=[ft.dropdown.Option(str(t[0]), t[1]) for t in all_tests], expand=True)
        spec_tf = ft.TextField(label="Especificación (Límite)", expand=True)
        
        list_col = ft.Column(height=200, scroll=ft.ScrollMode.ALWAYS)
        refresh_list()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Perfil: {material_name}"),
            content=ft.Column([
                ft.Text("Configura las pruebas que se cargarán en Lab:"),
                ft.Row([dd_tests, spec_tf], alignment="spaceBetween"),
                ft.ElevatedButton("Agregar Prueba al Perfil", on_click=add_test_to_profile),
                ft.Divider(),
                ft.Text("Pruebas Asignadas:"),
                list_col
            ], tight=True),
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # 3. ALMACÉN (Igual que antes, simplificado para contexto)
    def build_inventory_view():
        materials = db.execute_query("SELECT id, name FROM materials WHERE is_active=TRUE", fetch=True)
        mat_opts = [ft.dropdown.Option(str(m[0]), m[1]) for m in materials] if materials else []
        
        mat_dd = ft.Dropdown(label="Material", options=mat_opts)
        lot_int = ft.TextField(label="Lote Interno")
        qty = ft.TextField(label="Cantidad")
        
        def receive(e):
            db.execute_query("INSERT INTO inventory (material_id, lot_internal, quantity, status) VALUES (%s, %s, %s, 'CUARENTENA')",
                             (mat_dd.value, lot_int.value, float(qty.value)))
            ft.SnackBar(ft.Text("Ingresado")).open = True
            page.update()

        content_column.controls = [ft.Text("Recepción"), mat_dd, lot_int, qty, ft.ElevatedButton("Guardar", on_click=receive)]
        page.update()

    # 4. MUESTREO (Simplificado)
    def build_sampling_view():
        items = db.execute_query("SELECT i.id, m.name, i.lot_internal FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='CUARENTENA'", fetch=True)
        lv = ft.ListView(expand=True)
        for i in items:
            lv.controls.append(ft.ListTile(
                title=ft.Text(f"{i[1]} - {i[2]}"),
                trailing=ft.IconButton(ft.icons.CONTENT_CUT, on_click=lambda e, iid=i[0]: do_sample(iid))
            ))
        content_column.controls = [ft.Text("Pendientes Muestreo"), lv]
        page.update()
    
    def do_sample(iid):
        db.execute_query("UPDATE inventory SET status='MUESTREADO' WHERE id=%s", (iid,))
        build_sampling_view()

    # 5. LABORATORIO DINÁMICO
    def build_lab_view():
        # Busca items muestreados
        pending = db.execute_query(
            """SELECT i.id, m.name, i.lot_internal, i.material_id 
               FROM inventory i JOIN materials m ON i.material_id = m.id 
               WHERE i.status='MUESTREADO'""", fetch=True
        ) or []

        lv = ft.ListView(expand=True)

        def open_analysis(inv_id, mat_id, mat_name, lot):
            # 1. Cargar el perfil de pruebas de este material
            profile_tests = db.execute_query(
                "SELECT st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id = st.id WHERE mp.material_id = %s",
                (mat_id,), fetch=True
            )
            
            if not profile_tests:
                ft.SnackBar(ft.Text("Este material no tiene pruebas configuradas en el Catálogo.")).open = True
                page.update()
                return

            # 2. Generar campos dinámicos
            input_fields = []
            for pt in profile_tests:
                # Cada campo guarda referencia a su nombre y specs
                field = ft.TextField(label=f"{pt[0]} (Esp: {pt[1]})", data={"test": pt[0], "spec": pt[1]})
                input_fields.append(field)

            concl_dd = ft.Dropdown(label="Conclusión", options=[ft.dropdown.Option("APROBADO"), ft.dropdown.Option("RECHAZADO")])

            def save_results(e):
                # Recolectar datos
                results_json = {}
                results_list_for_pdf = []
                
                for f in input_fields:
                    val = f.value
                    results_json[f.data['test']] = val
                    results_list_for_pdf.append({"test": f.data['test'], "spec": f.data['spec'], "result": val})
                
                # Guardar en JSONB
                db.execute_query(
                    "INSERT INTO lab_results (inventory_id, analyst, result_data, conclusion) VALUES (%s, %s, %s, %s)",
                    (inv_id, current_user["name"], json.dumps(results_json), concl_dd.value)
                )
                
                new_status = "LIBERADO" if concl_dd.value == "APROBADO" else "RECHAZADO"
                db.execute_query("UPDATE inventory SET status=%s WHERE id=%s", (new_status, inv_id))
                
                # Generar PDF Dinámico
                generate_pdf(f"CoA_{lot}.pdf", {"Producto": mat_name, "Lote": lot, "Conclusión": concl_dd.value}, results_list_for_pdf)
                
                page.dialog.open = False
                build_lab_view()
                ft.SnackBar(ft.Text("Resultados guardados y Certificado generado")).open = True
                page.update()

            dlg = ft.AlertDialog(
                title=ft.Text(f"Analizando: {mat_name} {lot}"),
                content=ft.Column([ft.Text("Ingrese resultados:")] + input_fields + [concl_dd], scroll=ft.ScrollMode.ALWAYS, height=400),
                actions=[ft.ElevatedButton("Terminar Análisis", on_click=save_results)]
            )
            page.dialog = dlg
            dlg.open = True
            page.update()

        for p in pending:
            lv.controls.append(ft.Card(content=ft.ListTile(
                title=ft.Text(p[1]),
                subtitle=ft.Text(f"Lote: {p[2]}"),
                trailing=ft.IconButton(ft.icons.PLAY_ARROW, tooltip="Analizar", on_click=lambda e, i=p: open_analysis(i[0], i[3], i[1], i[2]))
            )))

        content_column.controls = [ft.Text("Laboratorio - Muestras Pendientes"), lv]
        page.update()
   # 6. MÓDULO DE CONSULTA Y CERTIFICADOS
    def build_query_view():
        search_tf = ft.TextField(label="Buscar por Lote o Nombre", suffix_icon=ft.icons.SEARCH)
        results_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

        def perform_search(e):
            term = f"%{search_tf.value}%"
            # Traemos inventario con nombre de material
            query = """
                SELECT i.id, m.code, m.name, i.lot_internal, i.status, i.expiry_date, i.quantity 
                FROM inventory i 
                JOIN materials m ON i.material_id = m.id 
                WHERE m.name ILIKE %s OR i.lot_internal ILIKE %s OR m.code ILIKE %s
                ORDER BY i.id DESC
            """
            items = db.execute_query(query, (term, term, term), fetch=True) or []
            
            results_col.controls.clear()
            
            if not items:
                results_col.controls.append(ft.Text("No se encontraron registros."))
            
            for item in items:
                # Color del estado
                status_color = "green" if item[4] == "LIBERADO" else "red" if item[4] == "RECHAZADO" else "orange"
                
                results_col.controls.append(
                    ft.Card(
                        content=ft.ListTile(
                            leading=ft.Icon(ft.icons.CIRCLE, color=status_color),
                            title=ft.Text(f"{item[2]} ({item[1]})"),
                            subtitle=ft.Text(f"Lote: {item[3]} | Estado: {item[4]}"),
                            trailing=ft.IconButton(ft.icons.VISIBILITY, tooltip="Ver Detalles / CoA", 
                                                   on_click=lambda e, iid=item[0], name=item[2], lot=item[3]: show_full_details(iid, name, lot))
                        )
                    )
                )
            page.update()

        def show_full_details(inv_id, mat_name, lot):
            # 1. Obtener Datos Generales
            inv_data = db.execute_query(
                "SELECT lot_vendor, manufacturer, quantity, expiry_date, status, material_id FROM inventory WHERE id=%s", 
                (inv_id,), fetch=True
            )[0]
            
            # 2. Obtener Resultados de Laboratorio (si existen)
            lab_data = db.execute_query(
                "SELECT analyst, result_data, conclusion, date_analyzed FROM lab_results WHERE inventory_id=%s", 
                (inv_id,), fetch=True
            )

            # Construir UI de Detalles
            details_controls = [
                ft.Text(f"Producto: {mat_name}", size=20, weight="bold"),
                ft.Text(f"Lote Interno: {lot}", size=16),
                ft.Divider(),
                ft.Text("Información de Almacén:", weight="bold"),
                ft.Text(f"Lote Proveedor: {inv_data[0]}"),
                ft.Text(f"Fabricante: {inv_data[1] or 'N/A'}"),
                ft.Text(f"Cantidad: {inv_data[2]} kg"),
                ft.Text(f"Caducidad: {inv_data[3]}"),
                ft.Text(f"Estado Actual: {inv_data[4]}"),
                ft.Divider(),
            ]

            # Si hay análisis, mostrar tabla comparativa
            if lab_data:
                res = lab_data[0] # Tomamos el primer análisis
                results_json = res[1] # JSON con resultados
                conclusion = res[2]
                
                details_controls.append(ft.Text(f"Resultados de Calidad ({res[3]}):", weight="bold"))
                details_controls.append(ft.Text(f"Analista: {res[0]}"))
                details_controls.append(ft.Text(f"Conclusión: {conclusion}", color="green" if conclusion=="APROBADO" else "red", weight="bold"))
                
                # Reconstruir tabla comparativa (Specs vs Resultado)
                # Necesitamos consultar las specs originales del perfil
                mat_id = inv_data[5]
                profile_specs = db.execute_query(
                    "SELECT st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id = st.id WHERE mp.material_id=%s",
                    (mat_id,), fetch=True
                )
                
                dt = ft.DataTable(columns=[
                    ft.DataColumn(ft.Text("Prueba")),
                    ft.DataColumn(ft.Text("Especificación")),
                    ft.DataColumn(ft.Text("Resultado")),
                ], rows=[])
                
                # Lista para enviar al generador de PDF
                pdf_data_list = []

                if profile_specs:
                    for spec in profile_specs:
                        test_name = spec[0]
                        test_spec = spec[1]
                        # Buscar resultado en el JSON, si no existe poner 'N/A'
                        test_res = results_json.get(test_name, "N/A")
                        
                        dt.rows.append(ft.DataRow(cells=[
                            ft.DataCell(ft.Text(test_name)),
                            ft.DataCell(ft.Text(test_spec)),
                            ft.DataCell(ft.Text(str(test_res))),
                        ]))
                        
                        pdf_data_list.append({"test": test_name, "spec": test_spec, "result": test_res})

                details_controls.append(dt)
                
                # Botón de Generar PDF
                def print_coa(e):
                    pdf_name = f"CoA_REPRINT_{lot}.pdf"
                    generate_pdf(pdf_name, 
                                 {"Producto": mat_name, "Lote": lot, "Fabricante": str(inv_data[1]), "Conclusión": conclusion}, 
                                 pdf_data_list)
                    ft.SnackBar(ft.Text(f"Certificado generado: {pdf_name}")).open = True
                    page.update()

                details_controls.append(ft.ElevatedButton("Descargar Certificado (PDF)", icon=ft.icons.PICTURE_AS_PDF, on_click=print_coa))

            else:
                details_controls.append(ft.Text("⚠️ Este material aún no ha sido analizado por el laboratorio.", color="orange"))

            # Mostrar Dialogo
            dlg = ft.AlertDialog(
                title=ft.Text("Expediente de Lote"),
                content=ft.Column(details_controls, scroll=ft.ScrollMode.ALWAYS, height=500, width=400),
                actions=[ft.TextButton("Cerrar", on_click=lambda e: setattr(dlg, 'open', False) or page.update())]
            )
            page.dialog = dlg
            dlg.open = True
            page.update()

        search_tf.on_submit = perform_search
        content_column.controls = [
            ft.Text("Consulta General & Certificados", size=20, weight="bold"),
            ft.Row([search_tf, ft.IconButton(ft.icons.SEARCH, on_click=perform_search)]),
            results_col
        ]
        # Cargar todo al inicio
        perform_search(None)     
    def build_audit_view():
        # Vista simple de logs
        content_column.controls = [ft.Text("Audit Trail disponible en base de datos.")]
        page.update()

    build_login()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=port, host="0.0.0.0")

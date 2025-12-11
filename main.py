import flet as ft
import os
import psycopg2
import logging
import json
import math
import datetime
import base64  # <--- CRÍTICO PARA DESCARGAR PDF
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
        # Definición de tablas COMPLETA
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
                manufacturer VARCHAR(100),
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
                analysis_num VARCHAR(50),
                bib_reference VARCHAR(200),
                reanalysis_date DATE,
                observations TEXT,
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
    """Registra en base de datos"""
    db.execute_query("INSERT INTO audit_trail (user_name, action, details) VALUES (%s, %s, %s)", (user, action, details))

def open_pdf_in_browser(page, filename, content_dict, test_results):
    """Genera el PDF y lo lanza al navegador para descarga (FIXED)"""
    try:
        pdf = FPDF()
        pdf.add_page()
        
        # Encabezado
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, "CERTIFICADO DE ANALISIS", ln=1, align="C")
        pdf.set_font("Arial", size=10)
        pdf.ln(5)

        # Datos Generales
        for key, value in content_dict.items():
            if key != "Observaciones":
                pdf.set_font("Arial", "B", 10)
                pdf.cell(50, 8, txt=f"{key}:", border=0)
                pdf.set_font("Arial", size=10)
                pdf.cell(0, 8, txt=str(value), ln=1, border=0)
        
        pdf.ln(5)
        
        # Tabla
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(60, 8, "Prueba", 1, fill=True)
        pdf.cell(70, 8, "Especificacion", 1, fill=True)
        pdf.cell(60, 8, "Resultado", 1, ln=1, fill=True)
        
        pdf.set_font("Arial", size=10)
        for test in test_results:
            pdf.cell(60, 8, str(test.get('test', '')), 1)
            pdf.cell(70, 8, str(test.get('spec', '')), 1)
            pdf.cell(60, 8, str(test.get('result', '')), 1, ln=1)

        # Observaciones
        pdf.ln(10)
        if "Observaciones" in content_dict:
            pdf.set_font("Arial", "B", 10)
            pdf.cell(0, 8, "Dictamen / Obs:", ln=1)
            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 6, str(content_dict["Observaciones"]))

        # --- LÓGICA DE DESCARGA WEB ---
        # Guardamos temporalmente en el sistema de archivos efímero
        temp_path = "/tmp/temp_cert.pdf"
        pdf.output(temp_path)
        
        # Leemos el archivo como binario y lo convertimos a base64
        with open(temp_path, "rb") as f:
            b64_pdf = base64.b64encode(f.read()).decode('utf-8')
        
        # Le decimos al navegador que abra este "archivo virtual"
        page.launch_url(f"data:application/pdf;base64,{b64_pdf}")
        return True
    
    except Exception as e:
        logger.error(f"Error generando PDF: {e}")
        return False
# --- UI PRINCIPAL ---
def main(page: ft.Page):
    page.title = "MASTER MP - PWA"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.window_width = 390 
    
    current_user = {"name": None, "role": None}

    def change_tab(e):
        idx = e.control.selected_index
        content_column.controls.clear()
        if idx == 0: build_catalog_view()
        elif idx == 1: build_inventory_view()
        elif idx == 2: build_sampling_view()
        elif idx == 3: build_lab_view()
        elif idx == 4: build_query_view()
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

    # 2. CATÁLOGO
    def build_catalog_view():
        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(text="Materias", icon=ft.icons.LAYERS),
                ft.Tab(text="Pruebas", icon=ft.icons.LIST_ALT),
            ],
            on_change=lambda e: render_catalog_content(e.control.selected_index)
        )
        
        tab_content = ft.Column()

        def render_catalog_content(index):
            tab_content.controls.clear()
            if index == 0: 
                materials = db.execute_query("SELECT id, code, name, is_active FROM materials ORDER BY id DESC", fetch=True) or []
                for m in materials:
                    tab_content.controls.append(
                        ft.Card(content=ft.ListTile(
                            leading=ft.Icon(ft.icons.CIRCLE, color="green" if m[3] else "red"),
                            title=ft.Text(f"{m[1]} - {m[2]}"),
                            trailing=ft.IconButton(ft.icons.SETTINGS, on_click=lambda e, mid=m[0], name=m[2]: open_profile_dialog(mid, name))
                        ))
                    )
                tab_content.controls.insert(0, ft.ElevatedButton("Nueva Materia", icon=ft.icons.ADD, on_click=add_material_dialog))
            elif index == 1: 
                tests = db.execute_query("SELECT id, name, method FROM standard_tests ORDER BY name", fetch=True) or []
                for t in tests:
                    tab_content.controls.append(ft.ListTile(title=ft.Text(t[1]), subtitle=ft.Text(f"{t[2]}"), leading=ft.Icon(ft.icons.CHECK)))
                tab_content.controls.insert(0, ft.ElevatedButton("Nueva Prueba", icon=ft.icons.ADD, on_click=add_test_dialog))
            page.update()

        content_column.controls = [ft.Text("Catálogo", size=20, weight="bold"), tabs, tab_content]
        render_catalog_content(0)
        page.update()

    def add_material_dialog(e):
        code = ft.TextField(label="Código")
        name = ft.TextField(label="Nombre")
        cat = ft.Dropdown(label="Categoría", options=[ft.dropdown.Option("API"), ft.dropdown.Option("EXCIPIENTE")])
        def save(e):
            db.execute_query("INSERT INTO materials (code, name, category) VALUES (%s, %s, %s)", (code.value, name.value, cat.value))
            log_audit(current_user["name"], "CREATE_MAT", f"Created {code.value}")
            page.dialog.open = False
            build_catalog_view()
            page.update()
        page.dialog = ft.AlertDialog(title=ft.Text("Crear Material"), content=ft.Column([code, name, cat], tight=True), actions=[ft.TextButton("Guardar", on_click=save)])
        page.dialog.open = True
        page.update()

    def add_test_dialog(e):
        name = ft.TextField(label="Nombre de Prueba")
        method = ft.TextField(label="Método")
        def save(e):
            db.execute_query("INSERT INTO standard_tests (name, method) VALUES (%s, %s)", (name.value, method.value))
            page.dialog.open = False
            build_catalog_view()
            page.update()
        page.dialog = ft.AlertDialog(title=ft.Text("Crear Prueba"), content=ft.Column([name, method], tight=True), actions=[ft.TextButton("Guardar", on_click=save)])
        page.dialog.open = True
        page.update()

    def open_profile_dialog(material_id, material_name):
        def refresh_list():
            current_tests = db.execute_query("SELECT mp.id, st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id = st.id WHERE mp.material_id = %s", (material_id,), fetch=True) or []
            list_col.controls.clear()
            for t in current_tests:
                list_col.controls.append(ft.ListTile(title=ft.Text(t[1]), subtitle=ft.Text(f"{t[2]}"), trailing=ft.IconButton(ft.icons.DELETE, icon_color="red", on_click=lambda e, pid=t[0]: delete_profile_item(pid))))
            page.update()

        def add_test_to_profile(e):
            if dd_tests.value and spec_tf.value:
                try:
                    db.execute_query("INSERT INTO material_profile (material_id, test_id, specification) VALUES (%s, %s, %s)", (material_id, dd_tests.value, spec_tf.value))
                    refresh_list()
                    spec_tf.value = ""
                except: pass

        def delete_profile_item(pid):
            db.execute_query("DELETE FROM material_profile WHERE id=%s", (pid,))
            refresh_list()

        all_tests = db.execute_query("SELECT id, name FROM standard_tests", fetch=True) or []
        dd_tests = ft.Dropdown(label="Prueba", options=[ft.dropdown.Option(str(t[0]), t[1]) for t in all_tests], expand=True)
        spec_tf = ft.TextField(label="Especificación", expand=True)
        list_col = ft.Column(height=200, scroll=ft.ScrollMode.ALWAYS)
        refresh_list()
        dlg = ft.AlertDialog(title=ft.Text(f"Perfil: {material_name}"), content=ft.Column([ft.Row([dd_tests, spec_tf]), ft.ElevatedButton("Agregar", on_click=add_test_to_profile), ft.Divider(), list_col], tight=True))
        page.dialog = dlg
        dlg.open = True
        page.update()

    # 3. ALMACÉN
    def build_inventory_view():
        materials = db.execute_query("SELECT id, name, code FROM materials WHERE is_active=TRUE ORDER BY name", fetch=True)
        mat_opts = [ft.dropdown.Option(key=str(m[0]), text=f"{m[1]} ({m[2]})") for m in materials] if materials else []
        
        mat_dd = ft.Dropdown(label="Materia Prima", options=mat_opts)
        lot_int = ft.TextField(label="Lote Interno")
        lot_ven = ft.TextField(label="Lote Prov.")
        mfg = ft.TextField(label="Fabricante")
        qty = ft.TextField(label="Cantidad", keyboard_type=ft.KeyboardType.NUMBER)
        expiry = ft.TextField(label="Caducidad (YYYY-MM-DD)")

        def receive(e):
            if not all([mat_dd.value, lot_int.value, qty.value]): return
            try:
                db.execute_query("INSERT INTO inventory (material_id, lot_internal, lot_vendor, manufacturer, expiry_date, quantity, status) VALUES (%s,%s,%s,%s,%s,%s,'CUARENTENA')",
                                 (mat_dd.value, lot_int.value, lot_ven.value, mfg.value, expiry.value, float(qty.value)))
                log_audit(current_user["name"], "RECEIPT", f"In: {lot_int.value}")
                ft.SnackBar(ft.Text("Guardado")).open = True
                page.update()
            except Exception: ft.SnackBar(ft.Text("Error en datos")).open = True

        content_column.controls = [ft.Text("Recepción", size=20, weight="bold"), mat_dd, lot_int, lot_ven, mfg, qty, expiry, ft.ElevatedButton("Ingresar", on_click=receive)]
        page.update()
        # 4. MUESTREO (FÓRMULA N+1)
    def build_sampling_view():
        items = db.execute_query("SELECT i.id, m.name, i.lot_internal, i.quantity FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='CUARENTENA'", fetch=True) or []
        lv = ft.ListView(expand=True, spacing=10)

        def open_dlg(iid, name, lot, qty):
            # Lógica reactiva para fórmula
            tf_n = ft.TextField(
                label="N Envases", 
                keyboard_type=ft.KeyboardType.NUMBER,
                on_change=lambda e: setattr(txt_f, 'value', f"Abrir: {math.ceil(math.sqrt(int(e.control.value or 0)) + 1)}") or page.update()
            )
            txt_f = ft.Text("Abrir: 0", color="blue", weight="bold")
            tf_rem = ft.TextField(label="Kg Muestreados", keyboard_type=ft.KeyboardType.NUMBER)
            
            def save(e):
                try:
                    rem = float(tf_rem.value or 0)
                    if rem > 0 and rem <= qty:
                        db.execute_query("UPDATE inventory SET quantity=%s, status='MUESTREADO' WHERE id=%s", (qty-rem, iid))
                        log_audit(current_user["name"], "SAMPLE", f"{lot} -{rem}kg")
                        page.dialog.open = False
                        build_sampling_view()
                        page.update()
                        ft.SnackBar(ft.Text("Muestreo registrado")).open = True
                    else:
                        tf_rem.error_text = "Cantidad inválida"
                        page.update()
                except: pass
            
            page.dialog = ft.AlertDialog(
                title=ft.Text(f"Muestreo {lot}"), 
                content=ft.Column([ft.Text(f"Stock: {qty}"), tf_n, txt_f, tf_rem], tight=True), 
                actions=[ft.ElevatedButton("Guardar", on_click=save)]
            )
            page.dialog.open = True
            page.update()

        for i in items:
            lv.controls.append(ft.Card(content=ft.ListTile(
                title=ft.Text(i[1]), 
                subtitle=ft.Text(f"Lote: {i[2]} | Stock: {i[3]}"), 
                trailing=ft.IconButton(ft.icons.CUT, on_click=lambda e, x=i: open_dlg(x[0], x[1], x[2], x[3]))
            )))
        content_column.controls = [ft.Text("Muestreo", size=20, weight="bold"), lv]
        page.update()

    # 5. LABORATORIO (CON PDF BASE64)
    def build_lab_view():
        pending = db.execute_query("SELECT i.id, m.name, i.lot_internal, i.material_id FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='MUESTREADO'", fetch=True) or []
        lv = ft.ListView(expand=True, spacing=10)

        def open_analysis(inv_id, mat_id, mat_name, lot):
            profile = db.execute_query("SELECT st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id = st.id WHERE mp.material_id = %s", (mat_id,), fetch=True)
            if not profile: 
                ft.SnackBar(ft.Text("Sin perfil de pruebas")).open = True
                page.update()
                return
            
            tf_num = ft.TextField(label="No. Análisis")
            tf_ref = ft.TextField(label="Referencia")
            tf_obs = ft.TextField(label="Obs", multiline=True)
            tf_re = ft.TextField(label="Fecha Reanálisis (YYYY-MM-DD)")
            dd_con = ft.Dropdown(label="Dictamen", options=[ft.dropdown.Option("APROBADO"), ft.dropdown.Option("RECHAZADO")], value="APROBADO")
            inputs = [ft.TextField(label=f"{p[0]} ({p[1]})", data={"test": p[0], "spec": p[1]}) for p in profile]

            def save(e):
                if not tf_num.value: return
                res_json = {f.data['test']: f.value for f in inputs}
                res_list = [{"test": f.data['test'], "spec": f.data['spec'], "result": f.value} for f in inputs]
                
                db.execute_query("INSERT INTO lab_results (inventory_id, analyst, result_data, conclusion, analysis_num, bib_reference, reanalysis_date, observations) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                 (inv_id, current_user["name"], json.dumps(res_json), dd_con.value, tf_num.value, tf_ref.value, tf_re.value or None, tf_obs.value))
                
                st = "LIBERADO" if dd_con.value == "APROBADO" else "RECHAZADO"
                db.execute_query("UPDATE inventory SET status=%s WHERE id=%s", (st, inv_id))
                
                page.dialog.open = False
                build_lab_view()
                page.update()
                
                # --- LLAMADA CRÍTICA AL PDF ---
                open_pdf_in_browser(page, f"CoA_{lot}.pdf", {"Producto": mat_name, "Lote": lot, "Analisis": tf_num.value, "Dictamen": dd_con.value, "Observaciones": tf_obs.value}, res_list)

            page.dialog = ft.AlertDialog(title=ft.Text(f"Analisis {lot}"), content=ft.Column([tf_num, tf_ref] + inputs + [tf_obs, dd_con, tf_re], scroll=ft.ScrollMode.ALWAYS, height=500), actions=[ft.ElevatedButton("Guardar", on_click=save)])
            page.dialog.open = True
            page.update()

        for p in pending:
            lv.controls.append(ft.Card(content=ft.ListTile(title=ft.Text(p[1]), subtitle=ft.Text(p[2]), trailing=ft.IconButton(ft.icons.PLAY_ARROW, on_click=lambda e, x=p: open_analysis(x[0], x[3], x[1], x[2])))))
        content_column.controls = [ft.Text("Laboratorio", size=20, weight="bold"), lv]
        page.update()

    # 6. CONSULTA (REIMPRESIÓN PDF)
    def build_query_view():
        tf_search = ft.TextField(label="Buscar Lote/Nombre", suffix_icon=ft.icons.SEARCH)
        col_res = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

        def search(e):
            t = f"%{tf_search.value}%"
            data = db.execute_query("SELECT i.id, m.name, i.lot_internal, i.status FROM inventory i JOIN materials m ON i.material_id=m.id WHERE m.name ILIKE %s OR i.lot_internal ILIKE %s ORDER BY i.id DESC", (t, t), fetch=True) or []
            col_res.controls.clear()
            for d in data:
                col_res.controls.append(ft.Card(content=ft.ListTile(title=ft.Text(d[1]), subtitle=ft.Text(f"{d[2]} - {d[3]}"), trailing=ft.IconButton(ft.icons.VISIBILITY, on_click=lambda e, x=d: show_detail(x[0], x[1], x[2])))))
            page.update()

        def show_detail(iid, name, lot):
            lab = db.execute_query("SELECT analyst, result_data, conclusion, analysis_num, observations FROM lab_results WHERE inventory_id=%s", (iid,), fetch=True)
            info = db.execute_query("SELECT material_id FROM inventory WHERE id=%s", (iid,), fetch=True)[0]
            
            content_list = [ft.Text(f"Producto: {name}"), ft.Text(f"Lote: {lot}")]
            
            if lab:
                l = lab[0]
                content_list.append(ft.Text(f"Resultado: {l[2]}"))
                specs = db.execute_query("SELECT st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id=st.id WHERE mp.material_id=%s", (info[0],), fetch=True)
                pdf_res = []
                for s in specs:
                    val = l[1].get(s[0], '-')
                    content_list.append(ft.Text(f"{s[0]}: {val} (Esp: {s[1]})"))
                    pdf_res.append({"test": s[0], "spec": s[1], "result": val})
                
                # Botón Reimprimir
                btn_pdf = ft.ElevatedButton("Descargar PDF", on_click=lambda e: open_pdf_in_browser(page, "CoA.pdf", {"Producto": name, "Lote": lot, "Analisis": l[3], "Dictamen": l[2], "Observaciones": l[4]}, pdf_res))
                content_list.append(btn_pdf)
            else:
                content_list.append(ft.Text("Sin análisis aún."))

            page.dialog = ft.AlertDialog(title=ft.Text("Detalle"), content=ft.Column(content_list, height=400, scroll=ft.ScrollMode.ALWAYS))
            page.dialog.open = True
            page.update()

        tf_search.on_submit = search
        content_column.controls = [ft.Text("Consulta", size=20, weight="bold"), tf_search, col_res]
        search(None)

    # 7. ADMIN (AUDIT TRAIL ARREGLADO)
    def build_audit_view():
        if current_user["role"] != "ADMIN":
            content_column.controls = [
                ft.Column([
                    ft.Icon(ft.icons.BLOCK, color="red", size=40),
                    ft.Text("SOLO ADMIN", color="red", size=20)
                ], alignment=ft.MainAxisAlignment.CENTER)
            ]
        else:
            logs = db.execute_query("SELECT timestamp, user_name, action, details FROM audit_trail ORDER BY id DESC LIMIT 50", fetch=True) or []
            
            # Usamos Column Scrollable, no ListView
            log_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=10)
            
            for l in logs:
                log_col.controls.append(
                    ft.Container(
                        padding=10, border=ft.border.all(1, "grey"), border_radius=5,
                        content=ft.Column([
                            ft.Row([ft.Text(str(l[0])[:19], weight="bold"), ft.Badge(l[2])], alignment="spaceBetween"),
                            ft.Text(f"User: {l[1]}"),
                            ft.Text(f"{l[3]}", italic=True)
                        ])
                    )
                )
            
            content_column.controls = [
                ft.Text("Audit Trail", size=20, weight="bold"), 
                log_col 
            ]
        page.update()

    build_login()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=port, host="0.0.0.0")

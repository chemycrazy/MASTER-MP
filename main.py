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

# --- INICIO DE LA NUEVA FUNCIÓN ---
def generate_pdf(page, filename, content_dict, test_results):
    """
    Genera el PDF en el servidor, lo convierte a código Base64
    y fuerza la descarga en el navegador del usuario.
    """
    try:
        pdf = FPDF()
        pdf.add_page()
        
        # --- DISEÑO DEL PDF (IGUAL QUE ANTES) ---
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
        
        # Tabla de Resultados
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(60, 8, "Prueba", 1, fill=True)
        pdf.cell(70, 8, "Especificacion", 1, fill=True)
        pdf.cell(60, 8, "Resultado", 1, ln=1, fill=True)
        
        pdf.set_font("Arial", size=10)
        for test in test_results:
            # Usamos .get() para evitar errores si faltan datos
            t_name = str(test.get('test', ''))
            t_spec = str(test.get('spec', ''))
            t_res = str(test.get('result', ''))
            
            pdf.cell(60, 8, t_name, 1)
            pdf.cell(70, 8, t_spec, 1)
            pdf.cell(60, 8, t_res, 1, ln=1)

        # Observaciones
        pdf.ln(10)
        if "Observaciones" in content_dict:
            pdf.set_font("Arial", "B", 10)
            pdf.cell(0, 8, "Dictamen / Obs:", ln=1)
            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 6, str(content_dict["Observaciones"]))

        # --- AQUÍ ESTÁ LA MAGIA WEB ---
        # 1. Guardar temporalmente en el servidor
        temp_path = "/tmp/temp_cert.pdf" 
        pdf.output(temp_path)
        
        # 2. Leer ese archivo y convertirlo a código Base64
        with open(temp_path, "rb") as f:
            b64_pdf = base64.b64encode(f.read()).decode('utf-8')
        
        # 3. Lanzar la descarga en el navegador
        # Esto le dice a Flet: "Abre esta URL especial que contiene el PDF"
        page.launch_url(f"data:application/pdf;base64,{b64_pdf}")
        
        return True

    except Exception as e:
        print(f"Error generando PDF: {e}")
        return False
# --- FIN DE LA NUEVA FUNCIÓN ---
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

    # 3. ALMACÉN (RECEPCIÓN COMPLETA)
    def build_inventory_view():
        # Cargar lista de materias primas activas
        materials = db.execute_query("SELECT id, name, code FROM materials WHERE is_active=TRUE ORDER BY name", fetch=True)
        # Creamos opciones mostrando Nombre + Código
        mat_opts = [ft.dropdown.Option(key=str(m[0]), text=f"{m[1]} ({m[2]})") for m in materials] if materials else []
        
        # --- CAMPOS DEL FORMULARIO ---
        mat_dd = ft.Dropdown(label="Seleccionar Materia Prima", options=mat_opts, expand=True)
        
        # Fila 1: Lotes
        lot_int = ft.TextField(label="Lote Interno (Asignado)", expand=True)
        lot_ven = ft.TextField(label="Lote Proveedor", expand=True)
        
        # Fila 2: Origen
        manufacturer = ft.TextField(label="Fabricante", expand=True)
        qty = ft.TextField(label="Cantidad Recibida (kg)", keyboard_type=ft.KeyboardType.NUMBER, expand=True)
        
        # Fila 3: Caducidad
        # Usamos un TextField con hint para formato fecha (YYYY-MM-DD)
        expiry = ft.TextField(
            label="Fecha de Caducidad", 
            hint_text="YYYY-MM-DD (Ej: 2026-12-31)", 
            keyboard_type=ft.KeyboardType.DATETIME,
            expand=True
        )

        def receive_material(e):
            # 1. Validaciones Básicas
            if not all([mat_dd.value, lot_int.value, lot_ven.value, manufacturer.value, qty.value, expiry.value]):
                ft.SnackBar(ft.Text("⚠️ Todos los campos son obligatorios")).open = True
                page.update()
                return
            
            try:
                # 2. Insertar en Base de Datos
                query = """
                    INSERT INTO inventory 
                    (material_id, lot_internal, lot_vendor, manufacturer, expiry_date, quantity, status) 
                    VALUES (%s, %s, %s, %s, %s, %s, 'CUARENTENA')
                """
                params = (
                    mat_dd.value, 
                    lot_int.value, 
                    lot_ven.value, 
                    manufacturer.value, 
                    expiry.value, 
                    float(qty.value)
                )
                
                db.execute_query(query, params)
                
                # 3. Audit Trail
                log_audit(
                    current_user["name"], 
                    "RECEIPT", 
                    f"Ingreso: {lot_int.value} | Prov: {lot_ven.value} | Qty: {qty.value}"
                )

                # 4. Limpieza y Feedback
                ft.SnackBar(ft.Text(f"✅ Lote {lot_int.value} ingresado a Cuarentena")).open = True
                
                # Limpiar campos para la siguiente entrada
                lot_int.value = ""
                lot_ven.value = ""
                manufacturer.value = ""
                qty.value = ""
                expiry.value = ""
                page.update()

            except Exception as ex:
                logger.error(f"Error en recepción: {ex}")
                ft.SnackBar(ft.Text("❌ Error al guardar. Verifica el formato de fecha (YYYY-MM-DD).")).open = True
                page.update()

        # Diseño Responsivo (Mobile First) usando Columnas
        form_content = ft.Column([
            ft.Text("Recepción de Materiales", size=20, weight="bold"),
            ft.Divider(),
            mat_dd,
            ft.Row([lot_int, lot_ven], spacing=10), # En PC se ven lado a lado, en móvil se ajustan
            manufacturer,
            ft.Row([qty, expiry], spacing=10),
            ft.Container(height=20), # Espacio
            ft.ElevatedButton(
                "Ingresar al Almacén", 
                icon=ft.icons.SAVE_ALT, 
                style=ft.ButtonStyle(bgcolor="blue", color="white"),
                on_click=receive_material,
                width=1000 # Ancho completo
            )
        ], scroll=ft.ScrollMode.AUTO)

        content_column.controls = [ft.Container(content=form_content, padding=20)]
        page.update()
# 4. MUESTREO (MEJORADO: Fórmula N+1 y Descuento de Inventario)
    def build_sampling_view():
        # Traemos items en CUARENTENA con su cantidad actual
        items = db.execute_query(
            "SELECT i.id, m.name, i.lot_internal, i.quantity FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='CUARENTENA'", 
            fetch=True
        ) or []

        lv = ft.ListView(expand=True, spacing=10, padding=10)

        def open_sampling_dialog(item_id, name, lot, current_qty):
            # Campos de entrada
            tf_n = ft.TextField(label="N° de Cuñetes/Envases (N)", keyboard_type=ft.KeyboardType.NUMBER, autofocus=True)
            txt_formula = ft.Text("Envases a abrir (√N + 1): 0", size=16, weight="bold", color="blue")
            
            tf_removed = ft.TextField(label="Cantidad Muestreada (kg)", keyboard_type=ft.KeyboardType.NUMBER, value="0.0")
            
            # Texto informativo de stock actual
            txt_stock = ft.Text(f"Stock actual: {current_qty} kg", size=12, color="grey")

            # Función reactiva: Calcula la fórmula apenas el usuario escribe N
            def calculate_formula(e):
                try:
                    if not tf_n.value:
                        txt_formula.value = "Envases a abrir (√N + 1): 0"
                    else:
                        n = int(tf_n.value)
                        # Fórmula farmacéutica estándar: Redondear hacia arriba (Raíz de n) + 1
                        result = math.ceil(math.sqrt(n) + 1)
                        txt_formula.value = f"Envases a abrir (√N + 1): {result}"
                    page.update()
                except ValueError:
                    pass # Si escribe letras no hacemos nada

            tf_n.on_change = calculate_formula

            def save_sampling(e):
                try:
                    qty_removed = float(tf_removed.value)
                    
                    if qty_removed <= 0:
                        tf_removed.error_text = "Debe ser mayor a 0"
                        page.update()
                        return
                    
                    if qty_removed > current_qty:
                        tf_removed.error_text = "No puedes muestrear más de lo que existe"
                        page.update()
                        return

                    # 1. Calcular nuevo inventario
                    new_qty = current_qty - qty_removed
                    
                    # 2. Actualizar DB: Cambia estado a MUESTREADO y actualiza cantidad
                    db.execute_query(
                        "UPDATE inventory SET quantity=%s, status='MUESTREADO' WHERE id=%s",
                        (new_qty, item_id)
                    )
                    
                    # 3. Registrar en Audit Trail
                    log_audit(
                        current_user["name"], 
                        "SAMPLING", 
                        f"Muestreo Lote {lot}. Envases: {tf_n.value}. Retirado: {qty_removed}kg. Stock Final: {new_qty}kg"
                    )

                    page.dialog.open = False
                    ft.SnackBar(ft.Text(f"Muestreo registrado. Nuevo stock: {new_qty} kg")).open = True
                    build_sampling_view() # Recargar lista
                    page.update()

                except ValueError:
                    tf_removed.error_text = "Número inválido"
                    page.update()
                except Exception as ex:
                    logger.error(f"Error sampling: {ex}")

            # Construcción del Dialog
            dlg = ft.AlertDialog(
                title=ft.Text(f"Muestreo: {name}"),
                content=ft.Column([
                    ft.Text(f"Lote: {lot}"),
                    txt_stock,
                    ft.Divider(),
                    ft.Text("Cálculo de Muestra (OMS/GMP):"),
                    tf_n,
                    txt_formula,
                    ft.Divider(),
                    ft.Text("Ejecución:"),
                    tf_removed
                ], tight=True, width=300),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda e: setattr(dlg, 'open', False) or page.update()),
                    ft.ElevatedButton("Confirmar Muestreo", on_click=save_sampling)
                ]
            )
            page.dialog = dlg
            dlg.open = True
            page.update()

        # Renderizar la lista
        if not items:
            lv.controls.append(ft.Text("No hay materiales en Cuarentena pendientes de muestreo."))
        
        for i in items:
            # i = [id, name, lot_internal, quantity]
            lv.controls.append(
                ft.Card(
                    content=ft.ListTile(
                        leading=ft.Icon(ft.icons.SCIENCE, color="orange"),
                        title=ft.Text(f"{i[1]}"),
                        subtitle=ft.Text(f"Lote: {i[2]} | Stock: {i[3]} kg"),
                        trailing=ft.IconButton(
                            ft.icons.ARROW_FORWARD_IOS, 
                            tooltip="Realizar Muestreo",
                            on_click=lambda e, iid=i[0], n=i[1], l=i[2], q=i[3]: open_sampling_dialog(iid, n, l, q)
                        )
                    )
                )
            )

        content_column.controls = [ft.Text("Módulo de Muestreo", size=20, weight="bold"), lv]
        page.update()
    # 5. LABORATORIO (CON PDF BASE64 Y AUDIT TRAIL ARREGLADO)
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
                
                # Recolectar datos
                res_json = {f.data['test']: f.value for f in inputs}
                res_list = [{"test": f.data['test'], "spec": f.data['spec'], "result": f.value} for f in inputs]
                
                try:
                    # 1. Guardar resultados
                    db.execute_query("INSERT INTO lab_results (inventory_id, analyst, result_data, conclusion, analysis_num, bib_reference, reanalysis_date, observations) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                     (inv_id, current_user["name"], json.dumps(res_json), dd_con.value, tf_num.value, tf_ref.value, tf_re.value or None, tf_obs.value))
                    
                    # 2. Actualizar Estado
                    st = "LIBERADO" if dd_con.value == "APROBADO" else "RECHAZADO"
                    db.execute_query("UPDATE inventory SET status=%s WHERE id=%s", (st, inv_id))
                    
                    # 3. REGISTRAR EN AUDIT TRAIL (Esta es la línea que fallaba por espacios, aquí ya está corregida)
                    log_audit(current_user["name"], "LAB_RELEASE", f"Analisis Lote {lot}. Dictamen: {st}")
                    
                    # 4. Cerrar y actualizar UI
                    page.dialog.open = False
                    build_lab_view()
                    page.update()
                    
                    # 5. Generar PDF
                    open_pdf_in_browser(page, f"CoA_{lot}.pdf", {"Producto": mat_name, "Lote": lot, "Analisis": tf_num.value, "Dictamen": dd_con.value, "Observaciones": tf_obs.value}, res_list)

                except Exception as ex:
                    logger.error(f"Error saving lab results: {ex}")
                    ft.SnackBar(ft.Text("Error al guardar análisis")).open = True
                    page.update()

            page.dialog = ft.AlertDialog(title=ft.Text(f"Analisis {lot}"), content=ft.Column([tf_num, tf_ref] + inputs + [tf_obs, dd_con, tf_re], scroll=ft.ScrollMode.ALWAYS, height=500), actions=[ft.ElevatedButton("Guardar", on_click=save)])
            page.dialog.open = True
            page.update()

        for p in pending:
            lv.controls.append(ft.Card(content=ft.ListTile(title=ft.Text(p[1]), subtitle=ft.Text(p[2]), trailing=ft.IconButton(ft.icons.PLAY_ARROW, on_click=lambda e, x=p: open_analysis(x[0], x[3], x[1], x[2])))))
        content_column.controls = [ft.Text("Laboratorio", size=20, weight="bold"), lv]
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
                    generate_pdf(page, pdf_name, 
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
    # 7. AUDIT TRAIL (REDDISEÑADO PARA VERSE BIEN EN MOVIL)
    def build_audit_view():
        if current_user["role"] != "ADMIN":
            content_column.controls = [
                ft.Container(
                    content=ft.Text("ACCESO DENEGADO - SOLO ADMIN", color="white", weight="bold"),
                    bgcolor="red", padding=20, alignment=ft.alignment.center
                )
            ]
        else:
            # Traer datos
            logs = db.execute_query("SELECT timestamp, user_name, action, details FROM audit_trail ORDER BY id DESC LIMIT 50", fetch=True) or []
            
            # Usamos Column con scroll ACTIVADO. Esto arregla el error de pantalla blanca.
            log_col = ft.Column(scroll=ft.ScrollMode.ALWAYS, expand=True, spacing=10)
            
            if not logs:
                log_col.controls.append(ft.Text("No hay registros."))
            
            for l in logs:
                # Diseño tipo tarjeta (Card) que no falla en móvil
                card = ft.Container(
                    padding=10, 
                    border=ft.border.all(1, ft.colors.GREY_300), 
                    border_radius=8,
                    bgcolor="white",
                    content=ft.Column([
                        ft.Row([
                            ft.Text(str(l[0])[:19], size=12, weight="bold", color="blue"), # Fecha
                            ft.Container(content=ft.Text(l[2], size=10, color="white"), bgcolor="black", padding=5, border_radius=4) # Acción
                        ], alignment="spaceBetween"),
                        ft.Text(f"Usuario: {l[1]}", size=12, weight="bold"),
                        ft.Text(f"{l[3]}", size=12, italic=True) # Detalles
                    ])
                )
                log_col.controls.append(card)
            
            content_column.controls = [
                ft.Text("Auditoría del Sistema (Audit Trail)", size=20, weight="bold"),
                ft.Divider(),
                ft.Container(content=log_col, expand=True, height=500) # Forzamos altura o expandimos
            ]
            
        page.update()
            
        # 3. Consulta a Base de Datos
        # Traemos los últimos 100 movimientos
        logs = db.execute_query(
            "SELECT timestamp, user_name, action, details FROM audit_trail ORDER BY id DESC LIMIT 100", 
            fetch=True
        )

        # 4. Construcción de la Lista
        lv = ft.ListView(expand=True, spacing=10, padding=10)

        if not logs:
            lv.controls.append(ft.Text("No hay registros de auditoría aún."))
        else:
            for l in logs:
                # l[0]=Time, l[1]=User, l[2]=Action, l[3]=Details
                # Formateamos la fecha para que sea legible
                fecha_str = str(l[0])[:19] 
                
                lv.controls.append(
                    ft.Card(
                        elevation=2,
                        content=ft.Container(
                            padding=10,
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.icons.ACCESS_TIME, size=14, color="grey"),
                                    ft.Text(fecha_str, size=12, color="grey", weight="bold"),
                                    ft.Container(expand=True),
                                    ft.Badge(text=l[2], color="white", bgcolor="blue") # La Acción
                                ]),
                                ft.Divider(height=10, thickness=0.5),
                                ft.Row([
                                    ft.Text("Usuario:", weight="bold", size=12),
                                    ft.Text(l[1], size=12)
                                ]),
                                ft.Text(f"{l[3]}", size=13, italic=True) # Detalles
                            ])
                        )
                    )
                )

        # 5. Montaje Final
        header = ft.Row(
            [
                ft.Text("Audit Trail (ALCOA)", size=20, weight="bold"),
                ft.IconButton(ft.icons.REFRESH, on_click=refresh_logs, tooltip="Actualizar")
            ], 
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

        content_column.controls = [
            ft.Container(content=header, padding=10),
            lv
        ]
        page.update()
    build_login()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=port, host="0.0.0.0")

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

# Aumentar la recursividad para evitar errores en llamadas anidadas (p.ej., build_sampling_view -> page.update)
sys.setrecursionlimit(2000)

# --- CONFIGURACIÓN Y LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Definición global para almacenar el usuario activo
current_user = {"id": None, "name": "GUEST", "role": "GUEST"}

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
        # Definición de tablas actualizada (corregida la concatenación y columnas faltantes en lab_results)
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
                material_id INTEGER REFERENCES materials (id) ON DELETE CASCADE,
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
        ON CONFLICT DO NOTHING
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
# --- FUNCIÓN PDF CORREGIDA (Método Javascript) ---
# Se utiliza el nombre open_pdf_in_browser para ser consistente con el módulo LAB
# --- FUNCIÓN PDF CORREGIDA (Método Javascript) ---
# Se utiliza el nombre open_pdf_in_browser para ser consistente con el módulo LAB

def open_pdf_in_browser(page, filename, content_dict, test_results):
    try:
        pdf = FPDF()
        pdf.add_page()

        # DISEÑO DEL PDF
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, "CERTIFICADO DE ANALISIS", ln=1, align="C")

        pdf.set_font("Arial", size=10)
        pdf.ln(5)

        # Datos Generales
        for key, value in content_dict.items():
            if key not in ["Observaciones", "Conclusión"]:
                pdf.set_font("Arial", "B", 10)
                pdf.cell(50, 8, txt=f"{key}:", border=0)
                pdf.set_font("Arial", size=10)
                pdf.cell(0, 8, txt=str(value), ln=1, border=0)

        # Se incluye Dictamen/Observaciones en el área de datos generales
        if "Conclusión" in content_dict:
            pdf.set_font("Arial", "B", 10)
            pdf.cell(50, 8, txt="Dictamen:", border=0)
            pdf.set_font("Arial", size=10)
            pdf.cell(0, 8, txt=str(content_dict["Conclusión"]), ln=1, border=0)

        pdf.ln(5)

        # Tabla de Resultados
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", "B", 10)

        pdf.cell(60, 8, "Prueba", 1, fill=True)
        pdf.cell(70, 8, "Especificacion", 1, fill=True)
        pdf.cell(60, 8, "Resultado", 1, ln=1, fill=True)

        pdf.set_font("Arial", size=10)
        for test in test_results:
            t_name = str(test.get('test', ''))
            t_spec = str(test.get('spec', ''))
            t_res = str(test.get('result', ''))

            pdf.cell(60, 8, t_name, 1)
            pdf.cell(70, 8, t_spec, 1)
            pdf.cell(60, 8, t_res, 1, ln=1)

        # Observaciones
        pdf.ln(10)
        if "Observaciones" in content_dict and content_dict["Observaciones"]:
            pdf.set_font("Arial", "B", 10)
            pdf.cell(0, 8, "Observaciones Adicionales:", ln=1)
            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 6, str(content_dict["Observaciones"]))

        # --- GENERACIÓN Y DESCARGA ---
        temp_path = "/tmp/temp_cert.pdf"
        pdf.output(temp_path)

        with open(temp_path, "rb") as f:
            b64_pdf = base64.b64encode(f.read()).decode('utf-8')

        # TRUCO JAVASCRIPT para descarga directa
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
# --- UI ---
def main(page: ft.Page):
    page.title = "MASTER MP - PWA"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.window_width = 390  # Simulación Mobile
    
    # Mapa de todos los módulos disponibles
    MODULES_MAP = {
        "CATALOGO": {"icon": ft.icons.BOOK, "label": "Catálogo", "func": lambda: build_catalog_view(page, content_column, current_user)},
        "ALMACEN": {"icon": ft.icons.INVENTORY, "label": "Almacén", "func": lambda: build_inventory_view(page, content_column, current_user)},
        "MUESTREO": {"icon": ft.icons.SCIENCE, "label": "Muestreo", "func": lambda: build_sampling_view(page, content_column, current_user)},
        "LAB": {"icon": ft.icons.ASSIGNMENT, "label": "Lab", "func": lambda: build_lab_view(page, content_column, current_user)},
        "CONSULTA": {"icon": ft.icons.SEARCH, "label": "Consulta", "func": lambda: build_query_view(page, content_column, current_user)},
        "USUARIOS": {"icon": ft.icons.PEOPLE, "label": "Usuarios", "func": lambda: build_users_view(page, content_column, current_user)},
        "ADMIN": {"icon": ft.icons.SECURITY, "label": "Admin", "func": lambda: build_audit_view(page, content_column, current_user)},
    }
    
    # Permisos por Rol
    ROLE_PERMISSIONS = {
        "ADMIN": ["CATALOGO", "ALMACEN", "MUESTREO", "LAB", "CONSULTA", "USUARIOS", "ADMIN"],
        "CALIDAD": ["CATALOGO", "MUESTREO", "LAB", "CONSULTA"],
        "ALMACEN": ["ALMACEN", "CONSULTA"],
        "OPERADOR": ["ALMACEN"]
    }

    # Variables de control de UI (deben estar en el scope de main)
    current_modules = []
    content_column = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
    nav_bar = ft.NavigationBar(destinations=[], visible=False)
    
    # Definición de funciones auxiliares de navegación (se define on_change después de configurar la función)
    def change_tab(e, page, content_column, current_modules, MODULES_MAP):
        idx = e.control.selected_index
        if current_modules and idx < len(current_modules):
            module_key = current_modules[idx]
            content_column.controls.clear()
            build_func = MODULES_MAP[module_key]["func"]
            build_func()
            page.update()

    def configure_menu_for_role(role, page, nav_bar, current_modules, ROLE_PERMISSIONS, MODULES_MAP):
        current_modules.clear()
        allowed_keys = ROLE_PERMISSIONS.get(role, ["CONSULTA"])
        nav_destinations = []
        for key in allowed_keys:
            if key in MODULES_MAP:
                config = MODULES_MAP[key]
                current_modules.append(key)
                nav_destinations.append(
                    ft.NavigationDestination(icon=config["icon"], label=config["label"])
                )
        
        nav_bar.destinations = nav_destinations
        # Se establece el on_change aquí para usar las variables definidas
        nav_bar.on_change = lambda e: change_tab(e, page, content_column, current_modules, MODULES_MAP)
        nav_bar.visible = True
        page.update()

    # --- DIALOGOS DE CATALOGO (Se definen antes de build_catalog_view)

    def open_profile_dialog(page, material_id, material_name):
        
        def refresh_list():
            current_tests = db.execute_query(
                "SELECT mp.id, st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id = st.id WHERE mp.material_id = %s",
                (material_id,), fetch=True
            ) or []
            
            list_col.controls.clear()
            for t in current_tests:
                # t = [mp.id, st.name, mp.specification]
                list_col.controls.append(ft.ListTile(
                    title=ft.Text(t[1]),
                    subtitle=ft.Text(f"Spec: {t[2]}"),
                    trailing=ft.IconButton(ft.icons.DELETE, icon_color=ft.colors.RED, on_click=lambda e, pid=t[0]: delete_profile_item(pid))
                ))
            page.update()
        
        def delete_profile_item(pid):
            db.execute_query("DELETE FROM material_profile WHERE id=%s", (pid,))
            refresh_list()

        def add_test_to_profile(e):
            if not dd_tests.value or not spec_tf.value:
                spec_tf.error_text = "Selección y especificación requeridas"
                page.update()
                return

            try:
                db.execute_query(
                    "INSERT INTO material_profile (material_id, test_id, specification) VALUES (%s, %s, %s)",
                    (material_id, dd_tests.value, spec_tf.value)
                )
                spec_tf.value = ""
                refresh_list()
            except Exception as ex:
                logger.error(ex)
                page.snack_bar = ft.SnackBar(ft.Text("Error: La prueba ya está asignada a este material."))
                page.snack_bar.open = True
                page.update()

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
                ft.Row([dd_tests, spec_tf], alignment=ft.MainAxisAlignment.SPACE_AROUND),
                ft.ElevatedButton("Agregar Prueba al Perfil", on_click=add_test_to_profile),
                ft.Divider(),
                ft.Text("Pruebas Asignadas:"),
                list_col
            ], tight=True),
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def add_material_dialog(page, content_column, current_user):
        code = ft.TextField(label="Código")
        name = ft.TextField(label="Nombre")
        cat = ft.Dropdown(label="Categoría", options=[ft.dropdown.Option("API"), ft.dropdown.Option("EXCIPIENTE")])

        def save(e):
            if not code.value or not name.value or not cat.value:
                code.error_text = "Todos los campos son obligatorios"
                page.update()
                return

            db.execute_query("INSERT INTO materials (code, name, category) VALUES (%s, %s, %s)",
                             (code.value, name.value, cat.value))
            log_audit(current_user["name"], "CREATE_MAT", f"Created {code.value}")
            page.dialog.open = False
            build_catalog_view(page, content_column, current_user)
            
        page.dialog = ft.AlertDialog(title=ft.Text("Crear Material"), 
                                     content=ft.Column([code, name, cat], tight=True), 
                                     actions=[ft.TextButton("Guardar", on_click=save)])
        page.dialog.open = True
        page.update()

    def add_test_dialog(page, content_column, current_user):
        name = ft.TextField(label="Nombre de Prueba (Ej: pH)")
        method = ft.TextField(label="Método Referencia")

        def save(e):
            if not name.value or not method.value:
                name.error_text = "Todos los campos son obligatorios"
                page.update()
                return
            
            db.execute_query("INSERT INTO standard_tests (name, method) VALUES (%s, %s)", (name.value, method.value))
            page.dialog.open = False
            build_catalog_view(page, content_column, current_user)
            
        page.dialog = ft.AlertDialog(title=ft.Text("Crear Prueba Master"), 
                                     content=ft.Column([name, method], tight=True), 
                                     actions=[ft.TextButton("Guardar", on_click=save)])
        page.dialog.open = True
        page.update()
        
    def build_catalog_view(page, content_column, current_user):
        # Tabs internos: Materias vs Pruebas
        tab_content = ft.Column(expand=True)

        def render_catalog_content(index):
            tab_content.controls.clear()
            if index == 0: # MATERIAS PRIMAS
                materials = db.execute_query("SELECT id, code, name, is_active FROM materials ORDER BY id DESC", fetch=True) or []
                
                for m in materials:
                    tab_content.controls.append(
                        ft.Card(content=ft.ListTile(
                            leading=ft.Icon(ft.icons.CIRCLE, color=ft.colors.GREEN if m[3] else ft.colors.RED),
                            title=ft.Text(f"{m[1]} - {m[2]}"),
                            trailing=ft.IconButton(ft.icons.SETTINGS, tooltip="Configurar Perfil", 
                                                   on_click=lambda e, mid=m[0], name=m[2]: open_profile_dialog(page, mid, name))
                        ))
                    )
                # Botón para agregar materia
                tab_content.controls.insert(0, ft.ElevatedButton("Nueva Materia Prima", icon=ft.icons.ADD,
                                                                 on_click=lambda e: add_material_dialog(page, content_column, current_user)))
            
            elif index == 1: # PRUEBAS MASTER
                tests = db.execute_query("SELECT id, name, method FROM standard_tests ORDER BY name",
                                         fetch=True) or []
                for t in tests:
                    tab_content.controls.append(
                        ft.ListTile(title=ft.Text(t[1]), subtitle=ft.Text(f"Método: {t[2]}"),
                                     leading=ft.Icon(ft.icons.CHECK_BOX))
                    )
                tab_content.controls.insert(0, ft.ElevatedButton("Nueva Prueba Estándar", icon=ft.icons.ADD,
                                                                 on_click=lambda e: add_test_dialog(page, content_column, current_user)))
            page.update()

        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(text="Materias Primas", icon=ft.icons.LAYERS),
                ft.Tab(text="Pruebas Master", icon=ft.icons.LIST_ALT),
            ],
            on_change=lambda e: render_catalog_content(e.control.selected_index)
        )

        content_column.controls = [ft.Text("Gestión de Catálogos", size=20, weight="bold"), tabs, tab_content]
        render_catalog_content(0)
        page.update()

    # 3. ALMACÉN (RECEPCIÓN COMPLETA)
    def build_inventory_view(page, content_column, current_user):
        # Cargar lista de materias primas activas
        materials = db.execute_query("SELECT id, name, code FROM materials WHERE is_active=TRUE ORDER BY name", fetch=True) or []
        
        # Creamos opciones mostrando Nombre + Código
        mat_opts = [ft.dropdown.Option(key=str(m[0]), text=f"{m[1]} ({m[2]})") for m in materials] if materials else []
        
        # --- CAMPOS DEL FORMULARIO
        mat_dd = ft.Dropdown(label="Seleccionar Materia Prima", options=mat_opts, expand=True)
        # Fila 1: Lotes
        lot_int = ft.TextField(label="Lote Interno (Asignado)", expand=True)
        lot_ven = ft.TextField(label="Lote Proveedor", expand=True)
        # Fila 2: Origen
        manufacturer = ft.TextField(label="Fabricante", expand=True)
        qty = ft.TextField(label="Cantidad Recibida (kg)", keyboard_type=ft.KeyboardType.NUMBER, expand=True)
        
        # Fila 3: Caducidad
        expiry = ft.TextField(
            label="Fecha de Caducidad",
            hint_text="YYYY-MM-DD (Ej: 2026-12-31)",
            keyboard_type=ft.KeyboardType.DATETIME,
            expand=True
        )

        def receive_material(e):
            # 1. Validaciones Básicas
            if not all([mat_dd.value, lot_int.value, lot_ven.value, manufacturer.value, qty.value, expiry.value]):
                page.snack_bar = ft.SnackBar(ft.Text("Todos los campos son obligatorios"))
                page.snack_bar.open = True
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
                page.snack_bar = ft.SnackBar(ft.Text(f"Lote {lot_int.value} ingresado a Cuarentena"))
                page.snack_bar.open = True
                
                # Limpiar campos para la siguiente entrada
                lot_int.value = ""
                lot_ven.value = ""
                manufacturer.value = ""
                qty.value = ""
                expiry.value = ""
                mat_dd.value = None # Deseleccionar
                page.update()
                
            except Exception as ex:
                logger.error(f"Error en recepción: {ex}")
                page.snack_bar = ft.SnackBar(ft.Text("Error al guardar. Verifica el formato de fecha (YYYY-MM-DD)."))
                page.snack_bar.open = True
                page.update()

        # Diseño Responsivo (Mobile First)
        form_content = ft.Column([
            ft.Text("Recepción de Materiales", size=20, weight="bold"),
            ft.Divider(),
            mat_dd,
            ft.Row([lot_int, lot_ven], spacing=10),
            manufacturer,
            ft.Row([qty, expiry], spacing=10),
            ft.Container(height=20),
            ft.ElevatedButton(
                "Ingresar al Almacén",
                icon=ft.icons.SAVE_ALT,
                style=ft.ButtonStyle(bgcolor=ft.colors.BLUE, color=ft.colors.WHITE),
                on_click=receive_material,
                width=float('inf')
            )
        ], scroll=ft.ScrollMode.AUTO)

        content_column.controls = [ft.Container(content=form_content, padding=20)]
        page.update()
# 4. MUESTREO (MEJORADO: Fórmula N+1 y Descuento de Inventario)
    def build_sampling_view(page, content_column, current_user):
        # Traemos items en CUARENTENA con su cantidad actual
        items = db.execute_query(
            "SELECT i.id, m.name, i.lot_internal, i.quantity FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='CUARENTENA'",
            fetch=True
        ) or []
        
        lv = ft.ListView(expand=True, spacing=10, padding=10)

        def open_sampling_dialog(item_id, name, lot, current_qty):
            # Campos de entrada
            tf_n = ft.TextField(label="N° de Cuñetes/Envases (N)", keyboard_type=ft.KeyboardType.NUMBER, autofocus=True)
            # Corregido: caracteres especiales rotos
            txt_formula = ft.Text("Envases a abrir (√N + 1): 0", size=16, weight="bold", color=ft.colors.BLUE)
            tf_removed = ft.TextField(label="Cantidad Muestreada (kg)", keyboard_type=ft.KeyboardType.NUMBER, value="0.0")
            
            # Texto informativo de stock actual
            txt_stock = ft.Text(f"Stock actual: {current_qty} kg", size=12, color=ft.colors.GREY)

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
                    tf_removed.error_text = None
                    
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
                    page.snack_bar = ft.SnackBar(ft.Text(f"Muestreo registrado. Nuevo stock: {new_qty} kg"))
                    page.snack_bar.open = True
                    build_sampling_view(page, content_column, current_user) # Recargar lista
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
                        leading=ft.Icon(ft.icons.SCIENCE, color=ft.colors.ORANGE),
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
    def build_lab_view(page, content_column, current_user):
        # Corregido: Query roto
        pending = db.execute_query("SELECT i.id, m.name, i.lot_internal, i.material_id FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.status='MUESTREADO'", fetch=True) or []
        lv = ft.ListView(expand=True, spacing=10)
        
        def open_analysis(inv_id, mat_id, mat_name, lot):
            # Corregido: Query roto
            profile = db.execute_query("SELECT st.name, mp.specification FROM material_profile mp JOIN standard_tests st ON mp.test_id = st.id WHERE mp.material_id = %s", (mat_id,), fetch=True)
            
            if not profile:
                page.snack_bar = ft.SnackBar(ft.Text("Sin perfil de pruebas. Configure el material en Catálogo."))
                page.snack_bar.open = True
                page.update()
                return
            
            tf_num = ft.TextField(label="No. Análisis")
            tf_ref = ft.TextField(label="Referencia")
            tf_obs = ft.TextField(label="Obs", multiline=True)
            tf_re = ft.TextField(label="Fecha Reanálisis (YYYY-MM-DD)")
            dd_con = ft.Dropdown(label="Dictamen", options=[ft.dropdown.Option("APROBADO"), ft.dropdown.Option("RECHAZADO")], value="APROBADO")
            # Corregido: sintaxis de list comprehension rota
            inputs = [ft.TextField(label=f"{p[0]} ({p[1]})", data={"test": p[0], "spec": p[1]}) for p in profile]
            
            def save(e):
                if not tf_num.value: 
                    tf_num.error_text = "Requerido"
                    page.update()
                    return
                
                # Recolectar datos
                res_json = {f.data['test']: f.value for f in inputs if f.data and f.value}
                res_list = [{"test": f.data['test'], "spec": f.data['spec'], "result": f.value} for f in inputs if f.data]

                try:
                    # 1. Guardar resultados
                    query = """
                    INSERT INTO lab_results (inventory_id, analyst, result_data, conclusion,
                    analysis_num, bib_reference, reanalysis_date, observations)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    params = (
                        inv_id, current_user["name"], json.dumps(res_json), dd_con.value, tf_num.value,
                        tf_ref.value, tf_re.value or None, tf_obs.value
                    )
                    db.execute_query(query, params)
                    
                    # 2. Actualizar Estado
                    st = "LIBERADO" if dd_con.value == "APROBADO" else "RECHAZADO"
                    db.execute_query("UPDATE inventory SET status=%s WHERE id=%s", (st, inv_id))
                    
                    # 3. REGISTRAR EN AUDIT TRAIL
                    log_audit(current_user["name"], "LAB_RELEASE", f"Analisis Lote {lot}. Dictamen: {st}")
                    
                    # 4. Cerrar y actualizar UI
                    page.dialog.open = False
                    build_lab_view(page, content_column, current_user)
                    page.update()
                    
                    # 5. Generar PDF
                    # Agregamos la conclusión a content_dict
                    pdf_content = {"Producto": mat_name, "Lote": lot, "Analisis": tf_num.value, 
                                   "Conclusión": dd_con.value, "Observaciones": tf_obs.value}
                    open_pdf_in_browser(page, f"CoA_{lot}.pdf", pdf_content, res_list)
                    
                except Exception as ex:
                    logger.error(f"Error saving lab results: {ex}")
                    page.snack_bar = ft.SnackBar(ft.Text("Error al guardar análisis. Revise formato de fecha o datos."))
                    page.snack_bar.open = True
                    page.update()

            # Corregido: acciones rotas y sintaxis de AlertDialog
            dlg_content = ft.Column([tf_num, tf_ref] + inputs + [tf_obs, dd_con, tf_re], scroll=ft.ScrollMode.ALWAYS, height=500)
            page.dialog = ft.AlertDialog(title=ft.Text(f"Analisis {lot}"), 
                                         content=dlg_content,
                                         actions=[ft.ElevatedButton("Guardar", on_click=save)])
            page.dialog.open = True
            page.update()

        for p in pending:
            # Corregido: trailing roto
            lv.controls.append(ft.Card(content=ft.ListTile(title=ft.Text(p[1]), subtitle=ft.Text(p[2]),
                                                         trailing=ft.IconButton(ft.icons.PLAY_ARROW, 
                                                                               on_click=lambda e, x=p: open_analysis(x[0], x[3], x[1], x[2])))))
        
        content_column.controls = [ft.Text("Laboratorio", size=20, weight="bold"), lv]
        page.update()
# 6. MÓDULO DE CONSULTA Y CERTIFICADOS
    def build_query_view(page, content_column, current_user):
        search_tf = ft.TextField(label="Buscar por Lote o Nombre", suffix_icon=ft.icons.SEARCH, expand=True)
        results_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

        def perform_search(e):
            term = f"%{search_tf.value or ''}%"
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
                status_color = ft.colors.GREEN if item[4] == "LIBERADO" else ft.colors.RED if item[4] == "RECHAZADO" else ft.colors.ORANGE
                
                results_col.controls.append(
                    ft.Card(
                        content=ft.ListTile(
                            leading=ft.Icon(ft.icons.CIRCLE, color=status_color),
                            title=ft.Text(f"{item[2]} ({item[1]})"),
                            subtitle=ft.Text(f"Lote: {item[3]} | Estado: {item[4]}"),
                            trailing=ft.IconButton(ft.icons.VISIBILITY, tooltip="Ver Detalles / CoA",
                                                   on_click=lambda e, iid=item[0], name=item[2], lot=item[3]: show_full_details(page, iid, name, lot))
                        )
                    )
                )
            
            page.update()

    def show_full_details(page, inv_id, mat_name, lot):
        # 1. Obtener Datos Generales
        inv_data = db.execute_query(
            "SELECT lot_vendor, manufacturer, quantity, expiry_date, status, material_id FROM inventory WHERE id=%s",
            (inv_id,), fetch=True
        )[0]
        
        # 2. Obtener Resultados de Laboratorio (si existen)
        lab_data = db.execute_query(
            "SELECT analyst, result_data, conclusion, date_analyzed, analysis_num, bib_reference, observations FROM lab_results WHERE inventory_id=%s",
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
        
        # 3. Si hay análisis, mostrar tabla comparativa y botón de certificado
        if lab_data:
            res = lab_data[0] # Tomamos el primer análisis
            
            # --- CORRECCIÓN CRÍTICA AQUÍ ---
            # Si res[1] ya es dict (por JSONB), lo usamos directo. Si es texto, lo convertimos.
            if isinstance(res[1], dict):
                results_json = res[1]
            else:
                results_json = json.loads(res[1])
            # -------------------------------
            
            conclusion = res[2]
            observations = res[6]
            
            details_controls.append(ft.Text(f"Resultados de Calidad ({res[3]}):", weight="bold"))
            details_controls.append(ft.Text(f"Analista: {res[0]}"))
            details_controls.append(ft.Text(f"No. Análisis: {res[4]}"))
            details_controls.append(ft.Text(f"Referencia: {res[5]}"))
            details_controls.append(ft.Text(f"Conclusión: {conclusion}", 
                                          color=ft.colors.GREEN if conclusion == "APROBADO" else ft.colors.RED,
                                          weight="bold"))
            
            # Reconstruir tabla comparativa (Specs vs Resultado)
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
            
            # Observaciones en detalle
            if observations:
                details_controls.append(ft.Text("Observaciones:", weight="bold"))
                details_controls.append(ft.Text(observations, italic=True))
            
            # --- COMPONENTE DE CERTIFICADO RECUPERADO ---
            def print_coa(e):
                pdf_name = f"CoA_REPRINT_{lot}.pdf"
                pdf_content = {
                    "Producto": mat_name, 
                    "Lote": lot, 
                    "Fabricante": str(inv_data[1] or 'N/A'),
                    "Conclusión": conclusion, 
                    "Observaciones": observations
                }
                # Llamada a la función global open_pdf_in_browser
                success = open_pdf_in_browser(page, pdf_name, pdf_content, pdf_data_list)
                
                if success:
                    page.snack_bar = ft.SnackBar(ft.Text(f"Certificado generado: {pdf_name}"))
                else:
                    page.snack_bar = ft.SnackBar(ft.Text("Error generando el PDF"))
                page.snack_bar.open = True
                page.update()

            details_controls.append(ft.Container(height=20))
            details_controls.append(ft.ElevatedButton(
                "Descargar Certificado (PDF)", 
                icon=ft.icons.PICTURE_AS_PDF, 
                bgcolor=ft.colors.GREEN,
                color=ft.colors.WHITE,
                on_click=print_coa
            ))
            # ---------------------------------------------

        else:
            details_controls.append(ft.Text("⚠️ Este material aún no ha sido analizado por el laboratorio.", color=ft.colors.ORANGE))

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

    # 7. GESTIÓN DE USUARIOS (SOLO ADMIN)
    # Las funciones open_edit_user y render_users se anidan dentro de build_users_view para simplificar el scope
    def build_users_view(page, content_column, current_user):
        
        if current_user["role"] != "ADMIN":
            content_column.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.icons.SECURITY, size=60, color=ft.colors.RED),
                        ft.Text("ACCESO RESTRINGIDO", size=20, weight="bold"),
                        ft.Text("Solo Administradores pueden gestionar usuarios.")
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    alignment=ft.alignment.center, padding=20
                )
            ]
            page.update()
            return
            
        users_list = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=10)
        
        # 4. Diálogo EDITAR (Bloquear/Desbloquear)
        def open_edit_user(page, uid, name, role, locked):
            dd_role = ft.Dropdown(
                label="Rol",
                options=[
                    ft.dropdown.Option("OPERADOR"),
                    ft.dropdown.Option("ALMACEN"),
                    ft.dropdown.Option("CALIDAD"),
                    ft.dropdown.Option("ADMIN"),
                ],
                value=role
            )
            # Switch para Bloqueo
            sw_lock = ft.Switch(label="Usuario Bloqueado (Acceso Denegado)", value=locked)

            def save_edit(e):
                # Actualizamos Rol y Estado de Bloqueo
                db.execute_query(
                    "UPDATE users SET role=%s, is_locked=%s WHERE id=%s",
                    (dd_role.value, sw_lock.value, uid)
                )
                
                action_desc = "BLOQUEO" if sw_lock.value else "DESBLOQUEO"
                log_audit(current_user["name"], "USER_EDIT", f"{action_desc} de usuario {name}. Rol: {dd_role.value}")
                
                page.dialog.open = False
                render_users(page, users_list, current_user, open_edit_user)
                page.update()

            dlg_content = ft.Column([
                ft.Text("Gestión de Acceso", weight="bold"),
                dd_role,
                ft.Divider(),
                sw_lock
            ], tight=True, width=300)

            page.dialog = ft.AlertDialog(
                title=ft.Text(f"Editar: {name}"),
                content=dlg_content,
                actions=[ft.ElevatedButton("Guardar Cambios", on_click=save_edit)]
            )
            page.dialog.open = True
            page.update()
            
        def render_users(page, users_list, current_user, open_edit_user_func):
            users_list.controls.clear()
            # Consultamos usuarios (sin contraseña por seguridad)
            data = db.execute_query("SELECT id, username, role, is_locked FROM users ORDER BY id ASC", fetch=True) or []
            
            for u in data:
                u_id, u_name, u_role, u_locked = u
                
                # Estilo visual según estado
                icon_code = ft.icons.VERIFIED_USER
                icon_color = ft.colors.BLUE
                status_txt = "ACTIVO"
                if u_locked:
                    icon_code = ft.icons.BLOCK
                    icon_color = ft.colors.GREY
                    status_txt = "BLOQUEADO"
                elif u_role == "ADMIN":
                    icon_code = ft.icons.SECURITY
                    icon_color = ft.colors.RED
                
                # Tarjeta de Usuario
                card = ft.Card(
                    content=ft.ListTile(
                        leading=ft.Icon(icon_code, color=icon_color, size=30),
                        title=ft.Text(u_name, weight="bold"),
                        subtitle=ft.Text(f"Rol: {u_role} | Estado: {status_txt}"),
                        trailing=ft.IconButton(
                            ft.icons.EDIT,
                            tooltip="Editar Permisos / Bloquear",
                            on_click=lambda e, uid=u_id, name=u_name, role=u_role, locked=u_locked: open_edit_user_func(page, uid, name, role, locked)
                        )
                    )
                )
                users_list.controls.append(card)
            
            page.update()

        def open_add_user(page, users_list, current_user, open_edit_user):
            tf_user = ft.TextField(label="Nombre de Usuario")
            tf_pass = ft.TextField(label="Contraseña", password=True, can_reveal_password=True)
            dd_role = ft.Dropdown(
                label="Rol Asignado",
                options=[
                    ft.dropdown.Option("OPERADOR"),
                    ft.dropdown.Option("ALMACEN"),
                    ft.dropdown.Option("CALIDAD"),
                    ft.dropdown.Option("ADMIN"),
                ],
                value="OPERADOR"
            )
            
            def save_new(e):
                if not tf_user.value or not tf_pass.value:
                    tf_user.error_text = "Requerido"
                    page.update()
                    return
                
                try:
                    # Insertamos con is_locked = FALSE por defecto
                    db.execute_query(
                        "INSERT INTO users (username, password, role, is_locked) VALUES (%s, %s, %s, FALSE)",
                        (tf_user.value, tf_pass.value, dd_role.value)
                    )
                    log_audit(current_user["name"], "USER_CREATE", f"Creo usuario: {tf_user.value} como {dd_role.value}")
                    
                    page.dialog.open = False
                    render_users(page, users_list, current_user, open_edit_user)
                    page.snack_bar = ft.SnackBar(ft.Text("Usuario creado exitosamente"))
                    page.snack_bar.open = True
                    page.update()
                    
                except Exception:
                    page.snack_bar = ft.SnackBar(ft.Text("Error: El usuario ya existe"))
                    page.snack_bar.open = True
                    page.update()
            
            dlg_content = ft.Column([tf_user, tf_pass, dd_role], tight=True, width=300)
            page.dialog = ft.AlertDialog(
                title=ft.Text("Nuevo Usuario"),
                content=dlg_content,
                actions=[ft.ElevatedButton("Crear", on_click=save_new)]
            )
            page.dialog.open = True
            page.update()

        # Montaje de la pantalla
        render_users(page, users_list, current_user, open_edit_user)
        content_column.controls = [
            ft.Row([
                ft.Text("Gestión de Usuarios", size=20, weight="bold"),
                ft.ElevatedButton("Nuevo Usuario", icon=ft.icons.PERSON_ADD, 
                                 on_click=lambda e: open_add_user(page, users_list, current_user, open_edit_user))
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(),
            users_list
        ]
        page.update()
        
    def build_audit_view(page, content_column, current_user):
        
        if current_user["role"] != "ADMIN":
            content_column.controls = [
                ft.Container(
                    content=ft.Text("ACCESO DENEGADO - SOLO ADMIN", color=ft.colors.WHITE, weight="bold"),
                    bgcolor=ft.colors.RED, padding=20, alignment=ft.alignment.center
                )
            ]
            page.update()
            return

        def refresh_logs(e=None):
            # Traer datos
            logs = db.execute_query("SELECT timestamp, user_name, action, details FROM audit_trail ORDER BY id DESC LIMIT 50", fetch=True) or []
            
            log_col.controls.clear()
            if not logs:
                log_col.controls.append(ft.Text("No hay registros."))
            
            for l in logs:
                # Diseño tipo tarjeta (Card) que no falla en móvil
                card = ft.Container(
                    padding=10,
                    border=ft.border.all(1, ft.colors.GREY_300),
                    border_radius=8,
                    bgcolor=ft.colors.WHITE,
                    content=ft.Column([
                        ft.Row([
                            ft.Text(str(l[0])[:19], size=12, weight="bold", color=ft.colors.BLUE), # Fecha
                            ft.Container(content=ft.Text(l[2], size=10, color=ft.colors.WHITE), bgcolor=ft.colors.BLACK, padding=5,
                                         border_radius=4) # Acción
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Text(f"Usuario: {l[1]}", size=12, weight="bold"),
                        ft.Text(f"{l[3]}", size=12, italic=True) # Detalles
                    ])
                )
                log_col.controls.append(card)
            
            content_column.controls = [
                ft.Text("Auditoría del Sistema (Audit Trail)", size=20, weight="bold"),
                ft.Divider(),
                ft.Container(content=ft.Column([
                    ft.Row([ft.Text("Registros (últimos 50)", weight="bold"), 
                            ft.IconButton(ft.icons.REFRESH, on_click=refresh_logs, tooltip="Actualizar")],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    log_col
                ], scroll=ft.ScrollMode.ALWAYS, expand=True, height=500))
            ]
            page.update()
            
        # Usamos Column con scroll ACTIVADO. Esto arregla el error de pantalla blanca.
        log_col = ft.Column(scroll=ft.ScrollMode.ALWAYS, expand=True, spacing=10)
        refresh_logs() # Carga inicial
# --- LOGIN ---
    def build_login(page, content_column, nav_bar, current_user, configure_menu_for_role, current_modules, MODULES_MAP):
        user_tf = ft.TextField(label="Usuario")
        pass_tf = ft.TextField(label="Contraseña", password=True, can_reveal_password=True)
        error_txt = ft.Text(color=ft.colors.RED, weight="bold")

        def auth(e):
            # Indices: 0=id, 1=username, 2=password, 3=role, 4=is_locked
            # Corregido: Query roto
            query = "SELECT id, username, password, role, is_locked FROM users WHERE username=%s AND password=%s"
            res = db.execute_query(query, (user_tf.value, pass_tf.value), fetch=True)
            
            if res:
                # El usuario existe, ahora verificamos si está bloqueado
                is_locked = res[0][4]
                
                if is_locked:
                    # SI ESTÁ BLOQUEADO: Mostramos error y NO entramos
                    error_txt.value = "ACCESO DENEGADO: Usuario Bloqueado."
                    page.update()
                else:
                    # SI NO ESTÁ BLOQUEADO: Procedemos normalmente
                    current_user["id"] = res[0][0] # Guardar ID
                    current_user["name"] = res[0][1]
                    current_user["role"] = res[0][3]
                    
                    # 1. Configuramos el menú según su rol
                    configure_menu_for_role(current_user["role"], page, nav_bar, current_modules, ROLE_PERMISSIONS, MODULES_MAP)
                    
                    # 2. Limpiamos pantalla y cargamos la app
                    page.clean()
                    page.add(content_column)
                    page.navigation_bar = nav_bar
                    
                    # 3. Intentamos cargar la primera pantalla disponible
                    if current_modules:
                        # Si usamos el menú dinámico
                        first_func = MODULES_MAP[current_modules[0]]["func"]
                        first_func()
                    else:
                        # Si no usamos menú dinámico, cargamos catálogo por defecto
                        build_catalog_view(page, content_column, current_user)
                    
                    page.update()
            else:
                error_txt.value = "Usuario o contraseña incorrectos"
                page.update()

        page.add(ft.Container(
            content=ft.Column([
                ft.Icon(ft.icons.LOCAL_PHARMACY, size=60, color=ft.colors.BLUE),
                ft.Text("MASTER MP", size=24, weight="bold"),
                user_tf, pass_tf, error_txt,
                ft.ElevatedButton("Entrar", on_click=auth)
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            alignment=ft.alignment.center, padding=20, expand=True
        ))
    
    # Llamada inicial de la aplicación
    build_login(page, content_column, nav_bar, current_user, configure_menu_for_role, current_modules, MODULES_MAP)

# --- APP EXECUTION ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=port, host="0.0.0.0")

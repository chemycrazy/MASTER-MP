import flet as ft
import os
import psycopg2
import logging
import datetime
import math
from contextlib import contextmanager
from fpdf import FPDF

# --- CONFIGURACIÓN Y LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Variable de entorno para la BD (Por defecto busca local si no hay env)
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:R57667115#gD@db.rhuudiwamxpfkinpgkzs.supabase.co:5432/postgres")

# --- CAPA DE DATOS (DATABASE) ---
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
        """Inicializa las tablas si no existen."""
        commands = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(50) NOT NULL,
                role VARCHAR(20) DEFAULT 'OPERADOR',
                is_locked BOOLEAN DEFAULT FALSE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS materials (
                id SERIAL PRIMARY KEY,
                code VARCHAR(20) UNIQUE,
                name VARCHAR(100),
                category VARCHAR(50),
                is_active BOOLEAN DEFAULT TRUE,
                specifications TEXT 
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS inventory (
                id SERIAL PRIMARY KEY,
                material_id INTEGER REFERENCES materials(id),
                lot_internal VARCHAR(50),
                lot_vendor VARCHAR(50),
                manufacturer VARCHAR(100),
                supplier VARCHAR(100),
                expiry_date DATE,
                quantity FLOAT,
                status VARCHAR(20) DEFAULT 'CUARENTENA'
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS lab_results (
                id SERIAL PRIMARY KEY,
                inventory_id INTEGER REFERENCES inventory(id),
                analysis_num VARCHAR(20),
                analyst VARCHAR(50),
                result_data TEXT,
                conclusion VARCHAR(20),
                date_analyzed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_trail (
                id SERIAL PRIMARY KEY,
                user_name VARCHAR(50),
                action VARCHAR(50),
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        ]
        
        # Crear admin por defecto si no existe
        create_admin = "INSERT INTO users (username, password, role) VALUES ('admin', 'admin', 'ADMIN') ON CONFLICT DO NOTHING"
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    for cmd in commands:
                        cur.execute(cmd)
                    cur.execute(create_admin)
                    conn.commit()
            logger.info("Base de datos inicializada correctamente.")
        except Exception as e:
            logger.critical(f"Fallo crítico al inicializar DB: {e}")

db = DBManager()

# --- FUNCIONES AUXILIARES (ALCOA, PDF) ---

def log_audit(user, action, details):
    """Registra cualquier cambio crítico (ALCOA)."""
    db.execute_query(
        "INSERT INTO audit_trail (user_name, action, details) VALUES (%s, %s, %s)",
        (user, action, details)
    )

def generate_pdf(filename, content_dict):
    """Genera un Certificado de Calidad simple."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="CERTIFICADO DE CALIDAD", ln=1, align="C")
    
    for key, value in content_dict.items():
        pdf.cell(200, 10, txt=f"{key}: {value}", ln=1, align="L")
    
    pdf.output(filename)
    return filename

# --- UI COMPONENTES Y VISTAS ---

def main(page: ft.Page):
    page.title = "MASTER MP - Pharma PWA"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.ADAPTIVE
    # Configuración Mobile-First
    page.window_width = 390
    page.window_height = 844
    
    # Estado global simple
    current_user = {"name": None, "role": None}

    # --- NAVEGACIÓN ---
    def change_tab(e):
        idx = e.control.selected_index
        content_column.controls.clear()
        
        if idx == 0: build_catalog_view()
        elif idx == 1: build_inventory_view()
        elif idx == 2: build_sampling_view()
        elif idx == 3: build_lab_view()
        elif idx == 4: build_audit_view()
        
        page.update()

    nav_bar = ft.NavigationBar(
        destinations=[
            ft.NavigationDestination(icon=ft.icons.BOOK, label="Catálogo"),
            ft.NavigationDestination(icon=ft.icons.INVENTORY, label="Almacén"),
            ft.NavigationDestination(icon=ft.icons.SCIENCE, label="Muestreo"),
            ft.NavigationDestination(icon=ft.icons.ASSIGNMENT, label="Lab"),
            ft.NavigationDestination(icon=ft.icons.SECURITY, label="Admin"),
        ],
        on_change=change_tab,
        visible=False 
    )
    
    content_column = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    # --- VISTAS ---

    # 1. LOGIN
    def login_success(user_data):
        current_user["name"] = user_data[1]
        current_user["role"] = user_data[3]
        nav_bar.visible = True
        page.clean()
        page.add(content_column)
        page.navigation_bar = nav_bar
        build_catalog_view() # Inicio por defecto
        page.update()

    def build_login():
        user_tf = ft.TextField(label="Usuario")
        pass_tf = ft.TextField(label="Contraseña", password=True, can_reveal_password=True)
        error_txt = ft.Text(color="red")

        def auth(e):
            res = db.execute_query(
                "SELECT * FROM users WHERE username=%s AND password=%s AND is_locked=FALSE", 
                (user_tf.value, pass_tf.value), fetch=True
            )
            if res:
                login_success(res[0])
            else:
                error_txt.value = "Credenciales inválidas o usuario bloqueado."
                page.update()

        page.add(
            ft.Container(
                content=ft.Column([
                    ft.Icon(ft.icons.PHARMACY, size=50, color="blue"),
                    ft.Text("MASTER MP", size=24, weight="bold"),
                    user_tf, pass_tf, error_txt,
                    ft.ElevatedButton("Ingresar", on_click=auth)
                ], alignment=ft.MainAxisAlignment.CENTER),
                padding=20,
                alignment=ft.alignment.center
            )
        )

    # 2. CATÁLOGO DE MATERIAS PRIMAS
    def build_catalog_view():
        materials = db.execute_query("SELECT id, code, name, is_active FROM materials ORDER BY id DESC", fetch=True) or []
        
        lv = ft.ListView(expand=1, spacing=10, padding=20)
        
        for m in materials:
            status_color = "green" if m[3] else "red"
            lv.controls.append(
                ft.Card(
                    content=ft.ListTile(
                        leading=ft.Icon(ft.icons.CIRCLE, color=status_color),
                        title=ft.Text(f"{m[1]} - {m[2]}"),
                        subtitle=ft.Text("Activo" if m[3] else "Inactivo"),
                        trailing=ft.PopupMenuButton(
                            items=[
                                ft.PopupMenuItem(text="Editar/ALCOA", on_click=lambda e, mid=m[0]: edit_material_dialog(mid)),
                                ft.PopupMenuItem(text="Cambiar Estado", on_click=lambda e, mid=m[0]: toggle_material(mid)),
                            ]
                        )
                    )
                )
            )

        def add_material_dialog(e):
            code = ft.TextField(label="Código")
            name = ft.TextField(label="Nombre")
            cat = ft.Dropdown(label="Categoría", options=[ft.dropdown.Option("API"), ft.dropdown.Option("EXCIPIENTE")])
            specs = ft.TextField(label="Especificaciones (Pruebas)", multiline=True)
            
            def save(e):
                if not all([code.value, name.value]): return
                db.execute_query(
                    "INSERT INTO materials (code, name, category, specifications) VALUES (%s, %s, %s, %s)",
                    (code.value, name.value, cat.value, specs.value)
                )
                log_audit(current_user["name"], "CREATE_MATERIAL", f"Creado {code.value}")
                dlg.open = False
                build_catalog_view()
                page.update()

            dlg = ft.AlertDialog(
                title=ft.Text("Nueva Materia Prima"),
                content=ft.Column([code, name, cat, specs], tight=True),
                actions=[ft.TextButton("Guardar", on_click=save)]
            )
            page.dialog = dlg
            dlg.open = True
            page.update()

        content_column.controls = [
            ft.Row([ft.Text("Catálogo", size=20, weight="bold"), ft.IconButton(ft.icons.ADD, on_click=add_material_dialog)], alignment="spaceBetween"),
            lv
        ]
        page.update()

    # FUNCIONES AUXILIARES CATALOGO
    def toggle_material(mid):
        db.execute_query("UPDATE materials SET is_active = NOT is_active WHERE id=%s", (mid,))
        log_audit(current_user["name"], "STATUS_CHANGE", f"Material ID {mid} cambiado")
        build_catalog_view()

    def edit_material_dialog(mid):
        # ALCOA: Justificar cambios
        data = db.execute_query("SELECT name, specifications FROM materials WHERE id=%s", (mid,), fetch=True)[0]
        name_tf = ft.TextField(label="Nombre", value=data[0])
        specs_tf = ft.TextField(label="Specs", value=data[1], multiline=True)
        reason_tf = ft.TextField(label="Justificación (ALCOA)", bgcolor=ft.colors.YELLOW_50)

        def update(e):
            if not reason_tf.value:
                reason_tf.error_text = "Requerido por Audit Trail"
                page.update()
                return
            
            db.execute_query("UPDATE materials SET name=%s, specifications=%s WHERE id=%s", (name_tf.value, specs_tf.value, mid))
            log_audit(current_user["name"], "EDIT_MATERIAL", f"ID {mid} modificado. Razón: {reason_tf.value}")
            page.dialog.open = False
            build_catalog_view()
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Editar Materia Prima"),
            content=ft.Column([name_tf, specs_tf, reason_tf], tight=True),
            actions=[ft.TextButton("Actualizar", on_click=update)]
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # 3. ALMACÉN (RECEPCIÓN)
    def build_inventory_view():
        materials = db.execute_query("SELECT id, name FROM materials WHERE is_active=TRUE", fetch=True)
        mat_opts = [ft.dropdown.Option(key=str(m[0]), text=m[1]) for m in materials] if materials else []

        mat_dd = ft.Dropdown(label="Materia Prima", options=mat_opts)
        lot_int = ft.TextField(label="Lote Interno")
        lot_ven = ft.TextField(label="Lote Proveedor")
        qty = ft.TextField(label="Cantidad Recibida (kg)", keyboard_type=ft.KeyboardType.NUMBER)
        exp_date = ft.TextField(label="Caducidad (YYYY-MM-DD)")
        
        def receive(e):
            try:
                db.execute_query(
                    """INSERT INTO inventory 
                    (material_id, lot_internal, lot_vendor, quantity, expiry_date, status) 
                    VALUES (%s, %s, %s, %s, %s, 'CUARENTENA')""",
                    (mat_dd.value, lot_int.value, lot_ven.value, float(qty.value), exp_date.value)
                )
                log_audit(current_user["name"], "RECEIPT", f"Ingreso Lote {lot_int.value}")
                ft.SnackBar(ft.Text("Material Ingresado")).open = True
                page.update()
            except Exception as ex:
                logger.error(ex)

        form = ft.Column([
            ft.Text("Recepción de Materiales", size=20, weight="bold"),
            mat_dd, lot_int, lot_ven, qty, exp_date,
            ft.ElevatedButton("Ingresar al Almacén", on_click=receive)
        ], scroll=ft.ScrollMode.AUTO)
        
        content_column.controls = [ft.Container(content=form, padding=20)]
        page.update()

    # 4. MUESTREO
    def build_sampling_view():
        inv_items = db.execute_query(
            "SELECT i.id, m.name, i.lot_internal, i.quantity FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.quantity > 0", 
            fetch=True
        ) or []

        lv = ft.ListView(expand=True)

        for item in inv_items:
            # Formula de muestreo farmacéutico simple: Raíz de N + 1 (Asumiendo N = contenedores, simulado aquí por cantidad)
            sample_cal = math.ceil(math.sqrt(item[3]) + 1) if item[3] > 0 else 1
            
            def discount_sample(e, iid=item[0], cur_qty=item[3]):
                new_qty = cur_qty - 0.1 # Descuenta 100g por ejemplo
                db.execute_query("UPDATE inventory SET quantity=%s, status='MUESTREADO' WHERE id=%s", (new_qty, iid))
                log_audit(current_user["name"], "SAMPLING", f"Muestreo ID {iid}. Qty desc: 0.1")
                build_sampling_view()

            lv.controls.append(
                ft.Card(
                    content=ft.ListTile(
                        title=ft.Text(f"{item[1]} (Lote: {item[2]})"),
                        subtitle=ft.Text(f"Stock: {item[3]}kg | Muestra sug.: {sample_cal} u"),
                        trailing=ft.IconButton(ft.icons.CUT, tooltip="Tomar Muestra", on_click=discount_sample)
                    )
                )
            )

        content_column.controls = [ft.Text("Módulo de Muestreo", size=20, weight="bold"), lv]
        page.update()

    # 5. LABORATORIO & REPORTES
    def build_lab_view():
        # Items muestreados pendientes de análisis
        pending = db.execute_query(
            """SELECT i.id, m.name, i.lot_internal, m.specifications 
               FROM inventory i JOIN materials m ON i.material_id = m.id 
               WHERE i.status='MUESTREADO'""", fetch=True
        ) or []

        lv = ft.ListView(expand=True)

        def open_analysis(item):
            res_val = ft.TextField(label="Resultados (JSON/Texto)", multiline=True)
            concl = ft.Dropdown(options=[ft.dropdown.Option("APROBADO"), ft.dropdown.Option("RECHAZADO")])
            
            def save_res(e):
                db.execute_query(
                    "INSERT INTO lab_results (inventory_id, analyst, result_data, conclusion) VALUES (%s, %s, %s, %s)",
                    (item[0], current_user["name"], res_val.value, concl.value)
                )
                new_status = "LIBERADO" if concl.value == "APROBADO" else "RECHAZADO"
                db.execute_query("UPDATE inventory SET status=%s WHERE id=%s", (new_status, item[0]))
                
                # Generar PDF
                pdf_name = f"CoA_{item[2]}.pdf"
                generate_pdf(pdf_name, {
                    "Producto": item[1],
                    "Lote": item[2],
                    "Analista": current_user["name"],
                    "Resultado": concl.value,
                    "Detalles": res_val.value
                })
                
                page.dialog.open = False
                ft.SnackBar(ft.Text(f"Análisis Guardado. PDF generado: {pdf_name}")).open = True
                build_lab_view()
                page.update()

            dlg = ft.AlertDialog(
                title=ft.Text(f"Análisis: {item[1]}"),
                content=ft.Column([
                    ft.Text(f"Specs: {item[3]}"),
                    res_val, concl
                ], tight=True),
                actions=[ft.ElevatedButton("Guardar & Emitir CoA", on_click=save_res)]
            )
            page.dialog = dlg
            dlg.open = True
            page.update()

        for p in pending:
            lv.controls.append(
                ft.ListTile(
                    title=ft.Text(f"{p[1]} - {p[2]}"),
                    subtitle=ft.Text("Pendiente de Análisis"),
                    trailing=ft.IconButton(ft.icons.EDIT_DOCUMENT, on_click=lambda e, i=p: open_analysis(i))
                )
            )

        content_column.controls = [ft.Text("Laboratorio - Pendientes", size=20, weight="bold"), lv]
        page.update()

    # 6. ADMIN / AUDIT TRAIL
    def build_audit_view():
        if current_user["role"] != "ADMIN":
            content_column.controls = [ft.Text("Acceso Denegado", color="red")]
            page.update()
            return

        logs = db.execute_query("SELECT timestamp, user_name, action, details FROM audit_trail ORDER BY id DESC LIMIT 50", fetch=True)
        
        dt = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Fecha")),
                ft.DataColumn(ft.Text("Usuario")),
                ft.DataColumn(ft.Text("Acción")),
                ft.DataColumn(ft.Text("Detalle")),
            ],
            rows=[]
        )
        
        for l in logs:
            dt.rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(str(l[0])[:16])),
                ft.DataCell(ft.Text(l[1])),
                ft.DataCell(ft.Text(l[2])),
                ft.DataCell(ft.Text(l[3])),
            ]))

        content_column.controls = [
            ft.Text("Audit Trail (ALCOA)", size=20, weight="bold"),
            ft.Column([dt], scroll=ft.ScrollMode.ALWAYS, expand=True)
        ]
        page.update()

    # INICIO
    build_login()

# --- ENTRY POINT ---
if __name__ == "__main__":
    # Configuración de puerto para Render
    port = int(os.environ.get("PORT", 8080))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=port, host="0.0.0.0")
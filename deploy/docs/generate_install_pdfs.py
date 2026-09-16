"""
Generates the illustrated installation guides (Windows Server / Linux) as
PDFs, using fpdf2 (same library the web panel uses for its own exports).

These are NOT screenshots of an installation wizard -- both server installs
are driven by a single script (PowerShell / bash), there is no GUI wizard to
photograph. What's "illustrated" here is the architecture/flow diagram and
the step numbering, drawn as vector shapes, plus the exact commands to run.

Run:
    venv\\Scripts\\python deploy\\docs\\generate_install_pdfs.py

Regenerate these PDFs whenever the install steps in deploy/windows_server/
or deploy/linux_server/ change, so the docs never drift from the scripts.
"""
import os
from fpdf import FPDF

HERE = os.path.dirname(os.path.abspath(__file__))

NAVY = (31, 41, 55)
BLUE = (37, 99, 235)
GRAY = (107, 114, 128)
LIGHT_GRAY = (243, 244, 246)
GREEN = (130, 179, 102)
GREEN_FILL = (213, 232, 212)
ORANGE = (215, 155, 0)
ORANGE_FILL = (255, 230, 204)
PURPLE = (150, 115, 166)
PURPLE_FILL = (225, 213, 231)
RED_FILL = (248, 206, 204)
RED = (184, 84, 80)
CODE_BG = (30, 30, 30)
CODE_FG = (0, 230, 118)


class Guide(FPDF):
    def __init__(self, doc_title):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.doc_title = doc_title
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 16, 18)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("helvetica", "", 8)
        self.set_text_color(*GRAY)
        self.set_xy(18, 8)
        self.cell(0, 6, self.doc_title, align="L")
        self.set_xy(-40, 8)
        self.cell(22, 6, f"Pag. {self.page_no()}", align="R")
        self.set_draw_color(*LIGHT_GRAY)
        self.line(18, 15, 192, 15)
        self.ln(6)

    def footer(self):
        self.set_y(-14)
        self.set_font("helvetica", "I", 7.5)
        self.set_text_color(*GRAY)
        self.cell(0, 8, "Develop License  Juan Carlos Aguirre Alvarado - Infraestructura TI & Ciberseguridad Apps", align="C")


def cover(pdf, title, subtitle, os_label, color, color_fill):
    pdf.add_page()
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, 210, 90, style="F")
    pdf.set_xy(18, 30)
    pdf.set_font("helvetica", "B", 24)
    pdf.set_text_color(255, 255, 255)
    pdf.multi_cell(174, 11, title)
    pdf.set_xy(18, 62)
    pdf.set_font("helvetica", "", 13)
    pdf.set_text_color(210, 220, 235)
    pdf.multi_cell(174, 7, subtitle)

    pdf.set_xy(18, 105)
    pdf.set_fill_color(*color_fill)
    pdf.set_draw_color(*color)
    pdf.rect(18, 105, 174, 16, style="DF")
    pdf.set_xy(18, 105)
    pdf.set_font("helvetica", "B", 12)
    pdf.set_text_color(*NAVY)
    pdf.cell(174, 16, f"Plataforma objetivo: {os_label}", align="C")

    pdf.set_xy(18, 140)
    pdf.set_font("helvetica", "", 10.5)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(
        174, 6,
        "Esta guia instala el panel web central del Sistema de Asistencia ZKTeco: "
        "el servicio que sincroniza varios relojes biometricos a una sola base de "
        "datos y expone un dashboard para RRHH (marcaciones, empleados, roles y "
        "doble autenticacion).\n\n"
        "Repositorio: github.com/nucaz/biometric-sincro-zkteco-webapp\n\n"
        "Nota: los pasos de servidor se hacen por linea de comandos (no hay un "
        "asistente grafico de instalacion), asi que en vez de capturas de pantalla "
        "esta guia usa diagramas para mostrar que hace cada paso."
    )


def section_title(pdf, text, color):
    pdf.ln(4)
    pdf.set_fill_color(*color)
    pdf.rect(18, pdf.get_y(), 3, 8, style="F")
    pdf.set_xy(24, pdf.get_y())
    pdf.set_font("helvetica", "B", 14)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, text, ln=1)
    pdf.ln(2)


def checklist(pdf, items):
    pdf.set_font("helvetica", "", 10)
    for label, detail in items:
        y0 = pdf.get_y()
        pdf.set_draw_color(*GREEN)
        pdf.set_fill_color(*GREEN_FILL)
        pdf.rect(18, y0 + 1, 4.5, 4.5, style="DF")
        pdf.set_xy(18, y0 + 1)
        pdf.set_font("helvetica", "B", 8)
        pdf.set_text_color(*GREEN)
        pdf.cell(4.5, 4.5, "OK", align="C")
        pdf.set_xy(26, y0)
        pdf.set_font("helvetica", "B", 10)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 6, label, ln=1)
        if detail:
            pdf.set_xy(26, pdf.get_y())
            pdf.set_font("helvetica", "", 9)
            pdf.set_text_color(90, 90, 90)
            pdf.multi_cell(166, 5, detail)
        pdf.ln(1.5)


def code_block(pdf, lines, height=None):
    pdf.set_font("courier", "", 9.5)
    line_h = 5.6
    h = height or (line_h * len(lines) + 5)
    x, y = pdf.get_x(), pdf.get_y()
    pdf.set_fill_color(*CODE_BG)
    pdf.rect(x, y, 174, h, style="F")
    pdf.set_xy(x + 4, y + 3)
    pdf.set_text_color(*CODE_FG)
    for line in lines:
        pdf.set_x(x + 4)
        pdf.cell(166, line_h, line, ln=1)
    pdf.set_xy(x, y + h + 3)
    pdf.set_text_color(0, 0, 0)


def step(pdf, number, title, description=None, code_lines=None, note=None):
    if pdf.get_y() > 250:
        pdf.add_page()
    y0 = pdf.get_y()
    pdf.set_fill_color(*BLUE)
    pdf.ellipse(18, y0, 9, 9, style="F")
    pdf.set_xy(18, y0 + 1.3)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(9, 6.5, str(number), align="C")

    pdf.set_xy(32, y0)
    pdf.set_font("helvetica", "B", 11.5)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 7, title, ln=1)

    pdf.set_x(32)
    if description:
        pdf.set_font("helvetica", "", 9.5)
        pdf.set_text_color(70, 70, 70)
        pdf.set_x(32)
        pdf.multi_cell(160, 5.2, description)
        pdf.set_x(32)

    if code_lines:
        pdf.ln(1)
        pdf.set_x(32)
        code_block_indented(pdf, code_lines, x=32, width=160)

    if note:
        pdf.ln(1)
        pdf.set_x(32)
        pdf.set_font("helvetica", "I", 8.5)
        pdf.set_text_color(*ORANGE)
        pdf.set_x(32)
        pdf.multi_cell(160, 4.8, "Nota: " + note)

    pdf.ln(4)


def code_block_indented(pdf, lines, x, width):
    pdf.set_font("courier", "", 9)
    line_h = 5.4
    h = line_h * len(lines) + 5
    y = pdf.get_y()
    pdf.set_fill_color(*CODE_BG)
    pdf.rect(x, y, width, h, style="F")
    pdf.set_xy(x + 3, y + 2.5)
    pdf.set_text_color(*CODE_FG)
    for line in lines:
        pdf.set_x(x + 3)
        pdf.cell(width - 6, line_h, line, ln=1)
    pdf.set_xy(x, y + h + 2)
    pdf.set_text_color(0, 0, 0)


def flow_diagram(pdf, boxes, arrow_labels, box_colors):
    """boxes: list of (title, [lines]); arrow_labels: list of str between boxes."""
    box_w, box_h, gap = 50, 28, 12
    x = pdf.l_margin
    y = pdf.get_y() + 4
    centers_right = []
    for i, (title, lines) in enumerate(boxes):
        fill, draw = box_colors[i]
        pdf.set_fill_color(*fill)
        pdf.set_draw_color(*draw)
        pdf.rect(x, y, box_w, box_h, style="DF")
        pdf.set_xy(x + 1.5, y + 3)
        pdf.set_font("helvetica", "B", 8.5)
        pdf.set_text_color(*NAVY)
        pdf.multi_cell(box_w - 3, 4.2, title, align="C")
        pdf.set_xy(x + 1.5, pdf.get_y())
        pdf.set_font("helvetica", "", 7)
        pdf.set_text_color(70, 70, 70)
        for l in lines:
            pdf.set_x(x + 1.5)
            pdf.cell(box_w - 3, 3.8, l, align="C", ln=1)
        centers_right.append((x + box_w, y + box_h / 2))
        x += box_w + gap

    pdf.set_draw_color(60, 60, 60)
    pdf.set_line_width(0.4)
    for i in range(len(boxes) - 1):
        x1, yc = centers_right[i]
        x2 = x1 + gap
        pdf.line(x1, yc, x2, yc)
        pdf.line(x2 - 2.5, yc - 1.8, x2, yc)
        pdf.line(x2 - 2.5, yc + 1.8, x2, yc)
        if i < len(arrow_labels):
            pdf.set_xy(x1, yc - 9)
            pdf.set_font("helvetica", "I", 6.5)
            pdf.set_text_color(*GRAY)
            pdf.multi_cell(gap, 3.2, arrow_labels[i], align="C")
    pdf.set_line_width(0.2)
    pdf.set_y(y + box_h + 8)
    pdf.set_text_color(0, 0, 0)


def qa_block(pdf, question, answer):
    if pdf.get_y() > 255:
        pdf.add_page()
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*RED)
    pdf.multi_cell(174, 5.5, "P: " + question)
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(174, 5.2, "R: " + answer)
    pdf.ln(3)


# --------------------------------------------------------------------------
# Windows Server guide
# --------------------------------------------------------------------------

def build_windows_pdf(out_path):
    pdf = Guide("Guia de instalacion - Windows Server")
    cover(
        pdf,
        "Instalacion del Panel Web Central\nen Windows Server",
        "Sistema de Asistencia ZKTeco - version 1.0.0",
        "Windows Server 2016+ / Windows 10-11",
        BLUE, (219, 234, 254),
    )

    pdf.add_page()
    section_title(pdf, "1. Requisitos previos", BLUE)
    checklist(pdf, [
        ("Sistema operativo", "Windows Server 2016 o mas nuevo (Windows 10/11 tambien sirve para pruebas)."),
        ("Python 3.10 o superior", "Instalado con la casilla 'Add python.exe to PATH' marcada. Descarga: python.org/downloads/windows"),
        ("PowerShell como Administrador", "Sin privilegios de administrador, el registro del servicio (Tareas Programadas) no se completa."),
        ("Git (opcional pero recomendado)", "Para traer el codigo con 'git clone'. Se instala con: winget install --id Git.Git -e --source winget"),
        ("Acceso de red a los relojes biometricos", "Puerto 4370/TCP abierto entre el servidor y cada sede."),
        ("Salida a internet durante la instalacion", "pip necesita descargar las dependencias de Python (Flask, SQLAlchemy, pyzk, etc.)."),
        ("Puerto 5000 libre", "El panel escucha ahi. Si se va a usar desde otras PCs de la red, abrir una regla de entrada en el Firewall de Windows Defender."),
        ("(Opcional) PostgreSQL/MySQL ya instalado", "Solo si no se va a usar SQLite (que es el modo por defecto, sin nada que instalar aparte)."),
    ])

    section_title(pdf, "2. Como funciona (diagrama)", BLUE)
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_text_color(70, 70, 70)
    pdf.multi_cell(174, 5, "El servidor Windows corre dos piezas (como Tareas Programadas, con el usuario SYSTEM): la sincronizacion periodica con los relojes, y el panel web que consulta RRHH desde el navegador.")
    flow_diagram(
        pdf,
        boxes=[
            ("Relojes ZKTeco", ["(una o mas sedes)"]),
            ("Servidor Windows", ["Tarea: sync", "Tarea: panel web", "Base de datos"]),
            ("Navegador RRHH", ["login + 2FA", "roles de acceso"]),
        ],
        arrow_labels=["TCP 4370\n(sync cada\n15 min)", "HTTP :5000\n(login, 2FA)"],
        box_colors=[
            ((219, 234, 254), BLUE),
            ((255, 230, 204), ORANGE),
            ((248, 206, 204), RED),
        ],
    )

    pdf.add_page()
    section_title(pdf, "3. Pasos de instalacion", BLUE)

    step(pdf, 1, "Instalar Git (si no lo tienes)",
         "Abre PowerShell (no hace falta ser administrador para esto) y corre:",
         code_lines=["winget install --id Git.Git -e --source winget"],
         note="Cierra y vuelve a abrir PowerShell despues de instalar Git -- si no, el comando 'git' no se reconoce todavia en esa misma ventana.")

    step(pdf, 2, "Clonar el repositorio",
         "En una carpeta cualquiera (no necesita ser la final):",
         code_lines=[
             "git clone https://github.com/nucaz/biometric-sincro-zkteco-webapp.git",
             "cd biometric-sincro-zkteco-webapp",
         ])

    step(pdf, 3, "Abrir PowerShell como Administrador",
         "En esa misma carpeta del repositorio clonado -- clic derecho en el menu de Windows sobre PowerShell y 'Ejecutar como administrador', luego navega con 'cd' hasta la carpeta.")

    step(pdf, 4, "Ejecutar el instalador",
         "Este comando prepara el entorno, instala dependencias, crea la base de datos, la cuenta de acceso, y registra el servicio:",
         code_lines=[
             ".\\deploy\\windows_server\\install.ps1 `",
             "    -AdminUser admin -AdminPassword \"clave-fuerte-aqui\"",
         ],
         note="Cambia la clave por una fuerte de verdad. Si prefieres PostgreSQL/MySQL en vez de SQLite, agrega -DatabaseUrl \"...\" (ver deploy/windows_server/README.md).")

    step(pdf, 5, "Verificar que el servicio quedo activo",
         code_lines=[
             "Get-ScheduledTask -TaskName Asistencia*",
             "Get-ScheduledTaskInfo -TaskName AsistenciaWeb",
         ])

    step(pdf, 6, "Entrar al panel",
         "Desde el mismo servidor: http://localhost:5000 -- desde otra PC de la red: http://<IP-del-servidor>:5000. Inicia sesion con la cuenta creada en el paso 4.")

    step(pdf, 7, "Cargar los relojes biometricos",
         "Desde el panel: Dispositivos -> Agregar dispositivo (nombre, sede, IP, puerto, comm key si el equipo la tiene). Usa 'Probar conexion' para confirmar que cada uno responde antes de esperar la sincronizacion automatica.")

    pdf.add_page()
    section_title(pdf, "4. Actualizar a una version nueva", BLUE)
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_text_color(70, 70, 70)
    pdf.multi_cell(174, 5, "Cada actualizacion oficial sale del repositorio (nunca se edita el codigo instalado a mano). En la carpeta donde clonaste el repo:")
    code_block(pdf, [
        "git pull",
        ".\\deploy\\windows_server\\install.ps1",
        "Stop-ScheduledTask -TaskName AsistenciaWeb",
        "Start-ScheduledTask -TaskName AsistenciaWeb",
    ])
    pdf.ln(3)
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(70, 70, 70)
    pdf.multi_cell(174, 5, "No hace falta repetir -AdminUser/-AdminPassword: la cuenta ya existe. El script conserva devices.json, la base de datos y la clave de sesion (SECRET_KEY) -- una actualizacion no cierra las sesiones activas ni pierde configuracion.")

    section_title(pdf, "5. Solucion de problemas", BLUE)
    qa_block(pdf, "PowerShell no reconoce el comando 'git' despues de instalarlo",
             "Cierra y vuelve a abrir la ventana de PowerShell (el PATH se actualiza al abrir una ventana nueva, no en la que ya estaba abierta).")
    qa_block(pdf, "El script se detiene diciendo que faltan privilegios de administrador",
             "Vuelve a abrirlo con 'Ejecutar como administrador' -- el registro de las Tareas Programadas lo exige. Lo demas (app, dependencias, base de datos) ya habia quedado listo.")
    qa_block(pdf, "El puerto 5000 ya esta en uso",
             "Edita la accion de la tarea 'AsistenciaWeb' (o el argumento --port en install.ps1) para usar otro puerto, ej. 8080, y actualiza la regla de firewall correspondiente.")
    qa_block(pdf, "No hay conexion con un reloj especifico",
             "Usa el boton 'Probar conexion' de ese dispositivo en el panel -- confirma IP, puerto y que el servidor pueda alcanzar esa sede (VPN/firewall entre sedes).")

    pdf.output(out_path)


# --------------------------------------------------------------------------
# Linux Server guide
# --------------------------------------------------------------------------

def build_linux_pdf(out_path):
    pdf = Guide("Guia de instalacion - Linux Server")
    cover(
        pdf,
        "Instalacion del Panel Web Central\nen Linux (Debian/Ubuntu)",
        "Sistema de Asistencia ZKTeco - version 1.0.0",
        "Debian / Ubuntu Server",
        GREEN, GREEN_FILL,
    )

    pdf.add_page()
    section_title(pdf, "1. Requisitos previos", GREEN)
    checklist(pdf, [
        ("Distribucion basada en Debian/Ubuntu", "El script usa apt-get. En RHEL/CentOS/Fedora hay que adaptar los pasos de paquetes a dnf/yum a mano."),
        ("Acceso root o sudo", "El script instala paquetes de sistema y crea un usuario de servicio -- debe correrse con sudo."),
        ("Salida a internet durante la instalacion", "apt-get y pip necesitan descargar PostgreSQL, Python y las dependencias del panel."),
        ("Acceso de red a los relojes biometricos", "Puerto 4370/TCP abierto entre el servidor y cada sede."),
        ("Puerto 5000 libre", "El panel escucha ahi. Si se expone fuera de la red interna, ponerlo detras de un proxy (nginx/caddy) con TLS."),
        ("Git (opcional)", "Para 'git clone' -- se instala con: sudo apt-get install -y git"),
    ])

    section_title(pdf, "2. Como funciona (diagrama)", GREEN)
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_text_color(70, 70, 70)
    pdf.multi_cell(174, 5, "El script deja todo corriendo como dos servicios systemd: el panel web (permanente) y un timer que sincroniza los relojes cada 15 minutos. PostgreSQL se instala y configura automaticamente.")
    flow_diagram(
        pdf,
        boxes=[
            ("Relojes ZKTeco", ["(una o mas sedes)"]),
            ("Servidor Linux", ["asistencia-web.service", "asistencia-sync.timer", "PostgreSQL local"]),
            ("Navegador RRHH", ["login + 2FA", "roles de acceso"]),
        ],
        arrow_labels=["TCP 4370\n(sync cada\n15 min)", "HTTP :5000\n(login, 2FA)"],
        box_colors=[
            ((219, 234, 254), BLUE),
            (GREEN_FILL, GREEN),
            ((248, 206, 204), RED),
        ],
    )

    pdf.add_page()
    section_title(pdf, "3. Pasos de instalacion", GREEN)

    step(pdf, 1, "Conectarse al servidor",
         "Por SSH, con un usuario que tenga sudo:",
         code_lines=["ssh usuario@ip-del-servidor"])

    step(pdf, 2, "Clonar el repositorio",
         code_lines=[
             "sudo apt-get update && sudo apt-get install -y git",
             "git clone https://github.com/nucaz/biometric-sincro-zkteco-webapp.git",
             "cd biometric-sincro-zkteco-webapp",
         ])

    step(pdf, 3, "Ejecutar el instalador",
         "Instala Python, PostgreSQL, crea el entorno virtual, la base de datos y los servicios systemd, todo en un solo paso:",
         code_lines=["sudo ./deploy/linux_server/install.sh"],
         note="Es seguro volver a correrlo -- cada paso revisa si ya esta hecho antes de repetirlo.")

    step(pdf, 4, "(Opcional) Crear la cuenta de acceso en el mismo paso",
         "Para no tener que crearla a mano despues:",
         code_lines=[
             "sudo ADMIN_USER=admin ADMIN_PASSWORD='clave-fuerte' \\",
             "    ./deploy/linux_server/install.sh",
         ])

    step(pdf, 5, "Verificar que los servicios quedaron activos",
         code_lines=[
             "systemctl status asistencia-web",
             "systemctl list-timers asistencia-sync.timer",
         ])

    step(pdf, 6, "Entrar al panel",
         "Desde una PC de la red: http://<IP-del-servidor>:5000. Si no creaste la cuenta en el paso 4, hazlo ahora:",
         code_lines=[
             "sudo -u asistencia bash -c \"cd /opt/asistencia && source central.env && \\",
             "    venv/bin/python -m central.create_admin admin TU_CLAVE\"",
         ])

    step(pdf, 7, "Cargar los relojes biometricos",
         "Desde el panel: Dispositivos -> Agregar dispositivo (nombre, sede, IP, puerto, comm key). Usa 'Probar conexion' para confirmar cada uno.")

    pdf.add_page()
    section_title(pdf, "4. Actualizar a una version nueva", GREEN)
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_text_color(70, 70, 70)
    pdf.multi_cell(174, 5, "Igual que en Windows: la unica fuente de versiones nuevas es este repositorio.")
    code_block(pdf, [
        "cd biometric-sincro-zkteco-webapp",
        "git pull",
        "sudo ./deploy/linux_server/install.sh",
        "sudo systemctl restart asistencia-web",
    ])
    pdf.ln(3)
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(70, 70, 70)
    pdf.multi_cell(174, 5, "El script conserva /opt/asistencia/central.env (incluida la SECRET_KEY) si ya existe -- una actualizacion no cierra las sesiones activas ni pierde la configuracion de base de datos.")

    section_title(pdf, "5. Solucion de problemas", GREEN)
    qa_block(pdf, "'Este script asume Debian/Ubuntu (apt-get)'",
             "Estas en una distro distinta (RHEL/CentOS/Fedora, por ejemplo). Instala manualmente python3, python3-venv y postgresql-server con dnf/yum, y sigue el resto de los pasos del script a mano (ver deploy/linux_server/install.sh como referencia).")
    qa_block(pdf, "'Corre esto como root'",
             "Falta sudo -- usa: sudo ./deploy/linux_server/install.sh")
    qa_block(pdf, "El servicio no arranca (systemctl status muestra failed)",
             "Revisa el log con: journalctl -u asistencia-web -n 50 -- casi siempre es DATABASE_URL mal formado o el puerto 5000 ya ocupado por otro proceso.")
    qa_block(pdf, "No hay internet en el servidor",
             "Este script necesita apt-get y pip. Si el servidor esta aislado, arma un wheelhouse offline desde una maquina con internet (pip download -r central/requirements.txt -d wheelhouse) y copialo al servidor -- ver deploy/linux_server/README.md.")

    pdf.output(out_path)


if __name__ == "__main__":
    out_dir = HERE
    build_windows_pdf(os.path.join(out_dir, "instalacion_windows_server.pdf"))
    build_linux_pdf(os.path.join(out_dir, "instalacion_linux_server.pdf"))
    print("PDFs generados en", out_dir)

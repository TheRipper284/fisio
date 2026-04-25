import os
import tempfile
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, has_app_context, current_app
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta 
from flask_migrate import Migrate
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
import io
from sqlalchemy import inspect, text, delete
from sqlalchemy.exc import IntegrityError

load_dotenv()

# --- STRIPE (desactivado temporalmente; poner True para reactivar pagos con tarjeta) ---
STRIPE_ENABLED = False
if STRIPE_ENABLED:
    import stripe

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
else:
    stripe = None
STRIPE_PUBLIC_KEY = os.environ.get("STRIPE_PUBLIC_KEY", "") if STRIPE_ENABLED else ""

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY',
    'dev-only-generate-a-strong-SECRET_KEY-for-production',
)
# Usar ruta absoluta para evitar errores en Windows
basedir = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get('DATABASE_URL')
is_serverless_runtime = bool(os.environ.get('VERCEL')) or basedir.startswith('/var/task')

def _build_sqlite_uri(base_uri=None):
    sqlite_dir = os.environ.get('SQLITE_DIR')
    if not sqlite_dir:
        sqlite_dir = tempfile.gettempdir() if is_serverless_runtime else os.path.join(basedir, 'database')
    os.makedirs(sqlite_dir, exist_ok=True)

    db_name = 'citas.db'
    if base_uri and base_uri.startswith('sqlite:///'):
        candidate = base_uri.replace('sqlite:///', '', 1).strip()
        if candidate:
            db_name = os.path.basename(candidate) or db_name

    sqlite_path = os.path.join(sqlite_dir, db_name)
    return 'sqlite:///' + sqlite_path

if database_url:
    # Render/heroku a veces usan postgres://; SQLAlchemy 2 espera postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    # Si DATABASE_URL usa SQLite en serverless, movemos el archivo a una ruta escribible.
    if database_url.startswith('sqlite:///') and is_serverless_runtime:
        database_url = _build_sqlite_uri(database_url)
    # Render: SSL suele ser necesario. Si falla la conexión, define DATABASE_SSL_DISABLE=1 en el dashboard.
    if (
        database_url.startswith('postgresql')
        and 'sslmode=' not in database_url
        and os.environ.get('DATABASE_SSL_DISABLE', '').lower() not in ('1', 'true', 'yes')
    ):
        database_url += '&sslmode=require' if '?' in database_url else '?sslmode=require'
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # En entornos serverless (ej. /var/task) el código es de solo lectura.
    # Si no hay DATABASE_URL, usamos una ruta SQLite escribible.
    app.config['SQLALCHEMY_DATABASE_URI'] = _build_sqlite_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# --- CONFIGURACIÓN DE CORREO (Flask-Mail) ---
# Puedes ajustar estos valores con tus credenciales reales
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')

mail = Mail(app)

# --- CONFIGURACIÓN DE SUBIDA DE ARCHIVOS ---
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

csrf = CSRFProtect(app)
# Tras el proxy inverso de Render (HTTPS, host, etc.)
app.wsgi_app = ProxyFix(
    app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1
)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@login_manager.user_loader
def load_user(user_id):
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    return db.session.get(Usuario, uid)


# Tabla de asociación para la relación Muchos a Muchos entre Usuarios (empleados) y Servicios
usuario_servicio = db.Table('usuario_servicio',
    db.Column('usuario_id', db.Integer, db.ForeignKey('usuario.id'), primary_key=True),
    db.Column('servicio_id', db.Integer, db.ForeignKey('servicio.id'), primary_key=True)
)

# MODELO USUARIO
class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    telefono = db.Column(db.String(20))
    rol = db.Column(db.String(20), nullable=False, default="cliente")
    foto_perfil = db.Column(db.String(200)) # Ruta a la imagen de perfil
    # admin, empleado, cliente

    # Relación muchos a muchos con Servicios (específicamente para empleados)
    servicios = db.relationship('Servicio', secondary=usuario_servicio, 
                                backref=db.backref('especialistas', lazy='dynamic'))

    # --- NUEVOS CAMPOS ENTERPRISE ---
    acepto_consentimiento = db.Column(db.Boolean, default=False)
    consentimiento_fecha = db.Column(db.DateTime)


# Modelo de Cita
class Cita(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    cliente_id = db.Column(
        db.Integer,
        db.ForeignKey('usuario.id'),
        nullable=False
    )
    
    # Campo para el empleado/fisioterapeuta asignado
    empleado_id = db.Column(
        db.Integer,
        db.ForeignKey('usuario.id'),
        nullable=True
    )

    servicio_id = db.Column(
        db.Integer,
        db.ForeignKey('servicio.id'),
        nullable=False
    )

    fecha_inicio = db.Column(db.DateTime, nullable=False)
    fecha_fin = db.Column(db.DateTime, nullable=False)

    estado = db.Column(db.String(20), default="Pendiente")
    # Pendiente, Confirmada, Cancelada, Completada
    
    # --- NUEVOS CAMPOS FINANCIEROS Y ENTERPRISE ---
    pagado = db.Column(db.Boolean, default=False)
    metodo_pago = db.Column(db.String(50)) # Efectivo, Tarjeta, Transferencia, Stripe
    stripe_id = db.Column(db.String(200)) # Identificador de transacción Stripe
    
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    cliente = db.relationship('Usuario', foreign_keys=[cliente_id], backref='citas_como_cliente')
    empleado = db.relationship('Usuario', foreign_keys=[empleado_id], backref='citas_como_empleado')
    servicio = db.relationship('Servicio', backref='citas')

# Modelo de Servicio
class Servicio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    precio = db.Column(db.Float, nullable=False)
    duracion_minutos = db.Column(db.Integer, nullable=False)
    categoria = db.Column(db.String(100))
    imagen = db.Column(db.String(200))

# --- NUEVOS MODELOS FASE 2 ---

class Expediente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False, unique=True)
    antecedentes = db.Column(db.Text)
    alergias = db.Column(db.Text)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    paciente = db.relationship('Usuario', backref=db.backref('expediente', uselist=False))

class NotaEvolucion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expediente_id = db.Column(db.Integer, db.ForeignKey('expediente.id'), nullable=False)
    empleado_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    
    expediente = db.relationship('Expediente', backref='notas')
    autor = db.relationship('Usuario', backref='notas_escritas')

class HorarioEspecialista(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    dia_semana = db.Column(db.Integer, nullable=False) # 0=Lunes, 6=Domingo
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    activo = db.Column(db.Boolean, default=True)

    especialista = db.relationship('Usuario', backref='horarios_personalizados')

class Testimonio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    nombre_cliente = db.Column(db.String(100), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    estrellas = db.Column(db.Integer, default=5)
    activo = db.Column(db.Boolean, default=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    
    cliente = db.relationship('Usuario', backref='testimonios_realizados')

class FAQ(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pregunta = db.Column(db.String(255), nullable=False)
    respuesta = db.Column(db.Text, nullable=False)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    imagen = db.Column(db.String(200))
    fecha_publicacion = db.Column(db.DateTime, default=datetime.utcnow)

class Mensaje(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emisor_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    receptor_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    leido = db.Column(db.Boolean, default=False)
    
    emisor = db.relationship('Usuario', foreign_keys=[emisor_id], backref='mensajes_enviados')
    receptor = db.relationship('Usuario', foreign_keys=[receptor_id], backref='mensajes_recibidos')

class Diagnostico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expediente_id = db.Column(db.Integer, db.ForeignKey('expediente.id'), nullable=False)
    empleado_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    plan_tratamiento = db.Column(db.Text)
    puntos_dolor = db.Column(db.Text) # Almacenará coordenadas JSON para el mapa de dolor
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    
    expediente = db.relationship('Expediente', backref='diagnosticos')
    especialista = db.relationship('Usuario', backref='diagnosticos_realizados')

class Archivo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expediente_id = db.Column(db.Integer, db.ForeignKey('expediente.id'), nullable=False)
    nombre_original = db.Column(db.String(200), nullable=False)
    nombre_archivo = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(50)) # pdf, imagen, etc.
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)
    
    expediente = db.relationship('Expediente', backref='archivos')



def _ensure_sqlite_schema():
    """Añade columnas que faltan cuando la BD SQLite es anterior al modelo (sin `flask db upgrade`)."""
    if db.engine.url.drivername != "sqlite":
        return
    try:
        db.create_all()
        insp = inspect(db.engine)
        tables = set(insp.get_table_names() or [])

        statements = []
        if "usuario" in tables:
            cols = {c["name"] for c in insp.get_columns("usuario")}
            if "password_hash" not in cols:
                statements.append("ALTER TABLE usuario ADD COLUMN password_hash VARCHAR(128)")
            if "foto_perfil" not in cols:
                statements.append("ALTER TABLE usuario ADD COLUMN foto_perfil VARCHAR(200)")
            if "acepto_consentimiento" not in cols:
                statements.append(
                    "ALTER TABLE usuario ADD COLUMN acepto_consentimiento BOOLEAN DEFAULT 0"
                )
            if "consentimiento_fecha" not in cols:
                statements.append("ALTER TABLE usuario ADD COLUMN consentimiento_fecha DATETIME")

        if "cita" in tables:
            cols = {c["name"] for c in insp.get_columns("cita")}
            if "empleado_id" not in cols:
                statements.append("ALTER TABLE cita ADD COLUMN empleado_id INTEGER")
            if "pagado" not in cols:
                statements.append("ALTER TABLE cita ADD COLUMN pagado BOOLEAN DEFAULT 0")
            if "metodo_pago" not in cols:
                statements.append("ALTER TABLE cita ADD COLUMN metodo_pago VARCHAR(50)")
            if "stripe_id" not in cols:
                statements.append("ALTER TABLE cita ADD COLUMN stripe_id VARCHAR(200)")

        if "testimonio" in tables:
            cols = {c["name"] for c in insp.get_columns("testimonio")}
            if "cliente_id" not in cols:
                statements.append("ALTER TABLE testimonio ADD COLUMN cliente_id INTEGER")
            if "fecha" not in cols:
                statements.append("ALTER TABLE testimonio ADD COLUMN fecha DATETIME")

        if not statements:
            return
        with db.engine.begin() as conn:
            for sql in statements:
                conn.execute(text(sql))
    except Exception as e:
        print(f"Error reparando esquema SQLite: {e}")


def seed_demo_data():
    """Servicios, admin y datos demo si la BD está vacía. Úsalo tras migraciones (PostgreSQL)."""
    if Servicio.query.count() != 0:
        return
    servicios_iniciales = [
        Servicio(nombre="Fisioterapia Deportiva", descripcion="Tratamiento de lesiones deportivas y mejora del rendimiento.", precio=500.0, duracion_minutos=60),
        Servicio(nombre="Masaje Terapéutico", descripcion="Masaje para aliviar tensión muscular y estrés.", precio=400.0, duracion_minutos=45),
        Servicio(nombre="Rehabilitación Post-Operatoria", descripcion="Cuidado especializado después de una cirugía.", precio=600.0, duracion_minutos=60)
    ]
    for s in servicios_iniciales:
        db.session.add(s)
    if Usuario.query.filter_by(rol="admin").count() == 0:
        hashed_pw = bcrypt.generate_password_hash("admin123").decode('utf-8')
        admin = Usuario(nombre="Admin", email="admin@fisio.com", rol="admin", telefono="0000000000", password_hash=hashed_pw)
        db.session.add(admin)
    if FAQ.query.count() == 0:
        db.session.add(FAQ(pregunta="¿Necesito orden médica para asistir?", respuesta="No es obligatorio, pero si vienes por rehabilitación post-lesión es recomendable traer estudios o indicaciones de tu médico."))
        db.session.add(FAQ(pregunta="¿Cuánto dura una sesión?", respuesta="Depende del servicio: entre 45 y 60 minutos. Puedes ver la duración en cada servicio."))
    if Testimonio.query.count() == 0:
        db.session.add(Testimonio(nombre_cliente="María G.", contenido="Excelente atención y muy buenos resultados con la rehabilitación.", estrellas=5, activo=True))
    db.session.commit()


def _auto_seed_demo_staff_enabled():
    """En Vercel/serverless suele faltar un empleado para agendar; se puede forzar con AUTO_SEED_DEMO_STAFF=1 o desactivar con =0."""
    v = (os.environ.get("AUTO_SEED_DEMO_STAFF") or "").strip().lower()
    if v in ("0", "false", "no"):
        return False
    if v in ("1", "true", "yes"):
        return True
    if os.environ.get("VERCEL"):
        return True
    if os.environ.get("FLASK_DEBUG", "").strip() in ("1", "true", "yes"):
        return True
    try:
        if has_app_context() and current_app and current_app.debug:
            return True
    except RuntimeError:
        pass
    return False


def ensure_demo_empleado_y_asignaciones(*, force=False):
    """
    Si hay servicios pero ningún rol «empleado», crea un fisioterapeuta demo y lo enlaza a todos los servicios.
    Evita API /api/especialistas vacía y slots sin horarios en despliegues de prueba (p. ej. Vercel).
    force=True: usar desde `flask seed` aunque no haya VERCEL (p. ej. PostgreSQL en Render).
    """
    if not force and not _auto_seed_demo_staff_enabled():
        return
    if Usuario.query.filter_by(rol="empleado").count() > 0:
        return
    servicios = Servicio.query.all()
    if not servicios:
        return
    email_demo = (os.environ.get("DEMO_EMPLEADO_EMAIL") or "fisio.demo@centro.app").strip().lower()
    pw_demo = os.environ.get("DEMO_EMPLEADO_PASSWORD") or "empleado123"
    nombre_demo = (os.environ.get("DEMO_EMPLEADO_NOMBRE") or "Fisioterapeuta Demo").strip() or "Fisioterapeuta Demo"
    try:
        emp = Usuario.query.filter_by(email=email_demo).first()
        if emp:
            if emp.rol != "empleado":
                return
        else:
            emp = Usuario(
                nombre=nombre_demo,
                email=email_demo,
                rol="empleado",
                telefono="0000000001",
                password_hash=bcrypt.generate_password_hash(pw_demo).decode("utf-8"),
                acepto_consentimiento=True,
                consentimiento_fecha=datetime.utcnow(),
            )
            db.session.add(emp)
            db.session.flush()
        for s in servicios:
            if s.especialistas.filter(Usuario.id == emp.id).first() is None:
                s.especialistas.append(emp)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
    except Exception as e:
        db.session.rollback()
        print(f"ensure_demo_empleado_y_asignaciones: {e}")


@app.cli.command("seed")
def cli_seed():
    """Tras `flask db upgrade`: tablas que aún no tienen migración + datos demo (Render)."""
    # create_all solo añade tablas que falten; no pisa las creadas por Alembic.
    _ensure_sqlite_schema()
    db.create_all()
    seed_demo_data()
    ensure_demo_empleado_y_asignaciones(force=True)
    print("Seed listo.")


# SQLite local: create_all + columnas faltantes + datos demo.
# PostgreSQL: NO crear tablas aquí — choca con Alembic (`relation already exists`). Usar migraciones + `flask seed`.
with app.app_context():
    database_dir = os.path.join(app.root_path, 'database')
    if not os.path.exists(database_dir):
        os.makedirs(database_dir)

    try:
        if db.engine.url.drivername == "sqlite":
            _ensure_sqlite_schema()
            seed_demo_data()
        ensure_demo_empleado_y_asignaciones()
    except Exception as e:
        print(f"Error inicializando DB: {e}")


@app.before_request
def _lazy_ensure_demo_staff():
    """Primera petición en serverless: por si el import corrió antes de tener tablas o BD vacía."""
    if getattr(app, "_lazy_staff_done", False):
        return
    if not _auto_seed_demo_staff_enabled():
        app._lazy_staff_done = True
        return
    app._lazy_staff_done = True
    try:
        ensure_demo_empleado_y_asignaciones()
    except Exception as e:
        print(f"_lazy_ensure_demo_staff: {e}")


@app.route("/health")
def health():
    """Sin consultas a BD: usado por Render para health checks."""
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/favicon.ico")
def favicon():
    return "", 204

def send_email(subject, recipient, template_name, **kwargs):
    """Función auxiliar para enviar correos electrónicos."""
    if not recipient:
        return False
    try:
        msg = Message(subject, recipients=[recipient])
        msg.html = render_template(f"emails/{template_name}.html", **kwargs)
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error enviando correo: {e}")
        return False


@app.route("/")
def index():
    if current_user.is_authenticated and not current_user.acepto_consentimiento:
        return redirect(url_for('consentimiento'))
    faqs = FAQ.query.all()
    # Solo testimonios activos
    testimonios = Testimonio.query.filter_by(activo=True).all()
    return render_template("index.html", faqs=faqs, testimonios=testimonios)

@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.rol == 'admin':
        return redirect(url_for('admin_inicio'))
    elif current_user.rol == 'recepcionista':
        return redirect(url_for('recepcion_dashboard'))
    elif current_user.rol == 'empleado':
        return redirect(url_for('empleado_dashboard'))
    else:
        return redirect(url_for('cliente_dashboard'))

@app.route("/cliente/citas")
@login_required
def cliente_dashboard():
    # Citas del cliente actual
    citas = Cita.query.filter_by(cliente_id=current_user.id).order_by(Cita.fecha_inicio.desc()).all()
    # Diagnósticos del expediente del cliente (evitar acceder relaciones en template)
    diagnosticos = []
    try:
        if hasattr(current_user, 'expediente') and current_user.expediente:
            diagnosticos = sorted(
                current_user.expediente.diagnosticos,
                key=lambda d: d.fecha or datetime.min,
                reverse=True
            )
    except Exception:
        diagnosticos = []
    return render_template("cliente_dashboard.html", citas=citas, diagnosticos=diagnosticos)

@app.route("/consentimiento", methods=["GET", "POST"])
@login_required
def consentimiento():
    if request.method == "POST":
        current_user.acepto_consentimiento = True
        current_user.consentimiento_fecha = datetime.utcnow()
        db.session.commit()
        flash("Gracias por aceptar los términos de consentimiento clínico.", "success")
        return redirect(url_for("index"))
    return render_template("consentimiento.html")

@app.route("/crear-sesion-pago/<int:cita_id>")
@login_required
def crear_sesion_pago(cita_id):
    cita = Cita.query.get_or_404(cita_id)
    if cita.cliente_id != current_user.id:
        return jsonify({"error": "No autorizado"}), 403

    if not STRIPE_ENABLED:
        flash(
            "El pago con tarjeta no está disponible temporalmente. Puedes pagar en recepción.",
            "info",
        )
        return redirect(url_for("cliente_dashboard"))

    if not stripe.api_key:
        flash(
            "Los pagos con tarjeta no están configurados (falta STRIPE_SECRET_KEY en el entorno).",
            "warning",
        )
        return redirect(url_for('cliente_dashboard'))

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'mxn',
                    'product_data': {
                        'name': cita.servicio.nombre,
                        'description': f"Cita con especialista para {cita.servicio.nombre}",
                    },
                    'unit_amount': int(cita.servicio.precio * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('pago_exitoso', cita_id=cita.id, _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('cliente_dashboard', _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        flash(f"Error al procesar pago: {str(e)}", "danger")
        return redirect(url_for('cliente_dashboard'))

@app.route("/pago-exitoso/<int:cita_id>")
@login_required
def pago_exitoso(cita_id):
    session_id = request.args.get('session_id')
    cita = Cita.query.get_or_404(cita_id)

    if STRIPE_ENABLED and session_id and stripe and stripe.api_key:
        session = stripe.checkout.Session.retrieve(session_id)
        cita.pagado = True
        cita.stripe_id = session.id
        cita.metodo_pago = "Stripe / Tarjeta"
        db.session.commit()
        flash("¡Pago realizado con éxito!", "success")

    return redirect(url_for('cliente_dashboard'))

@app.context_processor
def inject_globals():
    servicios_lista = Servicio.query.all()
    return {
        'servicios_global': servicios_lista,
        'fecha_actual_global': date.today().isoformat(),
        'stripe_public_key': STRIPE_PUBLIC_KEY,
        'stripe_habilitado': STRIPE_ENABLED,
    }

@app.route("/servicios")
def servicios():
    servicios_db = Servicio.query.all()
    return render_template("servicios.html", servicios=servicios_db)

@app.route("/ubicacion")
def ubicacion():
    return render_template("ubicacion.html")

@app.route("/servicio/<int:id>")
def servicio_detalle(id):
    servicio = Servicio.query.get_or_404(id)
    return render_template("servicio_detalle.html", servicio=servicio)

def is_safe_redirect(target):
    """Acepta solo redirecciones internas (mismo sitio)."""
    if not target or not target.startswith("/"):
        return False
    return not target.startswith("//") and not ":" in target.split("/")[0]

@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = (request.args.get("next") or request.form.get("next") or "").strip()
    if not is_safe_redirect(next_url):
        next_url = ""

    if current_user.is_authenticated:
        if next_url:
            return redirect(next_url)
        if current_user.rol == 'admin': return redirect(url_for('admin_inicio'))
        if current_user.rol == 'recepcionista': return redirect(url_for('recepcion_dashboard'))
        if current_user.rol == 'empleado': return redirect(url_for('empleado_dashboard'))
        return redirect(url_for('index'))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = (request.form.get("password") or "").strip()
        usuario = Usuario.query.filter_by(email=email).first()

        if usuario and usuario.password_hash and bcrypt.check_password_hash(usuario.password_hash, password):
            login_user(usuario)
            flash(f"Bienvenido, {usuario.nombre}.", "success")
            if next_url:
                return redirect(next_url)
            if usuario.rol == "admin": return redirect(url_for("admin_inicio"))
            if usuario.rol == "recepcionista": return redirect(url_for("recepcion_dashboard"))
            if usuario.rol == "empleado": return redirect(url_for("empleado_dashboard"))
            return redirect(url_for("index"))
        else:
            flash("Correo o contraseña incorrectos.", "danger")
    return render_template("login.html", next=next_url)

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
        
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        telefono = request.form.get("telefono", "").strip()

        if Usuario.query.filter_by(email=email).first():
            flash("Ese correo ya está registrado.", "warning")
            return redirect(url_for("registro"))
            
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        ahora = datetime.utcnow()
        nuevo_usuario = Usuario(
            nombre=nombre,
            email=email,
            password_hash=hashed_pw,
            telefono=telefono,
            rol='cliente',
            acepto_consentimiento=True,
            consentimiento_fecha=ahora,
        )
        db.session.add(nuevo_usuario)
        db.session.commit()
        db.session.refresh(nuevo_usuario)

        login_user(nuevo_usuario, remember=True)
        flash(f"Cuenta creada. ¡Bienvenido, {nombre}!", "success")
        return redirect(url_for("dashboard"))
        
    return render_template("registro.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

@app.route("/admin/crear_usuario", methods=["GET", "POST"])
@login_required
def crear_usuario():
    if current_user.rol != 'admin':
        flash("Acceso denegado.", "danger")
        return redirect(url_for("index"))
        
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        telefono = request.form.get("telefono", "").strip()

        rol = request.form.get("rol", "cliente")
        
        if Usuario.query.filter_by(email=email).first():
            flash("El correo ya está registrado.", "warning")
            return redirect(url_for("crear_usuario"))
            
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        nuevo_usuario = Usuario(nombre=nombre, email=email, password_hash=hashed_pw, telefono=telefono, rol=rol)
        db.session.add(nuevo_usuario)
        db.session.commit()
        flash(f"Usuario {nombre} con rol {rol} creado exitosamente.", "success")
        return redirect(url_for("gestion_usuarios"))
    return render_template("admin_crear_usuario.html")

@app.route("/admin/usuarios")
@login_required
def gestion_usuarios():
    if current_user.rol != 'admin':
        return redirect(url_for("index"))
    # SOLO MOSTRAR STAFF (Admin y Empleados), excluir Clientes
    usuarios = Usuario.query.filter(Usuario.rol.in_(['admin', 'empleado', 'recepcionista'])).all()
    return render_template("admin_usuarios.html", usuarios=usuarios)

@app.route("/admin/usuario/<int:usuario_id>/editar", methods=["GET", "POST"])
@login_required
def editar_usuario(usuario_id):
    if current_user.rol != 'admin':
        return redirect(url_for("index"))

    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        flash(
            "Ese usuario no existe o ya fue eliminado. Actualiza la lista de personal.",
            "warning",
        )
        return redirect(url_for("gestion_usuarios"))
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        telefono = request.form.get("telefono", "").strip()
        rol_nuevo = request.form.get("rol", "").strip()

        if not nombre or not email:
            flash("Nombre y correo son obligatorios.", "danger")
            return render_template("admin_editar_usuario.html", usuario=usuario)

        otro = Usuario.query.filter(Usuario.email == email, Usuario.id != usuario.id).first()
        if otro:
            flash("Ese correo ya está en uso por otro usuario.", "warning")
            return render_template("admin_editar_usuario.html", usuario=usuario)

        otros_admins = Usuario.query.filter(Usuario.rol == "admin", Usuario.id != usuario.id).count()
        if usuario.rol == "admin" and rol_nuevo and rol_nuevo != "admin" and otros_admins == 0:
            flash("No puedes quitar el rol de administrador al único administrador.", "danger")
            return render_template("admin_editar_usuario.html", usuario=usuario)

        usuario.nombre = nombre
        usuario.email = email
        usuario.telefono = telefono
        if rol_nuevo:
            usuario.rol = rol_nuevo

        nueva_pw = request.form.get("password", "").strip()
        if nueva_pw:
            usuario.password_hash = bcrypt.generate_password_hash(nueva_pw).decode("utf-8")

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("No se pudo guardar: el correo podría estar duplicado.", "danger")
            return render_template("admin_editar_usuario.html", usuario=usuario)

        flash(f"Usuario {usuario.nombre} actualizado.", "success")
        return redirect(url_for("gestion_usuarios"))

    return render_template("admin_editar_usuario.html", usuario=usuario)

@app.route("/admin/servicio/<int:id>/asignar", methods=["GET", "POST"])
@login_required
def asignar_especialistas(id):
    if current_user.rol != 'admin':
        return redirect(url_for("index"))
    
    servicio = Servicio.query.get_or_404(id)
    # Solo empleados (fisioterapeutas)
    empleados = Usuario.query.filter_by(rol='empleado').all()
    
    if request.method == "POST":
        ids_seleccionados = request.form.getlist("empleados")
        # Convertir IDs a objetos Usuario
        especialistas_nuevos = Usuario.query.filter(Usuario.id.in_(ids_seleccionados)).all()
        # Actualizar la relación muchos a muchos
        servicio.especialistas = especialistas_nuevos
        db.session.commit()
        flash(f"Especialistas asignados correctamente a {servicio.nombre}.", "success")
        return redirect(url_for("admin"))

    ids_asignados = {e.id for e in servicio.especialistas.all()}
    return render_template(
        "admin_asignar_especialistas.html",
        servicio=servicio,
        empleados=empleados,
        ids_asignados=ids_asignados,
    )

# --- RUTAS FASE 2 ---

@app.route("/empleado")
@login_required
def empleado_dashboard():
    if current_user.rol not in ['empleado', 'admin']:
        flash("Acceso restringido a personal de la clínica.", "danger")
        return redirect(url_for("index"))
    
    # Citas asignadas al empleado actual
    hoy = date.today()
    citas_hoy = Cita.query.filter(
        Cita.empleado_id == current_user.id,
        db.func.date(Cita.fecha_inicio) == hoy
    ).order_by(Cita.fecha_inicio.asc()).all()
    
    citas_todas = Cita.query.filter_by(empleado_id=current_user.id).order_by(Cita.fecha_inicio.desc()).all()

    # Mis clientes: solo los que tienen al menos una cita con este empleado
    mis_clientes = Usuario.query.join(Cita, Usuario.id == Cita.cliente_id).filter(
        Cita.empleado_id == current_user.id
    ).distinct().order_by(Usuario.nombre).all()

    return render_template("empleado_dashboard.html",
                           citas_hoy=citas_hoy,
                           citas_todas=citas_todas,
                           mis_clientes=mis_clientes)

def can_access_patient(user, paciente_id):
    if user.rol in ['admin', 'recepcionista']:
        return True
    if user.rol == 'empleado':
        return Cita.query.filter_by(empleado_id=user.id, cliente_id=paciente_id).first() is not None
    if user.rol == 'cliente':
        return user.id == paciente_id
    return False

def contactos_permitidos(user):
    if user.rol == 'cliente':
        return Usuario.query.join(Cita, Usuario.id == Cita.empleado_id).filter(
            Cita.cliente_id == user.id
        ).distinct().order_by(Usuario.nombre).all()
    if user.rol == 'empleado':
        return Usuario.query.join(Cita, Usuario.id == Cita.cliente_id).filter(
            Cita.empleado_id == user.id
        ).distinct().order_by(Usuario.nombre).all()
    if user.rol == 'recepcionista':
        # Recepción puede coordinar con clientes y especialistas.
        return Usuario.query.filter(Usuario.rol.in_(['cliente', 'empleado'])).order_by(Usuario.nombre).all()
    if user.rol == 'admin':
        # Admin solo puede mensajear al personal (sus trabajadores), no a clientes.
        return Usuario.query.filter(Usuario.rol.in_(['empleado', 'recepcionista'])).order_by(Usuario.nombre).all()
    return []


def especialistas_para_servicio(servicio):
    """
    Quienes pueden atender un servicio: los asignados en admin (M2M).
    Si aún no hay ninguno asignado, se listan todos los fisioterapeutas (empleado),
    para que en pruebas o recién desplegado el personal creado pueda elegirse sin paso extra.
    """
    if not servicio:
        return []
    asignados = servicio.especialistas.all()
    if asignados:
        return asignados
    return (
        Usuario.query.filter(Usuario.rol == "empleado")
        .order_by(Usuario.nombre)
        .all()
    )


def empleado_autorizado_para_servicio(empleado, servicio):
    """True si el usuario puede tomar citas de ese servicio (reserva / API de slots)."""
    if not empleado or not servicio or empleado.rol not in ("empleado", "admin"):
        return False
    if servicio.especialistas.count() == 0:
        return True
    return servicio.especialistas.filter(Usuario.id == empleado.id).first() is not None


@app.context_processor
def inject_booking_helpers():
    return {"especialistas_para_servicio": especialistas_para_servicio}


@app.route("/empleado/cita/<int:id>/completar")
@login_required
def completar_cita_empleado(id):
    if current_user.rol not in ['empleado', 'admin']: return redirect(url_for("index"))
    cita = Cita.query.get_or_404(id)
    if cita.empleado_id != current_user.id and current_user.rol != 'admin':
        flash("No puedes gestionar esta cita.", "danger")
        return redirect(url_for("empleado_dashboard"))
    
    cita.estado = "Completada"
    db.session.commit()
    flash(f"Cita con {cita.cliente.nombre} completada. Por favor agrega una nota de evolución.", "success")
    return redirect(url_for("ver_paciente", id=cita.cliente_id))

@app.route("/mensajeria")
@login_required
def mensajeria():
    # Contactos: solo con quienes puede chatear (y solo ven mensajes entre los dos)
    contactos = contactos_permitidos(current_user)

    # Conversación seleccionada: solo mensajes entre current_user y ese contacto
    conversacion_id = request.args.get("conversacion", type=int)
    mensajes_conversacion = []
    contacto_seleccionado = None
    if conversacion_id:
        # Validar que el otro usuario está en la lista de contactos permitidos
        ids_contactos = {c.id for c in contactos}
        if conversacion_id in ids_contactos:
            contacto_seleccionado = Usuario.query.get(conversacion_id)
            mensajes_conversacion = Mensaje.query.filter(
                db.or_(
                    db.and_(Mensaje.emisor_id == current_user.id, Mensaje.receptor_id == conversacion_id),
                    db.and_(Mensaje.emisor_id == conversacion_id, Mensaje.receptor_id == current_user.id)
                )
            ).order_by(Mensaje.fecha.asc()).all()

    return render_template(
        "mensajeria.html",
        contactos=contactos,
        mensajes_conversacion=mensajes_conversacion,
        conversacion_id=conversacion_id,
        contacto_seleccionado=contacto_seleccionado,
    )

@app.route("/mensaje/enviar", methods=["POST"])
@login_required
def enviar_mensaje():
    receptor_id = request.form.get("receptor_id")
    contenido = request.form.get("contenido", "").strip()
    
    if receptor_id and contenido:
        rid = int(receptor_id)
        ids_permitidos = {c.id for c in contactos_permitidos(current_user)}
        if rid not in ids_permitidos:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({"status": "error", "message": "No autorizado para este contacto"}), 403
            flash("No autorizado para enviar mensajes a este contacto.", "danger")
            return redirect(url_for("mensajeria"))
        nuevo_mensaje = Mensaje(emisor_id=current_user.id, receptor_id=rid, contenido=contenido)
        db.session.add(nuevo_mensaje)
        db.session.commit()
        
        # Si es una petición AJAX, devolvemos JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"status": "success", "mensaje": {
                "id": nuevo_mensaje.id,
                "contenido": nuevo_mensaje.contenido,
                "fecha": nuevo_mensaje.fecha.strftime('%d/%m %H:%M'),
                "emisor_id": nuevo_mensaje.emisor_id
            }})
            
        flash("Mensaje enviado.", "success")
        return redirect(url_for("mensajeria", conversacion=rid))
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"status": "error", "message": "Contenido vacío"}), 400
        flash("Escribe un mensaje y elige un contacto.", "danger")
    return redirect(url_for("mensajeria"))

@app.route("/perfil", methods=["GET", "POST"])
@login_required
def perfil():
    if request.method == "POST":
        current_user.nombre = request.form.get("nombre", "").strip()
        current_user.telefono = request.form.get("telefono", "").strip()
        
        # Actualización de correo
        new_email = request.form.get("email", "").strip().lower()
        if new_email and new_email != current_user.email:
            existing_user = Usuario.query.filter_by(email=new_email).first()
            if existing_user:
                flash("Ese correo ya está en uso por otro usuario.", "danger")
                return redirect(url_for("perfil"))
            current_user.email = new_email
        
        # Cambio de contraseña si se indica
        password = request.form.get("password")
        if password:
            current_user.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
            
        # Foto de perfil
        if 'foto' in request.files:
            file = request.files['foto']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"profile_{current_user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{filename.rsplit('.', 1)[1].lower()}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                current_user.foto_perfil = unique_filename
        
        db.session.commit()
        flash("Perfil actualizado correctamente.", "success")
        return redirect(url_for("perfil"))
        
    return render_template("perfil.html")

@app.route("/api/mensajes/<int:contacto_id>")
@login_required
def api_get_mensajes(contacto_id):
    # Validar que el usuario puede chatear con este contacto (opcional base en rol)
    ids_permitidos = {c.id for c in contactos_permitidos(current_user)}
    if contacto_id not in ids_permitidos:
        return jsonify({"error": "No autorizado"}), 403

    mensajes = Mensaje.query.filter(
        db.or_(
            db.and_(Mensaje.emisor_id == current_user.id, Mensaje.receptor_id == contacto_id),
            db.and_(Mensaje.emisor_id == contacto_id, Mensaje.receptor_id == current_user.id)
        )
    ).order_by(Mensaje.fecha.asc()).all()
    
    return jsonify({
        "mensajes": [
            {
                "id": m.id,
                "contenido": m.contenido,
                "fecha": m.fecha.strftime('%d/%m %H:%M'),
                "emisor_id": m.emisor_id
            } for m in mensajes
        ]
    })

@app.route("/paciente/<int:id>/subir_archivo", methods=["POST"])
@login_required
def subir_archivo(id):
    if current_user.rol not in ['empleado', 'admin']:
        return redirect(url_for("index"))
    
    paciente = Usuario.query.get_or_404(id)
    if not paciente.expediente:
        paciente.expediente = Expediente(paciente_id=id)
        db.session.add(paciente.expediente)
        db.session.commit()

    if 'archivo' not in request.files:
        flash("No se seleccionó ningún archivo.", "warning")
        return redirect(url_for("ver_paciente", id=id))
    
    file = request.files['archivo']
    if file.filename == '':
        flash("No se seleccionó ningún archivo.", "warning")
        return redirect(url_for("ver_paciente", id=id))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Añadir timestamp para evitar colisiones
        unique_filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
        
        nuevo_archivo = Archivo(
            expediente_id=paciente.expediente.id,
            nombre_original=filename,
            nombre_archivo=unique_filename,
            tipo=filename.rsplit('.', 1)[1].lower()
        )
        db.session.add(nuevo_archivo)
        db.session.commit()
        flash("Archivo subido correctamente.", "success")
    else:
        flash("Tipo de archivo no permitido.", "danger")
        
    return redirect(url_for("ver_paciente", id=id))

@app.route("/archivo/<int:id>/eliminar")
@login_required
def eliminar_archivo(id):
    archivo = Archivo.query.get_or_404(id)
    # Solo admin o el empleado que atiende al paciente (simplificado a admin/empleado)
    if current_user.rol not in ['admin', 'empleado']:
        flash("Acceso denegado.", "danger")
        return redirect(url_for("index"))
    
    paciente_id = archivo.expediente.paciente_id
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], archivo.nombre_archivo))
    except OSError:
        pass # Si el archivo no existe en disco, procedemos a borrar de DB
    
    db.session.delete(archivo)
    db.session.commit()
    flash("Archivo eliminado.", "info")
    return redirect(url_for("ver_paciente", id=paciente_id))

@app.route("/paciente/<int:id>/nuevo_diagnostico", methods=["POST"])
@login_required
def agregar_diagnostico(id):
    if current_user.rol not in ['empleado', 'admin']:
        return redirect(url_for("index"))
    
    paciente = Usuario.query.get_or_404(id)
    if not paciente.expediente:
        paciente.expediente = Expediente(paciente_id=id)
        db.session.add(paciente.expediente)
        db.session.commit()
    descripcion = request.form.get("descripcion")
    plan = request.form.get("plan_tratamiento")
    puntos = request.form.get("puntos_dolor") # Datos JSON del mapa de dolor
    
    if descripcion:
        nuevo_diag = Diagnostico(
            expediente_id=paciente.expediente.id,
            empleado_id=current_user.id,
            descripcion=descripcion,
            plan_tratamiento=plan,
            puntos_dolor=puntos
        )
        db.session.add(nuevo_diag)
        db.session.commit()
        flash("Diagnóstico registrado correctamente.", "success")
    
    return redirect(url_for("ver_paciente", id=id))

@app.route("/paciente/<int:id>")
@login_required
def ver_paciente(id):
    if current_user.rol not in ['empleado', 'admin']:
        flash("Acceso denegado.", "danger")
        return redirect(url_for("index"))
    if not can_access_patient(current_user, id):
        flash("Solo puedes ver expedientes de tus propios clientes.", "danger")
        return redirect(url_for("empleado_dashboard"))
    
    paciente = Usuario.query.get_or_404(id)
    expediente = Expediente.query.filter_by(paciente_id=id).first()
    if not expediente:
        expediente = Expediente(paciente_id=id)
        db.session.add(expediente)
        db.session.commit()
    # Cargar datos del expediente con consultas directas para no usar relaciones en la plantilla
    diagnosticos = Diagnostico.query.filter_by(expediente_id=expediente.id).order_by(Diagnostico.fecha.desc()).all()
    archivos = Archivo.query.filter_by(expediente_id=expediente.id).order_by(Archivo.fecha_subida.desc()).all()
    notas = NotaEvolucion.query.filter_by(expediente_id=expediente.id).order_by(NotaEvolucion.fecha.desc()).all()
    return render_template(
        "paciente_detalle.html",
        paciente=paciente,
        expediente=expediente,
        diagnosticos=diagnosticos,
        archivos=archivos,
        notas=notas,
    )

@app.route("/paciente/<int:id>/nueva_nota", methods=["POST"])
@login_required
def agregar_nota(id):
    if current_user.rol not in ['empleado', 'admin']:
        return redirect(url_for("index"))
    
    paciente = Usuario.query.get_or_404(id)
    if not paciente.expediente:
        paciente.expediente = Expediente(paciente_id=id)
        db.session.add(paciente.expediente)
        db.session.commit()
    contenido = request.form.get("contenido")
    
    if contenido:
        nueva_nota = NotaEvolucion(
            expediente_id=paciente.expediente.id,
            empleado_id=current_user.id,
            contenido=contenido
        )
        db.session.add(nueva_nota)
        db.session.commit()
        flash("Nota de evolución agregada.", "success")
    
    return redirect(url_for("ver_paciente", id=id))

@app.route("/paciente/<int:id>/editar_expediente", methods=["POST"])
@login_required
def editar_expediente(id):
    if current_user.rol not in ['empleado', 'admin']:
        return redirect(url_for("index"))
    
    paciente = Usuario.query.get_or_404(id)
    if not paciente.expediente:
        paciente.expediente = Expediente(paciente_id=id)
        db.session.add(paciente.expediente)

    paciente.expediente.antecedentes = request.form.get("antecedentes")
    paciente.expediente.alergias = request.form.get("alergias")
    db.session.commit()
    flash("Información del expediente actualizada.", "success")
    return redirect(url_for("ver_paciente", id=id))

@app.route("/api/especialistas")
def api_especialistas():
    servicio_id = request.args.get("servicio_id")
    if not servicio_id:
        return jsonify({"error": "Falta servicio_id"}), 400

    servicio = db.session.get(Servicio, int(servicio_id))
    if not servicio:
        return jsonify({"error": "Servicio no encontrado"}), 404

    lista = especialistas_para_servicio(servicio)
    especialistas = [{"id": e.id, "nombre": e.nombre} for e in lista]
    return jsonify({"especialistas": especialistas})

@app.route("/admin/stats")
@login_required
def admin_stats():
    if current_user.rol != 'admin':
        return redirect(url_for("index"))
    
    total_citas = Cita.query.count()
    citas_completadas = Cita.query.filter_by(estado="Completada").count()
    
    # Ingresos totales (solo citas pagadas)
    ingresos_totales = db.session.query(db.func.sum(Servicio.precio)).select_from(Cita).join(Servicio, Cita.servicio_id == Servicio.id).filter(Cita.pagado == True).scalar() or 0
    ingresos_pendientes = db.session.query(db.func.sum(Servicio.precio)).select_from(Cita).join(Servicio, Cita.servicio_id == Servicio.id).filter(Cita.pagado == False, Cita.estado != "Cancelada").scalar() or 0

    raw_populares = db.session.query(
        Servicio.nombre, db.func.count(Cita.id)
    ).select_from(Servicio).join(Cita, Servicio.id == Cita.servicio_id).group_by(Servicio.nombre).all()
    
    servicios_populares = []
    for nombre, count in raw_populares:
        porcentaje = int((count / total_citas * 100)) if total_citas > 0 else 0
        servicios_populares.append({
            'nombre': nombre,
            'count': count,
            'porcentaje': porcentaje
        })
    
    eficiencia = int((citas_completadas / total_citas * 100)) if total_citas > 0 else 0
    
    return render_template("admin_stats.html", 
                           total=total_citas, 
                           completadas=citas_completadas,
                           eficiencia=eficiencia,
                           populares=servicios_populares,
                           ingresos_totales=ingresos_totales,
                           ingresos_pendientes=ingresos_pendientes)

def obtener_slots_disponibles(fecha_dt, servicio_id, empleado_id=None):
    """Genera slots de tiempo para una fecha y servicio específicos."""
    servicio = db.session.get(Servicio, servicio_id)
    if not servicio:
        return []

    pool = especialistas_para_servicio(servicio)
    pool_ids = {e.id for e in pool}

    if empleado_id:
        try:
            eid = int(empleado_id)
        except (TypeError, ValueError):
            return []
        empleado = db.session.get(Usuario, eid)
        if not empleado or empleado.id not in pool_ids:
            return []
        especialistas = [empleado]
    else:
        especialistas = pool

    if not especialistas:
        return []
    
    slots_disponibles = []
    
    # Obtener citas existentes para los especialistas asignados ese día
    ids_especialistas = [e.id for e in especialistas]
    citas_existentes = Cita.query.filter(
        db.func.date(Cita.fecha_inicio) == fecha_dt.date(),
        Cita.estado != "Cancelada",
        Cita.empleado_id.in_(ids_especialistas)
    ).all()

    # Iterar especialistas para encontrar sus horarios específicos ese día
    dia_semana = fecha_dt.weekday() # 0=Lunes
    
    for especialista in especialistas:
        # Buscar horario personalizado
        horario = HorarioEspecialista.query.filter_by(
            usuario_id=especialista.id, 
            dia_semana=dia_semana, 
            activo=True
        ).first()
        
        if horario:
            inicio_h = fecha_dt.replace(hour=horario.hora_inicio.hour, minute=horario.hora_inicio.minute, second=0)
            fin_h = fecha_dt.replace(hour=horario.hora_fin.hour, minute=horario.hora_fin.minute, second=0)
        else:
            # Default 9-18
            inicio_h = fecha_dt.replace(hour=9, minute=0, second=0)
            fin_h = fecha_dt.replace(hour=18, minute=0, second=0)

        actual = inicio_h
        while actual + timedelta(minutes=servicio.duracion_minutos) <= fin_h:
            inicio_slot = actual
            fin_slot = actual + timedelta(minutes=servicio.duracion_minutos)
            
            # Verificar si este especialista está libre en este slot
            ocupado = any(
                c.empleado_id == especialista.id and
                not (fin_slot <= c.fecha_inicio or inicio_slot >= c.fecha_fin)
                for c in citas_existentes
            )
            
            if not ocupado:
                slot_str = inicio_slot.strftime('%H:%M')
                if slot_str not in slots_disponibles:
                    slots_disponibles.append(slot_str)
            
            actual += timedelta(minutes=30) # Saltos de 30 min para mayor flexibilidad

    slots_disponibles.sort()
    return slots_disponibles


@app.route("/api/slots")
def api_slots():
    fecha_str = request.args.get("fecha")
    servicio_id = request.args.get("servicio_id")
    empleado_id = request.args.get("empleado_id")
    
    if not (fecha_str and servicio_id):
        return jsonify({"error": "Faltan parámetros"}), 400
    try:
        fecha_dt = datetime.strptime(fecha_str, "%Y-%m-%d")
        slots = obtener_slots_disponibles(fecha_dt, int(servicio_id), 
                                         int(empleado_id) if empleado_id else None)
        return jsonify({"slots": slots})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/agendar", methods=["GET", "POST"])
@login_required
def agendar():
    servicios_lista = Servicio.query.all()

    if request.method == "POST":
        # Si el usuario no está logueado, podríamos pedirle sus datos o usar el email del form
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        telefono = request.form.get("telefono", "").strip()
        servicio_id = request.form.get("servicio_id")
        empleado_id = request.form.get("empleado_id")
        fecha_str = request.form.get("fecha")
        hora_str = request.form.get("hora", "").strip()

        if not (servicio_id and fecha_str and hora_str):
            flash("Faltan datos de la cita (servicio, fecha y hora).", "warning")
            return redirect(url_for("agendar"))

        try:
            fecha_inicio = datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M")
            servicio = Servicio.query.get(int(servicio_id))
            fecha_fin = fecha_inicio + timedelta(minutes=servicio.duracion_minutos)

            # Ya que @login_required asegura que hay un usuario autenticado
            # Solo permitimos que clientes agenden para sí mismos, 
            # o que admin/empleados agenden (podrían necesitar especificar un paciente en el futuro, 
            # pero por ahora simplificamos a usar current_user o los datos del form si es staff)
            
            if current_user.rol not in ['admin', 'empleado', 'recepcionista']:
                usuario_id = current_user.id
            else:
                # Si es admin/empleado, buscamos/creamos el paciente basándonos en el form
                if not (nombre and email):
                    flash("Debes proporcionar los datos del paciente.", "warning")
                    return redirect(url_for("agendar"))
                
                usuario = Usuario.query.filter_by(email=email).first()
                if not usuario:
                    usuario = Usuario(nombre=nombre, email=email, telefono=telefono, rol="cliente")
                    db.session.add(usuario)
                    db.session.flush()
                usuario_id = usuario.id

            # Verificar disponibilidad real y buscar un especialista libre
            if empleado_id:
                especialista_libre = db.session.get(Usuario, int(empleado_id))
                if not especialista_libre or not empleado_autorizado_para_servicio(
                    especialista_libre, servicio
                ):
                    flash("El especialista seleccionado no está disponible para este servicio.", "danger")
                    return redirect(url_for("agendar"))
                
                # Verificar conflicto de horario
                conflicto = Cita.query.filter(
                    Cita.empleado_id == especialista_libre.id,
                    Cita.estado != "Cancelada",
                    Cita.fecha_inicio < fecha_fin,
                    Cita.fecha_fin > fecha_inicio
                ).first()
                if conflicto:
                    flash("El especialista ya tiene una cita en ese horario.", "danger")
                    return redirect(url_for("agendar"))
            else:
                especialistas = especialistas_para_servicio(servicio)
                if not especialistas:
                    flash(
                        "No hay fisioterapeutas disponibles. Crea al menos un usuario con rol «empleado».",
                        "danger",
                    )
                    return redirect(url_for("agendar"))

                especialista_libre = None
                ids_especialistas = [e.id for e in especialistas]
                citas_rango = Cita.query.filter(
                    Cita.estado != "Cancelada",
                    Cita.fecha_inicio < fecha_fin,
                    Cita.fecha_fin > fecha_inicio,
                    Cita.empleado_id.in_(ids_especialistas)
                ).all()

                for esp in especialistas:
                    ocupado = any(c.empleado_id == esp.id for c in citas_rango)
                    if not ocupado:
                        especialista_libre = esp
                        break

            if not especialista_libre:
                flash("Ese horario se acaba de ocupar. Por favor elige otro.", "danger")
                return redirect(url_for("agendar"))

            nueva_cita = Cita(
                cliente_id=usuario_id,
                servicio_id=servicio.id,
                empleado_id=especialista_libre.id, # Asignamos al especialista libre
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                estado="Pendiente"
            )

            db.session.add(nueva_cita)
            db.session.commit()

            # --- NOTIFICACIÓN POR CORREO ---
            send_email(
                subject="Cita Confirmada - Centro de Fisioterapia",
                recipient=current_user.email if current_user.rol == 'cliente' else email,
                template_name="cita_confirmada",
                nombre=current_user.nombre if current_user.rol == 'cliente' else nombre,
                servicio=servicio.nombre,
                especialista=especialista_libre.nombre,
                fecha=fecha_str,
                hora=hora_str
            )

            flash("Cita agendada exitosamente.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")

        return redirect(url_for("agendar"))

    # Citas de hoy para mostrar en la página (todas, no solo las del empleado)
    citas_hoy = Cita.query.filter(
        db.func.date(Cita.fecha_inicio) == date.today(),
        Cita.estado != "Cancelada"
    ).order_by(Cita.fecha_inicio.asc()).all()

    return render_template("agendar.html", servicios=servicios_lista, citas=citas_hoy)


@app.route("/admin/inicio")
@login_required
def admin_inicio():
    """Página de inicio del administrador: solo enlaces claros a cada sección."""
    if current_user.rol != 'admin':
        flash("Acceso no autorizado.", "danger")
        return redirect(url_for("index"))
    return render_template("admin_inicio.html")


@app.route("/admin/limpiar_base_datos", methods=["POST"])
@login_required
def limpiar_base_datos():
    """Borra todos los datos excepto el/los usuario(s) admin. Recrea servicios y contenido inicial."""
    if current_user.rol != 'admin':
        flash("Acceso denegado.", "danger")
        return redirect(url_for("index"))
    try:
        # Orden por dependencias de claves foráneas (PostgreSQL exige esto; SQLite a veces no)
        NotaEvolucion.query.delete()
        Diagnostico.query.delete()
        Archivo.query.delete()
        Mensaje.query.delete()
        Cita.query.delete()
        Expediente.query.delete()
        HorarioEspecialista.query.delete()
        db.session.commit()

        # Relación empleados ↔ servicios (debe vaciarse antes de borrar usuarios o servicios)
        db.session.execute(delete(usuario_servicio))
        db.session.commit()

        # Contenido que puede referenciar clientes (FK a usuario)
        FAQ.query.delete()
        Testimonio.query.delete()
        try:
            Post.query.delete()
        except Exception:
            pass
        db.session.commit()

        # Solo mantener cuentas con rol administrador
        Usuario.query.filter(Usuario.rol != "admin").delete(synchronize_session=False)
        db.session.commit()

        Servicio.query.delete()
        db.session.commit()

        # Re-sembrar servicios
        servicios_iniciales = [
            Servicio(nombre="Fisioterapia Deportiva", descripcion="Tratamiento de lesiones deportivas y mejora del rendimiento.", precio=500.0, duracion_minutos=60),
            Servicio(nombre="Masaje Terapéutico", descripcion="Masaje para aliviar tensión muscular y estrés.", precio=400.0, duracion_minutos=45),
            Servicio(nombre="Rehabilitación Post-Operatoria", descripcion="Cuidado especializado después de una cirugía.", precio=600.0, duracion_minutos=60),
        ]
        for s in servicios_iniciales:
            db.session.add(s)
        db.session.add(FAQ(pregunta="¿Necesito orden médica para asistir?", respuesta="No es obligatorio, pero si vienes por rehabilitación post-lesión es recomendable traer estudios o indicaciones de tu médico."))
        db.session.add(FAQ(pregunta="¿Cuánto dura una sesión?", respuesta="Depende del servicio: entre 45 y 60 minutos. Puedes ver la duración en cada servicio."))
        db.session.add(Testimonio(nombre_cliente="María G.", contenido="Excelente atención y muy buenos resultados con la rehabilitación.", estrellas=5, activo=True))
        db.session.commit()

        flash("Base de datos limpiada. Solo se mantuvo el/los administrador(es). Servicios y contenido inicial restaurados.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al limpiar: {str(e)}", "danger")
    return redirect(url_for("admin_inicio"))


@app.route("/admin")
@login_required
def admin():
    if current_user.rol not in ['admin', 'recepcionista']:
        flash("Acceso no autorizado.", "danger")
        return redirect(url_for("index"))
        
    query = request.args.get("q", "").strip()
    if query:
        # Buscar por teléfono del cliente
        citas = Cita.query.join(Usuario, Cita.cliente_id == Usuario.id).filter(
            Usuario.telefono.contains(query)
        ).order_by(Cita.fecha_registro.desc()).all()
    else:
        citas = Cita.query.order_by(Cita.fecha_registro.desc()).all()
        
    servicios = Servicio.query.all()
    return render_template("admin.html", citas=citas, servicios=servicios, search_query=query)

@app.route("/recepcion")
@login_required
def recepcion_dashboard():
    if current_user.rol != 'recepcionista':
        flash("Acceso no autorizado.", "danger")
        return redirect(url_for("index"))

    query = request.args.get("q", "").strip()
    if query:
        citas = Cita.query.join(Usuario, Cita.cliente_id == Usuario.id).filter(
            Usuario.telefono.contains(query)
        ).order_by(Cita.fecha_registro.desc()).all()
    else:
        citas = Cita.query.order_by(Cita.fecha_registro.desc()).all()

    # Usa la misma plantilla con permisos de solo recepción.
    return render_template("admin.html", citas=citas, servicios=[], search_query=query)

@app.route("/admin/cita/<int:id>/status/<string:nuevo_estado>")
@login_required
def actualizar_cita_status(id, nuevo_estado):
    if current_user.rol not in ['admin', 'recepcionista']:
        return redirect(url_for("index"))
        
    cita = Cita.query.get_or_404(id)
    if nuevo_estado in ["Confirmada", "Cancelada", "Completada", "Pendiente"]:
        cita.estado = nuevo_estado
        db.session.commit()
        flash(f"Cita #{id} marcada como {nuevo_estado}.", "info")
    return redirect(url_for("admin"))

@app.route("/admin/cita/<int:id>/toggle_pago")
@login_required
def toggle_pago(id):
    if current_user.rol not in ['admin', 'recepcionista']: return redirect(url_for("index"))
    cita = Cita.query.get_or_404(id)
    cita.pagado = not cita.pagado
    db.session.commit()
    return redirect(url_for("admin"))

@app.route("/admin/cita/<int:id>/pago", methods=["POST"])
@login_required
def actualizar_pago(id):
    if current_user.rol not in ['admin', 'recepcionista']: return redirect(url_for("index"))
    cita = Cita.query.get_or_404(id)
    cita.pagado = request.form.get("pagado") == "1"
    cita.metodo_pago = request.form.get("metodo_pago", "").strip() or None
    db.session.commit()
    flash("Pago actualizado.", "info")
    return redirect(url_for("admin"))

@app.route("/admin/pacientes")
@login_required
def gestion_pacientes():
    if current_user.rol != 'admin': return redirect(url_for("index"))
    query = request.args.get("q", "").strip()
    if query:
        pacientes = Usuario.query.filter(
            Usuario.rol == 'cliente',
            (Usuario.nombre.contains(query)) | (Usuario.email.contains(query)) | (Usuario.telefono.contains(query))
        ).all()
    else:
        pacientes = Usuario.query.filter_by(rol='cliente').all()
    return render_template("admin_pacientes.html", pacientes=pacientes, search_query=query)

@app.route("/admin/servicio/<int:id>/editar", methods=["GET", "POST"])
@login_required
def editar_servicio(id):
    if current_user.rol != 'admin': return redirect(url_for("index"))
    servicio = Servicio.query.get_or_404(id)
    if request.method == "POST":
        servicio.nombre = request.form.get("nombre")
        servicio.precio = float(request.form.get("precio"))
        servicio.duracion_minutos = int(request.form.get("duracion"))
        servicio.descripcion = request.form.get("descripcion")
        servicio.categoria = request.form.get("categoria")
        servicio.imagen = request.form.get("imagen", "").strip() or None
        db.session.commit()
        flash(f"Servicio {servicio.nombre} actualizado.", "success")
        return redirect(url_for("admin"))
    return render_template("admin_editar_servicio.html", servicio=servicio)

@app.route("/admin/contenido")
@login_required
def gestion_contenido():
    if current_user.rol != 'admin': return redirect(url_for("index"))
    faqs = FAQ.query.all()
    testimonios = Testimonio.query.all()
    return render_template("admin_contenido.html", faqs=faqs, testimonios=testimonios)

@app.route("/admin/faq/nueva", methods=["POST"])
@login_required
def nueva_faq():
    if current_user.rol != 'admin': return redirect(url_for("index"))
    pregunta = request.form.get("pregunta")
    respuesta = request.form.get("respuesta")
    if pregunta and respuesta:
        faq = FAQ(pregunta=pregunta, respuesta=respuesta)
        db.session.add(faq)
        db.session.commit()
        flash("FAQ agregada.", "success")
    return redirect(url_for("gestion_contenido"))

@app.route("/admin/faq/<int:id>/eliminar")
@login_required
def eliminar_faq(id):
    if current_user.rol != 'admin': return redirect(url_for("index"))
    faq = FAQ.query.get_or_404(id)
    db.session.delete(faq)
    db.session.commit()
    flash("FAQ eliminada.", "info")
    return redirect(url_for("gestion_contenido"))

@app.route("/cita/<int:id>/recibo")
@login_required
def generar_recibo(id):
    cita = Cita.query.get_or_404(id)
    # Validar que sea el cliente de la cita o admin/empleado
    if current_user.rol == 'cliente' and cita.cliente_id != current_user.id:
        flash("Acceso denegado.", "danger")
        return redirect(url_for("index"))
    
    # Crear buffer
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Logo (si existe) y Título
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, height - 50, "RECIBO DE PAGO - CENTRO DE FISIOTERAPIA")
    
    p.setFont("Helvetica", 12)
    p.drawString(100, height - 80, f"Fecha de emisión: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    p.drawString(100, height - 100, f"Número de Cita: #{cita.id}")

    # Datos del Cliente
    p.line(100, height - 120, 500, height - 120)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(100, height - 140, "DATOS DEL PACIENTE")
    p.setFont("Helvetica", 11)
    p.drawString(100, height - 160, f"Nombre: {cita.cliente.nombre}")
    p.drawString(100, height - 180, f"Email: {cita.cliente.email}")
    p.drawString(100, height - 200, f"Teléfono: {cita.cliente.telefono or 'N/A'}")

    # Datos del Servicio
    p.line(100, height - 220, 500, height - 220)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(100, height - 240, "DETALLE DEL SERVICIO")
    p.setFont("Helvetica", 11)
    p.drawString(100, height - 260, f"Servicio: {cita.servicio.nombre}")
    p.drawString(100, height - 280, f"Especialista: {cita.empleado.nombre if cita.empleado else 'No asignado'}")
    p.drawString(100, height - 300, f"Fecha de Cita: {cita.fecha_inicio.strftime('%d/%m/%Y %H:%M')}")
    p.drawString(100, height - 320, f"Estado: {cita.estado}")
    
    # Pago
    p.line(100, height - 340, 500, height - 340)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(100, height - 370, f"TOTAL PAGADO: ${cita.servicio.precio}")
    p.setFont("Helvetica", 11)
    p.drawString(100, height - 390, f"Método de pago: {cita.metodo_pago or 'No especificado'}")

    p.setFont("Helvetica-Oblique", 10)
    p.drawString(100, 100, "Gracias por confiar en el Centro de Fisioterapia.")
    p.drawString(100, 85, "Este documento es un comprobante de pago interno.")

    p.showPage()
    p.save()

    buffer.seek(0)
    from flask import send_file
    return send_file(buffer, as_attachment=True, download_name=f"Recibo_Cita_{cita.id}.pdf", mimetype='application/pdf')

@app.route("/admin/calendario")
@login_required
def admin_calendario():
    if current_user.rol not in ['admin', 'recepcionista']: return redirect(url_for("index"))
    return render_template("admin_calendario.html")

@app.route("/api/citas_calendario")
@login_required
def api_citas_calendario():
    if current_user.rol not in ['admin', 'recepcionista']: return jsonify({"error": "Unauthorized"}), 403
    citas = Cita.query.filter(Cita.estado != "Cancelada").all()
    eventos = []
    for c in citas:
        eventos.append({
            'id': c.id,
            'title': f"{c.cliente.nombre} - {c.servicio.nombre}",
            'start': c.fecha_inicio.isoformat(),
            'end': c.fecha_fin.isoformat(),
            'color': '#ffc107' if c.estado == 'Pendiente' else '#0d6efd' if c.estado == 'Confirmada' else '#198754'
        })
    return jsonify({"eventos": eventos})

@app.route("/admin/agregar_servicio", methods=["POST"])
@login_required
def agregar_servicio():
    if current_user.rol != 'admin': return redirect(url_for("index"))

    nombre = request.form.get("nombre", "").strip()
    precio = request.form.get("precio")
    duracion = request.form.get("duracion")
    descripcion = request.form.get("descripcion", "Sin descripción").strip()
    categoria = request.form.get("categoria", "").strip()
    imagen = request.form.get("imagen", "").strip() or None

    if nombre and precio and duracion:
        try:
            nuevo_servicio = Servicio(
                nombre=nombre,
                precio=float(precio),
                duracion_minutos=int(duracion),
                descripcion=descripcion,
                categoria=categoria,
                imagen=imagen
            )

            db.session.add(nuevo_servicio)
            db.session.commit()
            flash(f"Servicio '{nombre}' agregado exitosamente.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error al agregar servicio: {str(e)}", "danger")
    else:
        flash("Todos los campos obligatorios deben estar llenos.", "warning")
    return redirect(url_for("admin"))

@app.route("/admin/eliminar_servicio/<int:id>")
@login_required
def eliminar_servicio(id):
    if current_user.rol != 'admin':
        flash("Acceso denegado.", "danger")
        return redirect(url_for("index"))
    servicio = Servicio.query.get_or_404(id)
    try:
        db.session.delete(servicio)
        db.session.commit()
        flash(f"Servicio '{servicio.nombre}' eliminado.", "info")
    except:
        db.session.rollback()
        flash("Error al eliminar el servicio.", "danger")
    return redirect(url_for("admin"))

@app.route("/cliente/testimonio", methods=["POST"])
@login_required
def crear_testimonio_cliente():
    if current_user.rol != 'cliente':
        flash("Solo los clientes pueden publicar testimonios.", "danger")
        return redirect(url_for("index"))

    contenido = request.form.get("contenido", "").strip()
    estrellas = request.form.get("estrellas", type=int)
    if not contenido:
        flash("El testimonio no puede estar vacío.", "warning")
        return redirect(url_for("cliente_dashboard"))
    if not estrellas or estrellas < 1 or estrellas > 5:
        estrellas = 5

    nuevo_testimonio = Testimonio(
        cliente_id=current_user.id,
        nombre_cliente=current_user.nombre,
        contenido=contenido,
        estrellas=estrellas,
        activo=False
    )
    db.session.add(nuevo_testimonio)
    db.session.commit()
    flash("Gracias por tu testimonio. Será visible cuando sea aprobado por el administrador.", "success")
    return redirect(url_for("cliente_dashboard"))

@app.route("/perfil/horarios", methods=["GET", "POST"])
@login_required
def gestionar_horarios():
    if current_user.rol not in ['admin', 'empleado']:
        flash("Acceso restringido.", "danger")
        return redirect(url_for('index'))
    
    if request.method == "POST":
        dia = int(request.form.get("dia_semana"))
        try:
            desde = datetime.strptime(request.form.get("hora_inicio"), "%H:%M").time()
            hasta = datetime.strptime(request.form.get("hora_fin"), "%H:%M").time()
            
            nuevo_horario = HorarioEspecialista(
                usuario_id=current_user.id,
                dia_semana=dia,
                hora_inicio=desde,
                hora_fin=hasta
            )
            db.session.add(nuevo_horario)
            db.session.commit()
            flash("Horario actualizado.", "success")
        except Exception as e:
            flash(f"Error en formato de hora: {e}", "danger")
            
        return redirect(url_for('gestionar_horarios'))

    horarios = HorarioEspecialista.query.filter_by(usuario_id=current_user.id).order_by(HorarioEspecialista.dia_semana, HorarioEspecialista.hora_inicio).all()
    dias_nombre = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    return render_template("horarios.html", horarios=horarios, dias_nombre=dias_nombre)

@app.route("/horario/<int:id>/eliminar")
@login_required
def eliminar_horario(id):
    h = HorarioEspecialista.query.get_or_404(id)
    if h.usuario_id != current_user.id and current_user.rol != 'admin':
        return redirect(url_for('index'))
    db.session.delete(h)
    db.session.commit()
    flash("Horario eliminado.", "info")
    return redirect(url_for('gestionar_horarios'))

@app.errorhandler(500)
def internal_error(error):
    import traceback
    error_path = os.path.join(basedir, "global_error.txt")
    try:
        with open(error_path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
    except OSError:
        pass
    return (
        "<h1>Error interno del servidor</h1>"
        "<p>Se ha registrado el error. Revisa global_error.txt en la carpeta de la aplicación.</p>",
        500,
        {"Content-Type": "text/html; charset=utf-8"},
    )

if __name__ == "__main__":
    app.run(debug=True)

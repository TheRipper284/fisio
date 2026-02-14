import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta 
from flask_migrate import Migrate
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user



app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-key-fisio-123'
# Usar ruta absoluta para evitar errores en Windows
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database', 'citas.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))


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
    # admin, empleado, cliente

    # Relación muchos a muchos con Servicios (específicamente para empleados)
    servicios = db.relationship('Servicio', secondary=usuario_servicio, 
                                backref=db.backref('especialistas', lazy='dynamic'))


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

class Testimonio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_cliente = db.Column(db.String(100), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    estrellas = db.Column(db.Integer, default=5)
    activo = db.Column(db.Boolean, default=True)

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



# Crear base de datos e insertar datos iniciales
with app.app_context():
    database_dir = os.path.join(app.root_path, 'database')
    if not os.path.exists(database_dir):
        os.makedirs(database_dir)
    
    # Intentar crear tablas. Si cambiaste el esquema, es posible que 
    # necesites borrar citas.db manualmente una vez para que se cree con los nuevos campos.
    try:
        db.create_all()
        
        # Sembrar servicios iniciales si la tabla está vacía
        if Servicio.query.count() == 0:
            servicios_iniciales = [
                Servicio(nombre="Fisioterapia Deportiva", descripcion="Tratamiento de lesiones deportivas y mejora del rendimiento.", precio=500.0, duracion_minutos=60),
                Servicio(nombre="Masaje Terapéutico", descripcion="Masaje para aliviar tensión muscular y estrés.", precio=400.0, duracion_minutos=45),
                Servicio(nombre="Rehabilitación Post-Operatoria", descripcion="Cuidado especializado después de una cirugía.", precio=600.0, duracion_minutos=60)
            ]
            for s in servicios_iniciales:
                db.session.add(s)
            
            # Crear admin inicial si no existe
            if Usuario.query.filter_by(rol="admin").count() == 0:
                hashed_pw = bcrypt.generate_password_hash("admin123").decode('utf-8')
                admin = Usuario(nombre="Admin", email="admin@fisio.com", rol="admin", telefono="0000000000", password_hash=hashed_pw)
                db.session.add(admin)
            
            # Sembrar contenido público si está vacío
            # (Removido por petición: Blog, FAQ, Testimonios)

            db.session.commit()


    except Exception as e:
        print(f"Error inicializando DB: {e}")
        # Si hay error de columnas faltantes, se recomienda borrar el archivo .db

@app.route("/")
def index():
    return render_template("index.html")

@app.context_processor
def inject_globals():
    servicios_lista = Servicio.query.all()
    return {
        'servicios_global': servicios_lista,
        'fecha_actual_global': date.today().isoformat()
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

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.rol == 'admin': return redirect(url_for('admin'))
        if current_user.rol == 'empleado': return redirect(url_for('empleado_dashboard'))
        return redirect(url_for('index'))
        
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and bcrypt.check_password_hash(usuario.password_hash, password):
            login_user(usuario)
            flash(f"Bienvenido, {usuario.nombre}.", "success")
            if usuario.rol == "admin": return redirect(url_for("admin"))
            if usuario.rol == "empleado": return redirect(url_for("empleado_dashboard"))
            return redirect(url_for("index"))
        else:
            flash("Correo o contraseña incorrectos.", "danger")
    return render_template("login.html")

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
    usuarios = Usuario.query.filter(Usuario.rol.in_(['admin', 'empleado'])).all()
    return render_template("admin_usuarios.html", usuarios=usuarios)

@app.route("/admin/usuario/<int:id>/editar", methods=["GET", "POST"])
@login_required
def editar_usuario(id):
    if current_user.rol != 'admin':
        return redirect(url_for("index"))
    
    usuario = Usuario.query.get_or_404(id)
    if request.method == "POST":
        usuario.nombre = request.form.get("nombre", "").strip()
        usuario.email = request.form.get("email", "").strip().lower()
        usuario.telefono = request.form.get("telefono", "").strip()
        usuario.rol = request.form.get("rol")
        
        # Opcional: actualizar contraseña si se proporciona (sin espacios accidentales)
        nueva_pw = request.form.get("password", "").strip()
        if nueva_pw:
            usuario.password_hash = bcrypt.generate_password_hash(nueva_pw).decode('utf-8')

            
        db.session.commit()
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
        
    return render_template("admin_asignar_especialistas.html", servicio=servicio, empleados=empleados)

# --- RUTAS FASE 2 ---

@app.route("/empleado")
@login_required
def empleado_dashboard():
    if current_user.rol not in ['empleado', 'admin']:
        flash("Acceso restringido a personal de la clínica.", "danger")
        return redirect(url_for("index"))
    
    # Citas asignadas al empleado actual
    citas = Cita.query.filter_by(empleado_id=current_user.id).order_by(Cita.fecha_inicio.asc()).all()
    return render_template("empleado_dashboard.html", citas=citas)

@app.route("/paciente/<int:id>")
@login_required
def ver_paciente(id):
    if current_user.rol not in ['empleado', 'admin']:
        flash("Acceso denegado.", "danger")
        return redirect(url_for("index"))
    
    paciente = Usuario.query.get_or_404(id)
    # Asegurar que tiene un expediente
    if not paciente.expediente:
        nuevo_expediente = Expediente(paciente_id=id)
        db.session.add(nuevo_expediente)
        db.session.commit()
    
    return render_template("paciente_detalle.html", paciente=paciente)

@app.route("/paciente/<int:id>/nueva_nota", methods=["POST"])
@login_required
def agregar_nota(id):
    if current_user.rol not in ['empleado', 'admin']:
        return redirect(url_for("index"))
    
    paciente = Usuario.query.get_or_404(id)
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

@app.route("/admin/stats")
@login_required
def admin_stats():
    if current_user.rol != 'admin':
        return redirect(url_for("index"))
    
    total_citas = Cita.query.count()
    citas_completadas = Cita.query.filter_by(estado="Completada").count()
    servicios_populares = db.session.query(
        Servicio.nombre, db.func.count(Cita.id)
    ).join(Cita).group_by(Servicio.nombre).all()
    
    return render_template("admin_stats.html", 
                           total=total_citas, 
                           completadas=citas_completadas,
                           populares=servicios_populares)

def obtener_slots_disponibles(fecha_dt, servicio_id):
    """Genera slots de tiempo para una fecha y servicio específicos basándose en especialistas asignados."""
    servicio = Servicio.query.get(servicio_id)
    if not servicio: return []
    
    # Solo considerar especialistas asignados a este servicio
    especialistas = servicio.especialistas.all()
    if not especialistas:
        return [] # O podrías devolver slots vacíos si no hay nadie asignado
    
    # Horario de atención: 09:00 a 18:00
    inicio_jornada = fecha_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    fin_jornada = fecha_dt.replace(hour=18, minute=0, second=0, microsecond=0)
    
    slots_disponibles = []
    actual = inicio_jornada
    
    # Obtener citas existentes para los especialistas asignados ese día
    ids_especialistas = [e.id for e in especialistas]
    citas_existentes = Cita.query.filter(
        db.func.date(Cita.fecha_inicio) == fecha_dt.date(),
        Cita.estado != "Cancelada",
        Cita.empleado_id.in_(ids_especialistas)
    ).all()
    
    while actual + timedelta(minutes=servicio.duracion_minutos) <= fin_jornada:
        inicio_slot = actual
        fin_slot = actual + timedelta(minutes=servicio.duracion_minutos)
        
        # Un slot está disponible si al menos UN especialista asignado está libre
        al_menos_uno_libre = False
        
        for esp in especialistas:
            # Verificar si ESTE especialista está ocupado en este horario
            esta_ocupado = False
            for cita in citas_existentes:
                if cita.empleado_id == esp.id:
                    if (inicio_slot < cita.fecha_fin) and (fin_slot > cita.fecha_inicio):
                        esta_ocupado = True
                        break
            
            if not esta_ocupado:
                al_menos_uno_libre = True
                break
        
        if al_menos_uno_libre:
            slots_disponibles.append(inicio_slot.strftime("%H:%M"))
        
        # Incrementos de 30 minutos
        actual += timedelta(minutes=30)
        
    return slots_disponibles


@app.route("/api/slots")
def api_slots():
    fecha_str = request.args.get("fecha")
    servicio_id = request.args.get("servicio_id")
    if not (fecha_str and servicio_id):
        return {"error": "Faltan parámetros"}, 400
    try:
        fecha_dt = datetime.strptime(fecha_str, "%Y-%m-%d")
        slots = obtener_slots_disponibles(fecha_dt, int(servicio_id))
        return {"slots": slots}
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/agendar", methods=["GET", "POST"])
def agendar():
    servicios_lista = Servicio.query.all()

    if request.method == "POST":
        # Si el usuario no está logueado, podríamos pedirle sus datos o usar el email del form
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip()
        telefono = request.form.get("telefono", "").strip()
        servicio_id = request.form.get("servicio_id")
        fecha_str = request.form.get("fecha")
        hora_str = request.form.get("hora")

        if not (servicio_id and fecha_str and hora_str):
            flash("Faltan datos de la cita.", "warning")
            return redirect(url_for("agendar"))

        try:
            fecha_inicio = datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M")
            servicio = Servicio.query.get(int(servicio_id))
            fecha_fin = fecha_inicio + timedelta(minutes=servicio.duracion_minutos)

            # Si está logueado, usar su id. Si no, buscar/crear por email
            if current_user.is_authenticated:
                usuario_id = current_user.id
            else:
                if not (nombre and email):
                    flash("Debes estar logueado o proporcionar tus datos.", "warning")
                    return redirect(url_for("agendar"))
                
                usuario = Usuario.query.filter_by(email=email).first()
                if not usuario:
                    usuario = Usuario(nombre=nombre, email=email, telefono=telefono, rol="cliente")
                    db.session.add(usuario)
                    db.session.flush()
                usuario_id = usuario.id

            # Verificar disponibilidad real y buscar un especialista libre
            especialistas = servicio.especialistas.all()
            if not especialistas:
                flash("No hay especialistas asignados para este servicio actualmente.", "danger")
                return redirect(url_for("agendar"))

            especialista_libre = None
            # Citas de los especialistas asignados en ese rango horario
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
            flash("Cita agendada exitosamente.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")

        return redirect(url_for("agendar"))

    return render_template("agendar.html", servicios=servicios_lista)


@app.route("/admin")
@login_required
def admin():
    if current_user.rol != 'admin':
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

@app.route("/admin/cita/<int:id>/status/<string:nuevo_estado>")
@login_required
def actualizar_cita_status(id, nuevo_estado):
    if current_user.rol != 'admin':
        return redirect(url_for("index"))
        
    cita = Cita.query.get_or_404(id)
    if nuevo_estado in ["Confirmada", "Cancelada", "Completada", "Pendiente"]:
        cita.estado = nuevo_estado
        db.session.commit()
        flash(f"Cita #{id} marcada como {nuevo_estado}.", "info")
    return redirect(url_for("admin"))

@app.route("/admin/agregar_servicio", methods=["POST"])
@login_required
def agregar_servicio():
    if current_user.rol != 'admin': return redirect(url_for("index"))

    nombre = request.form.get("nombre", "").strip()
    precio = request.form.get("precio")
    duracion = request.form.get("duracion")
    descripcion = request.form.get("descripcion", "Sin descripción").strip()
    categoria = request.form.get("categoria", "").strip()
    
    if nombre and precio and duracion:
        try:
            nuevo_servicio = Servicio(
                nombre=nombre,
                precio=float(precio),
                duracion_minutos=int(duracion),
                descripcion=descripcion,
                categoria=categoria
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
def eliminar_servicio(id):
    servicio = Servicio.query.get_or_404(id)
    try:
        db.session.delete(servicio)
        db.session.commit()
        flash(f"Servicio '{servicio.nombre}' eliminado.", "info")
    except:
        db.session.rollback()
        flash("Error al eliminar el servicio.", "danger")
    return redirect(url_for("admin"))

@app.errorhandler(500)
def internal_error(error):
    import traceback
    with open("global_error.txt", "w") as f:
        f.write(traceback.format_exc())
    return "500 Internal Error - Check global_error.txt", 500

if __name__ == "__main__":
    app.run(debug=True)
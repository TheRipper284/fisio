# Centro de Fisioterapia - Web App

Aplicación web con **Flask** para gestión de citas, roles (admin, recepción, empleado, cliente), expedientes clínicos, mensajería, calendario, pagos (Stripe) y contenido (FAQs, testimonios).

## Características principales

- Inicio, servicios, ubicación, registro e inicio de sesión
- **Agendar cita** con elección de especialista y franjas horarias
- Paneles por rol: administrador, recepción, empleado, cliente
- Expediente del paciente, notas, diagnósticos, archivos
- Mensajería interna, consentimiento informado, perfil y horarios del especialista
- Pagos con **Stripe** (opcional), recibos PDF, correo (Flask-Mail, opcional)

## Tecnologías

- Python 3, Flask, Flask-Login, Flask-Bcrypt, Flask-WTF (CSRF), Flask-Mail
- Flask-SQLAlchemy + SQLite (por defecto)
- HTML / Jinja2, Bootstrap 5

## Instalación

1. Clonar o copiar el proyecto y entrar en la carpeta `fisio_web`.

2. Crear entorno virtual e instalar dependencias:

   ```bash
   python -m venv venv
   ```

   - Windows: `venv\Scripts\activate`
   - Linux/macOS: `source venv/bin/activate`

   ```bash
   pip install -r requirements.txt
   ```

3. **Variables de entorno:** copiar `.env.example` a `.env` y configurar al menos `SECRET_KEY` en instalaciones reales. Ver comentarios dentro de `.env.example` para Stripe y correo.

   La app carga `.env` automáticamente con `python-dotenv`.

4. Ejecutar:

   ```bash
   python app.py
   ```

   La aplicación queda en `http://127.0.0.1:5000`.

## Seguridad

- Las peticiones **POST** de formularios requieren token **CSRF** (plantilla `_csrf.html` y meta `csrf-token` en `base.html`).
- No uses la `SECRET_KEY` por defecto en producción; define una fuerte en `.env`.
- Las claves de **Stripe** solo deben existir en variables de entorno, no en el código.

## Notas

- Usuario admin inicial (si no existe): sembrado en la primera ejecución; revisa el código en `inicializar_db()` para la contraseña por defecto en desarrollo.
- Para producción conviene servir la app con un proceso WSGI (por ejemplo Gunicorn) y HTTPS detrás de un proxy.

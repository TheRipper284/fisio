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
- Flask-SQLAlchemy + SQLite en local, o **PostgreSQL** vía `DATABASE_URL` (p. ej. Render)
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

## Despliegue en Render (gratis)

1. Sube el código a **GitHub/GitLab**. Hay dos layouts:
   - **Raíz = `fisio_web`:** deja `render.yaml` dentro de esa carpeta (es la raíz del repo).
   - **Raíz = carpeta padre** (como este proyecto con `app/` y `fisio_web/`): en la raíz del repo usa el `render.yaml` del padre (incluye `rootDir: fisio_web`) y no dupliques otro blueprint en el mismo repositorio.

2. En [Render](https://render.com): **New → Blueprint** → conecta el repo y elige la rama. Render creará el **Web Service** y una base **PostgreSQL** gratuita (tienen límites; revisa la [documentación](https://render.com/docs/free)).

3. Variables que Render rellena sola con el Blueprint: `DATABASE_URL`, `SECRET_KEY` (generada). Opcionalmente en el panel del servicio añade `STRIPE_SECRET_KEY`, `STRIPE_PUBLIC_KEY`, `MAIL_USERNAME`, `MAIL_PASSWORD`.

4. **Build command:** `pip install -r requirements.txt`  
   **Start command:** `bash scripts/render_start.sh`  
   (aplica migraciones y arranca Gunicorn en el puerto que asigna Render.)

5. **Sin Blueprint:** New → PostgreSQL (free) → copia la *Internal Database URL*. New → Web Service → mismo repo, **Root Directory** `fisio_web` si aplica; en *Environment* define `DATABASE_URL` (pegar URL), `SECRET_KEY`, `FLASK_APP=app.py`, `PYTHON_VERSION=3.11.6`.

6. **Subidas de archivos (`static/uploads`):** en el plan gratuito el disco del contenedor es efímero; las fotos/archivos pueden perderse al redeploy. Para algo serio usa almacenamiento externo (S3, Cloudinary, etc.).

7. Tras el primer despliegue, entra con el admin sembrado (`admin@fisio.com` / contraseña por defecto del código) y **cámbiala** en producción.

## Notas

- Usuario admin inicial (si no existe): sembrado en la primera ejecución; revisa `inicializar_db()` en `app.py` para la contraseña por defecto en desarrollo.
- En producción la app debe servirse con **Gunicorn** (ya usado en Render), no con `python app.py` en modo debug.

# Centro de Fisioterapia - Web App

Una aplicación web básica construida con Flask para la gestión de citas de un centro de fisioterapia.

## Características
- **Página de Inicio**: Información general.
- **Servicios**: Listado de servicios ofrecidos.
- **Ubicación**: Mapa y dirección del centro.
- **Agendar Cita**: Formulario para solicitar citas (guardado en base de datos).
- **Panel de Admin**: Visualización de todas las citas registradas.

## Tecnologías
- Python 3
- Flask
- Flask-SQLAlchemy (SQLite)
- HTML5 / Jinja2

## Instalación

1. Clonar el repositorio.
2. Crear un entorno virtual:
   ```bash
   python -m venv venv
   ```
3. Activar el entorno virtual:
   - Windows: `venv\Scripts\activate`
   - Linux/Mac: `source venv/bin/activate`
4. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
5. Ejecutar la aplicación:
   ```bash
   python app.py
   ```

La aplicación estará disponible en `http://127.0.0.1:5000`.

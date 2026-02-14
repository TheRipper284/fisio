import os
from app import app, db, Usuario, Servicio, Cita
from datetime import datetime, timedelta

with app.app_context():
    print("Testing agendar logic...")
    nombre = "Test User"
    telefono = "1234567890"
    
    # Try to find a service
    servicio = Servicio.query.first()
    if not servicio:
        print("No services found. Seeding one...")
        servicio = Servicio(nombre="Test Service", descripcion="Desc", precio=10.0, duracion_minutos=30)
        db.session.add(servicio)
        db.session.commit()
    
    print(f"Using service: {servicio.nombre} (ID: {servicio.id})")
    servicio_id = servicio.id
    fecha = "2026-02-13"
    hora = "10:00"
    
    # Logic from app.py
    cliente = Usuario.query.filter_by(telefono=telefono).first()
    if not cliente:
        print("Creating new client...")
        cliente = Usuario(nombre=nombre, telefono=telefono, rol="cliente")
        db.session.add(cliente)
        db.session.commit()
    
    print(f"Using client: {cliente.nombre} (ID: {cliente.id})")
    
    fecha_inicio = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
    fecha_fin = fecha_inicio + timedelta(minutes=servicio.duracion_minutos)
    
    print(f"Dates: {fecha_inicio} to {fecha_fin}")
    
    nueva_cita = Cita(
        cliente_id=cliente.id,
        servicio_id=servicio.id,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin
    )
    
    db.session.add(nueva_cita)
    db.session.commit()
    print("Success! Cita created.")

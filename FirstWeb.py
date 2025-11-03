from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import psycopg2.extras as extras # Para obtener resultados como diccionario (útil para la consulta)
import os
from werkzeug.utils import secure_filename
from urllib.parse import urlparse

# --- CONEXIÓN A BASE DE DATOS (POSTGRESQL - SUPABASE/RENDER) ---
def get_db_connection():
    """Establece la conexión a PostgreSQL usando la variable de entorno DATABASE_URL."""
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        # Esto es un error crítico si la variable no está configurada en Render
        raise Exception("DATABASE_URL environment variable not set. Cannot connect to database.")

    # Analiza la URL de conexión para extraer credenciales
    url = urlparse(DATABASE_URL)
    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port,
        cursor_factory=extras.DictCursor # Devuelve filas como diccionarios
    )
    return conn

# --- INICIALIZACIÓN DE LA APLICACIÓN ---
app = Flask('Control de Prestamos')
# Usa la variable de entorno SECRET_KEY de Render para seguridad de sesiones
app.secret_key = os.environ.get('SECRET_KEY', 'una_clave_de_respaldo_segura') 

# Configuración para subir archivos
# WARNING: El almacenamiento en Render NO es persistente en el plan gratuito.
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ----------------- RUTAS DE LA APLICACIÓN -----------------

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Verificación de usuario
            cursor.execute("SELECT id, contraseña FROM usuarios WHERE id = %s AND contraseña = %s", (username, password))
            user = cursor.fetchone()
            conn.close()

        if user:
            session['username'] = username
            return redirect(url_for('dashboard'))
        
        flash('Credenciales inválidas', 'danger')
        return redirect(url_for('home'))
        
    except Exception as e:
        print(f"Error en el login: {e}")
        flash('Error de conexión o autenticación', 'danger')
        return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('home'))
    
    clientes_con_deuda = []
    total_clientes = 0

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Consulta de clientes con deuda
            cursor.execute("""
                SELECT id, nombre, apellido, direccion, telefono, prestamo 
                FROM clientes_oficial 
                WHERE prestamo > 0 AND usuario_id = %s
            """, (session['username'],))
            clientes_con_deuda = cursor.fetchall()
            
            # Obtener el total de clientes
            cursor.execute("SELECT COUNT(*) FROM clientes_oficial WHERE usuario_id = %s", (session['username'],))
            total_clientes = cursor.fetchone()[0] # [0] para obtener el valor del COUNT
        conn.close()

    except Exception as e:
        print("Error al consultar la base de datos:", e)

    return render_template('dashboard.html', username=session['username'],
                           clientes_con_deuda=clientes_con_deuda,
                           total_clientes=total_clientes)

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Validar que el nombre de usuario no esté ya registrado
                cursor.execute("SELECT id FROM usuarios WHERE id = %s", (username,))
                existing_user = cursor.fetchone()

                if existing_user:
                    flash('El nombre de usuario ya está en uso', 'danger')
                else:
                    # Insertar el nuevo usuario
                    cursor.execute("INSERT INTO usuarios (id, contraseña) VALUES (%s, %s)", (username, password))
                    conn.commit()
                    flash('Usuario registrado con éxito', 'success')
                    conn.close()
                    return redirect(url_for('home'))
            conn.close()
        except Exception as e:
            flash(f'Ocurrió un error al registrar el usuario: {e}', 'danger')
            
    return render_template('registro.html')

@app.route('/nuevo_cliente', methods=['GET', 'POST'])
def nuevo_cliente():
    if 'username' not in session:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        nombre = request.form['nombre']
        apellido = request.form['apellido']
        telefono = request.form['telefono']
        direccion = request.form['direccion']
        aval = request.form['aval']
        telefono_aval = request.form['telefono_aval']
        try:
            prestamo = float(request.form['prestamo'])
        except ValueError:
            flash('El monto del préstamo debe ser un número válido.', 'danger')
            return redirect(url_for('nuevo_cliente'))

        usuario_id = session['username']
        
        # Manejo de archivos
        try:
            credencial_cliente = request.files['credencial_cliente']
            credencial_aval = request.files['credencial_aval']
            comprobante_domicilio = request.files['comprobante_domicilio']

            # Validar tipos de archivos
            if not (credencial_cliente.content_type.startswith('image/') and
                    credencial_aval.content_type.startswith('image/') and
                    comprobante_domicilio.content_type.startswith('image/')):
                flash('Solo se permiten archivos de tipo imagen', 'danger')
                return redirect(url_for('nuevo_cliente'))
            
            # Guardar archivos y obtener rutas relativas para guardar en DB
            credencial_cliente_filename = secure_filename(credencial_cliente.filename)
            credencial_aval_filename = secure_filename(credencial_aval.filename)
            comprobante_domicilio_filename = secure_filename(comprobante_domicilio.filename)

            credencial_cliente_path = os.path.join(app.config['UPLOAD_FOLDER'], credencial_cliente_filename)
            credencial_aval_path = os.path.join(app.config['UPLOAD_FOLDER'], credencial_aval_filename)
            comprobante_domicilio_path = os.path.join(app.config['UPLOAD_FOLDER'], comprobante_domicilio_filename)

            credencial_cliente.save(credencial_cliente_path)
            credencial_aval.save(credencial_aval_path)
            comprobante_domicilio.save(comprobante_domicilio_path)

            conn = get_db_connection()
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO clientes_oficial (nombre, apellido, telefono, direccion, aval, telefono_aval, prestamo, usuario_id,
                                            credencial_cliente, credencial_aval, comprobante_domicilio)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """
                cursor.execute(sql, (nombre, apellido, telefono, direccion, aval, telefono_aval, prestamo, usuario_id,
                                    credencial_cliente_path, credencial_aval_path, comprobante_domicilio_path))
                
                cliente_id = cursor.fetchone()[0] 
                conn.commit()
            conn.close()

            flash('Cliente registrado con éxito', 'success')
            return redirect(url_for('metodos_pago', id_cliente=cliente_id, prestamo=prestamo))
        
        except Exception as e:
            print("Error al insertar datos:", e)
            flash(f"Error al registrar el cliente: {e}", 'danger')
            return redirect(url_for('nuevo_cliente'))
        
    return render_template('nuevo_cliente.html')

@app.route('/metodos_pago/<int:id_cliente>/<float:prestamo>', methods=['GET', 'POST'])
def metodos_pago(id_cliente, prestamo):
    if 'username' not in session:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        meses = int(request.form['meses'])
        dia_pago = request.form['dia_pago']
        interes = 0.0

        if meses == 3:
            interes = 0.05
        elif meses == 6:
            interes = 0.10
        elif meses == 9:
            interes = 0.20
        elif meses == 12:
            interes = 0.25

        prestamo_con_interes = prestamo * (1 + interes)

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                sql_update = "UPDATE clientes_oficial SET prestamo = %s, dia_pago = %s WHERE id = %s"
                cursor.execute(sql_update, (prestamo_con_interes, dia_pago, id_cliente))
                conn.commit()
            conn.close()

            flash('Método de pago registrado con éxito', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            print("Error al actualizar datos:", e)
            flash(f"Error al registrar el método de pago: {e}", 'danger')
            return redirect(url_for('metodos_pago', id_cliente=id_cliente, prestamo=prestamo))

    return render_template('metodos_pago.html', id_cliente=id_cliente, prestamo=prestamo)

@app.route('/registro_pago', methods=['POST'])
def registro_pago():
    if 'username' not in session:
        return redirect(url_for('home'))
    
    id_cliente = request.form['id_cliente']
    try:
        monto_pagado = float(request.form['monto_pagado'])
    except ValueError:
        flash('Monto a pagar inválido.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Obtener el prestamo actual del cliente
            cursor.execute("SELECT prestamo FROM clientes_oficial WHERE id = %s", (id_cliente,))
            prestamo_actual = cursor.fetchone()[0]

            # Validar el monto
            if monto_pagado > prestamo_actual:
                flash('El monto a abonar no puede ser mayor a la deuda.', 'danger')
                conn.close()
                return redirect(url_for('dashboard'))
            if monto_pagado < 1:
                flash('El monto a abonar debe ser mayor o igual a 1.', 'danger')
                conn.close()
                return redirect(url_for('dashboard'))

            # Insertar el nuevo pago
            sql_insert_pago = "INSERT INTO pagos (id_cliente, monto_pagado) VALUES (%s, %s)"
            cursor.execute(sql_insert_pago, (id_cliente, monto_pagado))
            
            # Actualizar la deuda
            sql_update = "UPDATE clientes_oficial SET prestamo = prestamo - %s WHERE id = %s"
            cursor.execute(sql_update, (monto_pagado, id_cliente))
            conn.commit()
        conn.close()
            
        flash('Pago registrado con éxito', 'success')
    except Exception as e:
        print("Error al registrar el pago:", e)
        flash('Error al registrar el pago', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return redirect(url_for('home'))

# NOTA: Se eliminó el bloque 'if __name__ == "__main__":'
# Gunicorn inicia la aplicación en producción con 'gunicorn FirstWeb:app'

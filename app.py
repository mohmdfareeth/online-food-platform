from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_mysqldb import MySQL
import MySQLdb.cursors
from werkzeug.security import generate_password_hash, check_password_hash
import re

# PyMySQL fallback (helpful on Windows if mysqlclient not installed)
try:
    import MySQLdb  # noqa: F401
except Exception:
    try:
        import pymysql
        pymysql.install_as_MySQLdb()
    except Exception:
        pass

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # change this for production

# Load MySQL config from config.py (make sure this file exists)
# Example config.py:
# MYSQL_HOST = 'localhost'
# MYSQL_USER = 'root'
# MYSQL_PASSWORD = 'yourpass'
# MYSQL_DB = 'food_ordering'
# MYSQL_CURSORCLASS = 'DictCursor'
app.config.from_pyfile('config.py')
mysql = MySQL(app)

# ------------------ HOME ------------------
@app.route('/')
def index():
    return render_template('index.html')

# ------------------ REGISTER ------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    msg = ''
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'customer')  # default customer

        # Basic validation
        if not name or not email or not password:
            msg = 'Please fill out the form!'
            return render_template('register.html', msg=msg)

        if not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            msg = 'Invalid email address!'
            return render_template('register.html', msg=msg)

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE email=%s', (email,))
        account = cursor.fetchone()
        if account:
            msg = 'Account already exists!'
        else:
            hashed = generate_password_hash(password)
            cursor.execute('INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, %s)',
                           (name, email, hashed, role))
            mysql.connection.commit()
            flash('You have successfully registered! Please login.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html', msg=msg)

# ------------------ LOGIN ------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    msg = ''
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not email or not password:
            msg = 'Please enter email and password!'
            return render_template('login.html', msg=msg)

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE email=%s', (email,))
        account = cursor.fetchone()
        if account and check_password_hash(account['password'], password):
            # set session
            session['loggedin'] = True
            session['id'] = account['id']
            session['name'] = account['name']
            session['role'] = account['role']

            # redirect based on role
            if account['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif account['role'] == 'restaurant':
                return redirect(url_for('restaurant_dashboard'))
            else:
                return redirect(url_for('customer_dashboard'))
        else:
            msg = 'Incorrect email/password!'
    return render_template('login.html', msg=msg)

# ------------------ DASHBOARDS ------------------
@app.route('/customer')
def customer_dashboard():
    if 'loggedin' in session and session.get('role') == 'customer':
        return render_template('customer_dashboard.html', name=session.get('name'))
    return redirect(url_for('login'))

@app.route('/restaurant')
def restaurant_dashboard():
    if 'loggedin' in session and session.get('role') == 'restaurant':
        return render_template('restaurant_dashboard.html', name=session.get('name'))
    return redirect(url_for('login'))

@app.route('/admin')
def admin_dashboard():
    if 'loggedin' in session and session.get('role') == 'admin':
        return render_template('admin_dashboard.html', name=session.get('name'))
    return redirect(url_for('login'))

# ------------------ LOGOUT ------------------
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ------------------ CUSTOMER VIEW MENU & PLACE ORDER ------------------
@app.route('/menu')
def view_menu():
    if 'loggedin' in session and session.get('role') == 'customer':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""
            SELECT m.id, m.item_name, m.price, m.restaurant_id, u.name as restaurant_name
            FROM menu m JOIN users u ON m.restaurant_id = u.id
            """)
        items = cursor.fetchall()
        return render_template('menu.html', items=items, name=session.get('name'))
    return redirect(url_for('login'))

@app.route('/order/<int:item_id>', methods=['GET', 'POST'])
def place_order(item_id):
    if 'loggedin' in session and session.get('role') == 'customer':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM menu WHERE id=%s", (item_id,))
        item = cursor.fetchone()
        if not item:
            flash('Item not found', 'danger')
            return redirect(url_for('view_menu'))

        if request.method == 'POST':
            try:
                qty = int(request.form.get('quantity', 1))
                if qty < 1:
                    qty = 1
            except ValueError:
                qty = 1
            total = qty * float(item['price'])
            cursor.execute("""
                INSERT INTO orders (customer_id, restaurant_id, item_id, quantity, total)
                VALUES (%s, %s, %s, %s, %s)
                """, (session.get('id'), item['restaurant_id'], item_id, qty, total))
            mysql.connection.commit()
            flash('Order placed successfully!', 'success')
            return redirect(url_for('view_orders'))
        return render_template('order.html', item=item)
    return redirect(url_for('login'))

@app.route('/orders')
def view_orders():
    if 'loggedin' in session and session.get('role') == 'customer':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""SELECT o.id, m.item_name, o.quantity, o.total, o.status, u.name as restaurant
                          FROM orders o
                          JOIN menu m ON o.item_id = m.id
                          JOIN users u ON o.restaurant_id = u.id
                          WHERE o.customer_id = %s
                          ORDER BY o.id DESC""", (session.get('id'),))
        orders = cursor.fetchall()
        return render_template('orders.html', orders=orders, name=session.get('name'))
    return redirect(url_for('login'))

# ------------------ RESTAURANT: ADD ITEM + VIEW ORDERS + UPDATE ORDER ------------------
@app.route('/add_item', methods=['GET', 'POST'])
def add_item():
    if 'loggedin' in session and session.get('role') == 'restaurant':
        if request.method == 'POST':
            item_name = request.form.get('item_name', '').strip()
            price = request.form.get('price', '').strip()
            if not item_name or not price:
                flash('Please fill item name and price', 'warning')
                return render_template('add_item.html')
            try:
                price_val = float(price)
            except ValueError:
                flash('Invalid price', 'warning')
                return render_template('add_item.html')
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            cursor.execute("INSERT INTO menu (restaurant_id, item_name, price) VALUES (%s, %s, %s)",
                           (session.get('id'), item_name, price_val))
            mysql.connection.commit()
            flash('Item added successfully', 'success')
            return redirect(url_for('restaurant_orders'))
        return render_template('add_item.html')
    return redirect(url_for('login'))

@app.route('/restaurant/orders')
def restaurant_orders():
    if 'loggedin' in session and session.get('role') == 'restaurant':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""SELECT o.id, m.item_name, o.quantity, o.total, o.status, u.name as customer
                          FROM orders o
                          JOIN menu m ON o.item_id = m.id
                          JOIN users u ON o.customer_id = u.id
                          WHERE o.restaurant_id = %s
                          ORDER BY o.id DESC""", (session.get('id'),))
        orders = cursor.fetchall()
        return render_template('restaurant_orders.html', orders=orders, name=session.get('name'))
    return redirect(url_for('login'))

@app.route('/update_order/<int:order_id>/<string:status>')
def update_order(order_id, status):
    if 'loggedin' in session and session.get('role') == 'restaurant':
        if status not in ('pending', 'accepted', 'rejected', 'delivered'):
            flash('Invalid status', 'warning')
            return redirect(url_for('restaurant_orders'))
        cursor = mysql.connection.cursor()
        cursor.execute("UPDATE orders SET status=%s WHERE id=%s AND restaurant_id=%s",
                       (status, order_id, session.get('id')))
        mysql.connection.commit()
        flash('Order updated', 'info')
        return redirect(url_for('restaurant_orders'))
    return redirect(url_for('login'))

# ------------------ ADMIN: MANAGE USERS ------------------
@app.route('/admin/users')
def manage_users():
    if 'loggedin' in session and session.get('role') == 'admin':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT id, name, email, role FROM users ORDER BY id")
        users = cursor.fetchall()
        return render_template('manage_users.html', users=users, name=session.get('name'))
    return redirect(url_for('login'))

# ------------------ RUN ------------------
if __name__ == '__main__':
    # In development use debug=True. For production, use a proper WSGI server
    app.run(debug=True)
from flask import (
	Flask,
	render_template,
	url_for,
	redirect,
	request,
	flash,
	session,
	jsonify,
	Blueprint,
	current_app,
	send_file,
	g,
)
import sqlite3
import os
import json
import time
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
import random
from datetime import date, timedelta
from twilio.rest import Client

# Twilio credentials (from console)
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_number = os.getenv("TWILIO_NUMBER")
client = Client(account_sid, auth_token)

# -------------------- Flask App Setup --------------------
app = Flask(__name__)
app.secret_key = "supersecret"  # change in production


def get_db():
	db = getattr(g, '_database', None)
	if db is None:
		db = g._database = sqlite3.connect('restaurant.db')
		db.row_factory = sqlite3.Row  # This enables dictionary-like access
	return db


@app.teardown_appcontext
def close_connection(exception):
	db = getattr(g, '_database', None)
	if db is not None:
		db.close()


def init_db():
	with app.app_context():
		db = get_db()
		cursor = db.cursor()
		
		# Schema for SQLite
		cursor.executescript('''
            CREATE TABLE IF NOT EXISTS All_Orders (
                Order_id TEXT NOT NULL,
                item TEXT NOT NULL,
                type TEXT NOT NULL,
                Quantity INTEGER NOT NULL,
                price INTEGER NOT NULL,
                date_time TEXT NOT NULL,
                payment_type TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS current_order (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_no INTEGER NOT NULL,
                order_id TEXT NOT NULL,
                dish_name TEXT NOT NULL,
                type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                Price INTEGER NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dishes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_name TEXT NOT NULL,
                name TEXT NOT NULL,
                image TEXT,
                available INTEGER DEFAULT 1,
                half_price REAL,
                full_price REAL,
                single_price REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,
                is_veg INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS login (
                Username TEXT NOT NULL,
                Pass TEXT NOT NULL,
                phone_number INTEGER,
                kitchen_password TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments_type (
                Payment_methods TEXT NOT NULL UNIQUE
            );
        ''')
		db.commit()
		
		# Seed data if tables are empty
		cursor.execute("SELECT COUNT(*) FROM login")
		if cursor.fetchone()[0] == 0:
			cursor.execute(
				"INSERT INTO login (Username, Pass, phone_number, kitchen_password) VALUES ('admin', 'Wahid', 8016561416, 'Wahid@123')")
			db.commit()


# Call init_db() to create the database and tables on startup
with app.app_context():
	init_db()


def send_otp(phone_number, otp):
	message = client.messages.create(
		body=f"Your OTP code is {otp}",
		from_=twilio_number,
		to=phone_number
	)
	return message.sid


# -------------------- Admin Blueprint --------------------
admin_bp = Blueprint("admin", __name__, template_folder="templates")


def is_session_expired(x):
	if x == "admin":
		if 'logged_in' not in session or 'last_activity' not in session:
			return True
		timeout = 3600
		if time.time() - session['last_activity'] > timeout:
			return True
		session['last_activity'] = time.time()
	
	if x == "kitchen":
		if 'is_kitchen' not in session or 'kitchen_last_activity' not in session:
			return True
		timeout = 3600 * 24
		if time.time() - session['kitchen_last_activity'] > timeout:
			return True
		session['kitchen_last_activity'] = time.time()
	return False


def cleanup_old_orders():
	db = get_db()
	cursor = db.cursor()
	try:
		# SQLite's DATETIME function is `strftime`
		cursor.execute("DELETE FROM All_Orders WHERE date_time < strftime('%Y-%m-%d %H:%M:%S', 'now', '-180 days')")
		db.commit()
		print("Successfully cleaned old orders")
	except sqlite3.Error as err:
		print(f"Error: {err}")
	cursor.close()


@admin_bp.before_request
def before_admin_request():
	if request.endpoint and request.endpoint.startswith('admin.'):
		if request.endpoint not in ['admin.login', 'admin.forget_password']:
			if session.get('admin_device_id') != request.remote_addr:
				flash("Access denied. You can only access this page from the device you logged in on.", "danger")
				session.clear()
				return redirect(url_for("admin.login"))
			if is_session_expired("admin"):
				session.clear()
				flash("Your session has expired. Please log in again.", "info")
				return redirect(url_for("admin.login"))


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
	message = request.args.get("message")
	if request.method == "POST":
		un = request.form['username']
		ps = request.form['password']
		db = get_db()
		cursor = db.cursor()
		cursor.execute("SELECT * FROM login")
		k = cursor.fetchone()
		cursor.close()
		if k and k['Username'] == un and k['Pass'] == ps:
			session['last_activity'] = time.time()
			session['logged_in'] = True
			session['admin_device_id'] = request.remote_addr
			return redirect(url_for("admin.dashboard"))
		else:
			return render_template("admin_login.html", error=True, message=message)
	return render_template("admin_login.html", error=False, message=message)


@admin_bp.route("/forget_password", methods=["GET", "POST"])
def forget_password():
	db = get_db()
	cursor = db.cursor()
	cursor.execute("SELECT * FROM login")
	k = cursor.fetchone()
	cursor.close()
	if request.method == "POST":
		try:
			phone = int(request.form["phone"])
		except:
			return render_template("forget_password.html", val=str(k['phone_number'])[-4:], error=True)
		if phone == k['phone_number']:
			session["otp"] = str(random.randint(100000, 999999))
			send_otp("+91" + str(phone), session["otp"])
			return render_template("verify_otp.html", error=False)
		else:
			return render_template("forget_password.html", val=str(k['phone_number'])[-4:], error=True)
	return render_template("forget_password.html", val=str(k['phone_number'])[-4:], error=False)


@app.route("/verify_otp", methods=["POST"])
def verify_otp():
	try:
		otp = request.form['otp']
	except:
		return render_template("verify_otp.html", error=True)
	if otp == session.get('otp'):
		return render_template("reset_password.html", error=False)
	return render_template("verify_otp.html", error=True)


@app.route("/reset_password", methods=["POST"])
def reset_password():
	account_type = request.form['account_type']
	password = request.form['new_password']
	confirm_password = request.form['confirm_password']
	if not account_type:
		return render_template("reset_password.html", error=True, message="Select proper account type")
	elif password != confirm_password:
		return render_template("reset_password.html", error=True, message="Passwords and Confirm Password do not match")
	else:
		db = get_db()
		cursor = db.cursor()
		if account_type == "kitchen":
			cursor.execute("UPDATE login SET kitchen_password=?", (password,))
		elif account_type == "admin":
			cursor.execute("UPDATE login SET Pass=?", (password,))
		db.commit()
		cursor.close()
		session.pop("otp", None)
		flash("Password reset successfully. Please login.", "success")
		return redirect(url_for("admin.login", message="Password reset successful"))


@admin_bp.route("/dashboard")
def dashboard():
	if not session.get('logged_in'):
		return redirect(url_for("admin.login"))
	
	cleanup_old_orders()
	db = get_db()
	cursor = db.cursor()
	
	# Calculate today's sales
	today = date.today().strftime('%Y-%m-%d')
	cursor.execute("SELECT SUM(Quantity * price) AS total FROM All_Orders WHERE date(date_time) = ?", (today,))
	sales_today = cursor.fetchone()['total'] or 0
	
	# Calculate yesterday's sales
	yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
	cursor.execute("SELECT SUM(Quantity * price) AS total FROM All_Orders WHERE date(date_time) = ?", (yesterday,))
	sales_yesterday = cursor.fetchone()['total'] or 0
	
	# Fetch data for the sales chart (last 5 days)
	cursor.execute("""
        SELECT date(date_time) as sales_date, SUM(Quantity * price) as total_sales
        FROM All_Orders
        WHERE date_time >= strftime('%Y-%m-%d %H:%M:%S', 'now', '-5 days')
        GROUP BY sales_date
        ORDER BY sales_date
    """)
	chart_data_rows = cursor.fetchall()
	
	chart_labels = [row['sales_date'] for row in chart_data_rows]
	chart_data_values = [row['total_sales'] for row in chart_data_rows]
	
	cursor.close()
	
	return render_template(
		"admin/dashboard.html",
		sales_today=sales_today,
		sales_yesterday=sales_yesterday,
		chart_labels=chart_labels,
		chart_data=chart_data_values
	)


@admin_bp.route("/menu")
def menu():
	if not session.get('logged_in'):
		return redirect(url_for("admin.login"))
	
	db = get_db()
	cursor = db.cursor()
	cursor.execute("SELECT `name` FROM categories")
	categories = [i["name"] for i in cursor.fetchall()]
	
	if not categories:
		categories = ["Default"]
	
	category = request.args.get("category", categories[0])
	
	if category not in categories:
		return redirect(url_for("admin.menu", category=categories[0]))
	
	cursor.execute(
		"SELECT * FROM dishes WHERE available=1 AND category_name=?",
		(category,)
	)
	dishes = cursor.fetchall()
	cursor.close()
	
	return render_template(
		"admin/menu.html",
		categories=categories,
		selected_category=category,
		dishes=dishes
	)


# Edit Dish
@admin_bp.route("/edit_dish", methods=["GET", "POST"])
def edit_dish():
	if not session.get('logged_in'):
		return redirect(url_for("admin.login"))
	
	dish_id = request.args.get("id")
	db = get_db()
	cursor = db.cursor()
	
	cursor.execute("SELECT * FROM dishes WHERE id=?", (dish_id,))
	dish = cursor.fetchone()
	
	cursor.execute("SELECT id, name FROM categories")
	categories = cursor.fetchall()
	
	if request.method == "POST":
		name = request.form["name"]
		category_name = request.form["category"]
		half_price = request.form.get("half_price") or None
		full_price = request.form.get("full_price") or None
		single_price = request.form.get("single_price") or None
		available = 1 if request.form.get("available") == "on" else 0
		is_veg = 1 if request.form.get("is_veg") == "1" else 0
		
		cursor.execute("""
            UPDATE dishes SET name=?, category_name=?, half_price=?, full_price=?,
            single_price=?, available=?, is_veg=? WHERE id=?
        """, (name, category_name, half_price, full_price, single_price, available, is_veg, dish_id))
		db.commit()
		flash("Dish updated successfully!", "success")
		return redirect(url_for("admin.menu", category=category_name))
	
	cursor.close()
	return render_template("admin/edit_dish.html", dish=dish, categories=categories)


@admin_bp.route("/delete_dish")
def delete_dish():
	if not session.get('logged_in'):
		return redirect(url_for("admin.login"))
	
	dish_id = request.args.get("id")
	db = get_db()
	cursor = db.cursor()
	
	cursor.execute("SELECT image FROM dishes WHERE id=?", (dish_id,))
	dish = cursor.fetchone()
	
	if dish and dish['image']:
		image_path = os.path.join(current_app.root_path, 'static', 'images', dish['image'])
		if os.path.exists(image_path):
			os.remove(image_path)
	
	cursor.execute("DELETE FROM dishes WHERE id=?", (dish_id,))
	db.commit()
	cursor.close()
	
	flash("Dish deleted successfully!", "info")
	return redirect(url_for("admin.menu"))


UPLOAD_FOLDER = "static/images"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}


def allowed_file(filename):
	return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@admin_bp.route("/add_dish", methods=["GET", "POST"])
def add_dish():
	db = get_db()
	cursor = db.cursor()
	
	if request.method == "POST":
		category_name = request.form["category"]
		name = request.form["name"]
		available = 1 if "available" in request.form else 0
		is_veg = 1 if request.form.get("is_veg") == "1" else 0
		
		half_price = request.form.get("half_price") or None
		full_price = request.form.get("full_price") or None
		single_price = request.form.get("single_price") or None
		
		cursor.execute("""
            INSERT INTO dishes (category_name, name, available, half_price, full_price, single_price, is_veg)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (category_name, name, available, half_price, full_price, single_price, is_veg))
		db.commit()
		
		dish_id = cursor.lastrowid
		
		image = None
		if "image" in request.files:
			file = request.files["image"]
			if file and allowed_file(file.filename):
				ext = os.path.splitext(file.filename)[1]
				filename = f"{dish_id}{ext}"
				file.save(os.path.join(UPLOAD_FOLDER, filename))
				image = filename
				
				cursor.execute("UPDATE dishes SET image=? WHERE id=?", (image, dish_id))
				db.commit()
		
		cursor.close()
		flash("✅ Dish added successfully!", "success")
		return redirect(url_for("admin.menu", category=category_name))
	
	cursor.execute("SELECT id, name FROM categories")
	categories = cursor.fetchall()
	cursor.close()
	
	return render_template("admin/add_dish.html", categories=categories)


# Get all categories
@admin_bp.route("/categories")
def categories_page():
	db = get_db()
	cursor = db.cursor()
	cursor.execute("SELECT * FROM categories ORDER BY id")
	categories = cursor.fetchall()
	cursor.close()
	return render_template("admin/category_management.html", categories=categories)


# Add new category
@admin_bp.route("/add_category", methods=["POST"])
def add_category():
	name = request.form.get("category_name")
	if name:
		db = get_db()
		cursor = db.cursor()
		cursor.execute("INSERT INTO categories (name) VALUES (?)", (name,))
		db.commit()
		cursor.close()
	return redirect(url_for("admin.categories_page"))


# Edit category
@admin_bp.route("/edit_category/<category_name>", methods=["GET", "POST"])
def edit_category(category_name):
	db = get_db()
	cursor = db.cursor()
	
	if request.method == "POST":
		new_name = request.form.get("category_name")
		if new_name:
			cursor.execute("UPDATE categories SET name=? WHERE name=?", (new_name, category_name))
			cursor.execute("UPDATE dishes SET category_name=? WHERE category_name=?", (new_name, category_name))
			db.commit()
			cursor.close()
			return redirect(url_for("admin.categories_page"))
	
	cursor.execute("SELECT * FROM categories WHERE name=?", (category_name,))
	category = cursor.fetchone()
	cursor.close()
	if not category:
		flash("Category not found", "danger")
		return redirect(url_for("admin.categories_page"))
	
	return render_template("admin/edit_category.html", category_name=category_name)


# Delete category
@admin_bp.route("/delete_category/<category_name>", methods=["POST"])
def delete_category(category_name):
	db = get_db()
	cursor = db.cursor()
	
	cursor.execute("SELECT image FROM dishes WHERE category_name=?", (category_name,))
	dishes = cursor.fetchall()
	
	for dish in dishes:
		if dish['image']:
			image_path = os.path.join(current_app.root_path, 'static', 'images', dish['image'])
			if os.path.exists(image_path):
				os.remove(image_path)
	
	cursor.execute("DELETE FROM dishes WHERE category_name=?", (category_name,))
	cursor.execute("DELETE FROM categories WHERE name=?", (category_name,))
	
	db.commit()
	cursor.close()
	
	return redirect(url_for("admin.categories_page"))


@admin_bp.route("/payment_methods", methods=["GET", "POST"])
def payment_methods():
	if not session.get('logged_in'):
		return redirect(url_for("admin.login"))
	
	db = get_db()
	cursor = db.cursor()
	
	if request.method == "POST":
		if 'add_method' in request.form:
			name = request.form.get("name")
			if name:
				try:
					cursor.execute("INSERT INTO payments_type (Payment_methods) VALUES (?)", (name,))
					db.commit()
					flash("Payment method added successfully!", "success")
				except sqlite3.IntegrityError:
					flash(f"Error: Method '{name}' already exists.", "danger")
		elif 'delete_method' in request.form:
			method_name = request.form.get("method_name")
			try:
				cursor.execute("DELETE FROM payments_type WHERE Payment_methods=?", (method_name,))
				db.commit()
				flash("Payment method deleted successfully!", "danger")
			except sqlite3.Error as err:
				flash(f"Error: {err}", "danger")
		
		return redirect(url_for("admin.payment_methods"))
	
	cursor.execute("SELECT Payment_methods FROM payments_type")
	methods = [row[0] for row in cursor.fetchall()]
	cursor.close()
	return render_template("admin/payment_methods.html", methods=methods)


@admin_bp.route("/reports")
def reports():
	if not session.get('logged_in'):
		return redirect(url_for("admin.login"))
	
	db = get_db()
	cursor = db.cursor()
	
	from_date = request.args.get('from_date')
	to_date = request.args.get('to_date')
	from_time = request.args.get('from_time')
	to_time = request.args.get('to_time')
	order_id = request.args.get('order_id')
	table_no = request.args.get('table_no')
	payment_type = request.args.get('payment_type')
	item_name = request.args.get('item_name')
	
	query = "SELECT * FROM All_Orders"
	conditions = []
	params = []
	
	if from_date and from_time:
		start_datetime = f"{from_date} {from_time}"
		conditions.append("date_time >= ?")
		params.append(start_datetime)
	elif from_date:
		conditions.append("date(date_time) >= ?")
		params.append(from_date)
	
	if to_date and to_time:
		end_datetime = f"{to_date} {to_time}"
		conditions.append("date_time <= ?")
		params.append(end_datetime)
	elif to_date:
		conditions.append("date(date_time) <= ?")
		params.append(to_date)
	
	if order_id:
		conditions.append("Order_id = ?")
		params.append(order_id)
	if table_no:
		conditions.append("table_no = ?")
		params.append(table_no)
	if payment_type:
		conditions.append("payment_type = ?")
		params.append(payment_type)
	if item_name:
		conditions.append("item LIKE ?")
		params.append(f"%{item_name}%")
	
	if conditions:
		query += " WHERE " + " AND ".join(conditions)
	
	query += " ORDER BY date_time DESC"
	
	cursor.execute(query, tuple(params))
	all_orders = cursor.fetchall()
	
	total_sales_query = "SELECT SUM(Quantity * price) AS total_sales FROM All_Orders"
	if conditions:
		total_sales_query += " WHERE " + " AND ".join(conditions)
	
	cursor.execute(total_sales_query, tuple(params))
	total_sales = cursor.fetchone()['total_sales'] or 0
	
	cursor.execute("SELECT Payment_methods FROM payments_type")
	payment_methods = [row['Payment_methods'] for row in cursor.fetchall()]
	cursor.close()
	
	return render_template("admin/reports.html",
	                       all_orders=all_orders,
	                       total_sales=total_sales,
	                       from_date=from_date,
	                       to_date=to_date,
	                       from_time=from_time,
	                       to_time=to_time,
	                       order_id=order_id,
	                       table_no=table_no,
	                       payment_type=payment_type,
	                       item_name=item_name,
	                       payment_methods=payment_methods)


@admin_bp.route("/analytics")
def analytics():
	if not session.get('logged_in'):
		return redirect(url_for("admin.login"))
	
	db = get_db()
	cursor = db.cursor()
	
	# 1. Sales over time (last 30 days)
	cursor.execute("""
        SELECT date(date_time) AS sales_date, SUM(Quantity * price) AS total_sales
        FROM All_Orders
        WHERE date_time >= strftime('%Y-%m-%d %H:%M:%S', 'now', '-30 days')
        GROUP BY sales_date
        ORDER BY sales_date ASC
    """)
	daily_sales_data = cursor.fetchall()
	
	daily_sales_labels = [row['sales_date'] for row in daily_sales_data]
	daily_sales_values = [row['total_sales'] for row in daily_sales_data]
	
	# 2. Revenue by payment type
	cursor.execute("""
        SELECT payment_type, SUM(Quantity * price) AS total_revenue
        FROM All_Orders
        GROUP BY payment_type
    """)
	payment_revenue_data = cursor.fetchall()
	
	payment_labels = [row['payment_type'] for row in payment_revenue_data]
	payment_values = [row['total_revenue'] for row in payment_revenue_data]
	
	# 3. Top 5 best-selling dishes
	cursor.execute("""
        SELECT item, SUM(Quantity) AS total_sold
        FROM All_Orders
        GROUP BY item
        ORDER BY total_sold DESC
        LIMIT 5
    """)
	top_dishes_data = cursor.fetchall()
	
	top_dishes_labels = [row['item'] for row in top_dishes_data]
	top_dishes_values = [row['total_sold'] for row in top_dishes_data]
	
	cursor.close()
	
	return render_template(
		"admin/analytices.html",
		daily_sales_labels=daily_sales_labels,
		daily_sales_values=daily_sales_values,
		payment_labels=payment_labels,
		payment_values=payment_values,
		top_dishes_labels=top_dishes_labels,
		top_dishes_values=top_dishes_values
	)


@admin_bp.route("/logout")
def logout():
	session.pop("logged_in", None)
	session.pop("last_activity", None)
	session.pop("admin_device_id", None)
	session.clear()
	flash("Logged out successfully.", "info")
	return redirect(url_for("admin.login"))


app.register_blueprint(admin_bp, url_prefix="/admin")

# -------------------- Customer Blueprint --------------------
customer_bp = Blueprint("customer", __name__, template_folder="templates/customer")

CARTS_FOLDER = "carts"
if not os.path.exists(CARTS_FOLDER):
	os.makedirs(CARTS_FOLDER)


def get_cart_file_path(table_number):
	return os.path.join(CARTS_FOLDER, f"cart_{table_number}.json")


def load_cart(table_number):
	file_path = get_cart_file_path(table_number)
	if os.path.exists(file_path):
		with open(file_path, 'r') as f:
			return json.load(f)
	return {}


def save_cart(table_number, cart_data):
	file_path = get_cart_file_path(table_number)
	with open(file_path, 'w') as f:
		json.dump(cart_data, f, indent=4)


@customer_bp.route("/customer")
def customer_menu():
	table = request.args.get("table")
	if not table:
		return "Table number is required.", 400
	
	category = request.args.get("category")
	db = get_db()
	cursor = db.cursor()
	cursor.execute("SELECT * FROM categories")
	categories = cursor.fetchall()
	
	if not category and categories:
		category = categories[0]['name']
	
	dishes = []
	if category:
		cursor.execute(
			"SELECT * FROM dishes WHERE available=1 AND category_name=?",
			(category,)
		)
		dishes = cursor.fetchall()
	cursor.close()
	
	cart = load_cart(table)
	
	return render_template(
		"customer/customer_menu.html",
		categories=categories,
		dishes=dishes,
		selected_category=category,
		table_number=table,
		cart=cart
	)


@customer_bp.route("/update-cart", methods=["POST"])
def update_cart():
	data = request.get_json()
	cart_data = data.get('cart', {})
	table_number = data.get('table')
	
	save_cart(table_number, cart_data)
	
	return jsonify({"success": True})


@customer_bp.route("/add-to-cart", methods=["POST"])
def add_to_cart():
	if request.method == "POST":
		data = request.get_json()
		
		table_number = data.get('table')
		cart_data = data.get('cart', {})
		
		save_cart(table_number, cart_data)
		return jsonify({"success": True})
	table = request.args.get("table")
	if not table:
		return "Table number is required.", 400


@customer_bp.route("/checkout")
def checkout():
	table = request.args.get("table")
	if not table:
		return "Table number is required.", 400
	
	cart = load_cart(table)
	
	cart_items = []
	total_price = 0
	
	for item_key, item_data in cart.items():
		subtotal = item_data['price'] * item_data['quantity']
		total_price += subtotal
		
		cart_items.append({
			'id': item_data['id'],
			'name': item_data['name'],
			'portion': item_data['portion'],
			'price': item_data['price'],
			'image': item_data['image'],
			'quantity': item_data['quantity'],
			'subtotal': subtotal
		})
	
	return render_template("customer/checkout.html",
	                       table_number=table,
	                       cart_items=cart_items,
	                       total_price=total_price)


@customer_bp.route("/place_order", methods=["POST"])
def place_order():
	data = request.get_json()
	table_number = data.get('table_number')
	
	order_id = "ORD" + str(int(time.time()))
	
	cart_data = load_cart(table_number)
	
	db = get_db()
	cursor = db.cursor()
	
	try:
		for item_key, item in cart_data.items():
			dish_name = item['name']
			item_type = item['portion']
			quantity = item['quantity']
			price = item['price']
			status = 'Pending'
			message = item.get('request', '')
			
			sql = """
                INSERT INTO current_order
                (table_no, order_id, dish_name, type, quantity, Price, status, message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
			val = (table_number, order_id, dish_name, item_type, quantity, price, status, message)
			cursor.execute(sql, val)
		
		db.commit()
	
	except sqlite3.Error as err:
		print(f"Error: {err}")
		return jsonify({"success": False, "message": "Database error"})
	finally:
		cursor.close()
	
	cart_file_path = get_cart_file_path(table_number)
	if os.path.exists(cart_file_path):
		os.remove(cart_file_path)
	
	return jsonify({"success": True, "order_id": order_id})


@customer_bp.route("/order-confirmation")
def order_confirmation():
	order_id = request.args.get("order_id")
	table_number = request.args.get("table")
	return render_template("order_confirmation.html", order_id=order_id, table_number=table_number)


@customer_bp.route("/order_status/")
def order_status():
	table_no = request.args.get("table")
	db = get_db()
	cursor = db.cursor()
	
	cursor.execute("SELECT status FROM current_order WHERE table_no = ?", (table_no,))
	statuses = cursor.fetchall()
	
	if not statuses:
		status = "No Order Found"
	else:
		all_completed = all(s['status'] == 'Completed' for s in statuses)
		if all_completed:
			status = "Ready for Billing"
		else:
			status = "In Progress"
	
	cursor.close()
	
	return render_template("order_status.html", table_no=table_no, status=status)


app.register_blueprint(customer_bp, url_prefix="/customer")

# -------------------- kitchen Blueprint --------------------
kitchen_bp = Blueprint("kitchen", __name__, template_folder="templates/kitchen")


@kitchen_bp.route("/login", methods=["GET", "POST"])
def login():
	if request.method == "POST":
		password = request.form['password']
		db = get_db()
		cursor = db.cursor()
		cursor.execute("SELECT kitchen_password FROM login")
		saved_password = cursor.fetchone()['kitchen_password']
		cursor.close()
		
		if password == saved_password:
			session['is_kitchen'] = True
			session['Kitchen_device_id'] = request.remote_addr
			session['kitchen_last_activity'] = time.time()
			return redirect(url_for("kitchen.orders"))
		else:
			return render_template("kitchen/kitchen_login.html", error=True)
	
	return render_template("kitchen/kitchen_login.html", error=False)


@kitchen_bp.route("/logout", methods=["GET", "POST"])
def k_logout():
	session.pop("is_kitchen", None)
	session.pop("Kitchen_device_id", None)
	session.pop("kitchen_last_activity", None)
	return redirect(url_for("kitchen.login"))


@kitchen_bp.before_request
def before_kitchen_request():
	if request.endpoint and request.endpoint.startswith('kitchen.'):
		if request.endpoint == 'kitchen.login':
			return
		
		if not session.get('is_kitchen'):
			return redirect(url_for("kitchen.login"))
		
		if session.get('Kitchen_device_id') != request.remote_addr:
			flash("Access denied. You can only access this page from the device you logged in on.", "danger")
			session.clear()
			return redirect(url_for("kitchen.login"))
		
		if is_session_expired("kitchen"):
			session.clear()
			flash("Your session has expired. Please log in again.", "info")
			return redirect(url_for("kitchen.login"))


@kitchen_bp.route("/orders", methods=["GET", "POST"])
def orders():
	db = get_db()
	cursor = db.cursor()
	
	if request.method == "POST":
		if 'update_status' in request.form:
			order_id = request.form.get('order_id')
			new_status = request.form.get('new_status')
			try:
				cursor.execute(
					"UPDATE current_order SET status = ? WHERE order_id = ?",
					(new_status, order_id)
				)
				db.commit()
				flash("Order status updated!", "success")
			except sqlite3.Error as err:
				flash(f"Error updating status: {err}", "danger")
		
		elif 'update_quantity' in request.form:
			item_id = request.form.get('item_id')
			new_quantity = request.form.get('quantity')
			try:
				cursor.execute(
					"UPDATE current_order SET quantity = ? WHERE id = ?",
					(new_quantity, item_id)
				)
				db.commit()
				flash("Item quantity updated!", "success")
			except sqlite3.Error as err:
				flash(f"Error updating quantity: {err}", "danger")
		
		elif 'delete_item' in request.form:
			item_id = request.form.get('item_id')
			try:
				cursor.execute(
					"DELETE FROM current_order WHERE id = ?",
					(item_id,)
				)
				db.commit()
				flash("Order item deleted successfully!", "danger")
			except sqlite3.Error as err:
				flash(f"Error deleting item: {err}", "danger")
		return redirect(url_for("kitchen.orders"))
	
	cursor.execute("SELECT * FROM current_order ORDER BY table_no")
	raw_orders = cursor.fetchall()
	
	orders = {}
	for item in raw_orders:
		order_id = item['order_id']
		if order_id not in orders:
			orders[order_id] = {
				'table_no': item['table_no'],
				'items': [],
				'status': item['status']
			}
		orders[order_id]['items'].append(item)
	
	is_table_empty = len(raw_orders) == 0
	cursor.close()
	return render_template("kitchen/orders.html", orders=orders, is_table_empty=is_table_empty)


@kitchen_bp.route("/orders_json")
def orders_json():
	db = get_db()
	cursor = db.cursor()
	cursor.execute("SELECT * FROM current_order ORDER BY table_no, id")
	raw_orders = cursor.fetchall()
	cursor.close()
	
	orders = {}
	for item in raw_orders:
		order_id = item['order_id']
		if order_id not in orders:
			orders[order_id] = {
				'table_no': item['table_no'],
				'items': [],
				'status': item['status']
			}
		orders[order_id]['items'].append(item)
	
	return jsonify(orders)


@kitchen_bp.route("/bills")
def bills():
	db = get_db()
	cursor = db.cursor()
	
	cursor.execute("SELECT * FROM current_order WHERE status = 'Completed' ORDER BY table_no, id")
	raw_orders = cursor.fetchall()
	cursor.close()
	
	orders_to_bill = {}
	for item in raw_orders:
		table_no = item['table_no']
		if table_no not in orders_to_bill:
			orders_to_bill[table_no] = {
				'items': [],
				'total_price': 0,
				'order_ids': set()
			}
		orders_to_bill[table_no]['items'].append(item)
		orders_to_bill[table_no]['total_price'] += item['quantity'] * item['Price']
		orders_to_bill[table_no]['order_ids'].add(item['order_id'])
	
	db = get_db()
	cursor = db.cursor()
	cursor.execute("SELECT Payment_methods FROM payments_type")
	payment_types = [row['Payment_methods'] for row in cursor.fetchall()]
	cursor.close()
	
	return render_template("kitchen/bills.html", orders=orders_to_bill, payment_types=payment_types)


@kitchen_bp.route("/generate_bill_pdf/<table_no>")
def generate_bill_pdf(table_no):
	if not session.get('logged_in'):
		return redirect(url_for("admin.login"))
	
	db = get_db()
	cursor = db.cursor()
	cursor.execute("SELECT * FROM current_order WHERE status = 'Completed' AND table_no = ?", (table_no,))
	order_items = cursor.fetchall()
	cursor.close()
	
	if not order_items:
		flash("Order not found.", "danger")
		return redirect(url_for("kitchen.bills"))
	
	buffer = BytesIO()
	p = canvas.Canvas(buffer, pagesize=letter)
	p.setFont("Helvetica-Bold", 16)
	
	p.drawString(50, 750, "Restaurant Bill")
	p.setFont("Helvetica", 12)
	p.drawString(50, 730, f"Table: {table_no}")
	p.drawString(50, 715, f"Date: {time.strftime('%Y-%m-%d %H:%M')}")
	
	y_position = 690
	total = 0
	
	p.drawString(50, y_position, "Item")
	p.drawString(300, y_position, "Quantity")
	p.drawString(400, y_position, "Price")
	p.drawString(500, y_position, "Subtotal")
	y_position -= 15
	
	p.line(50, y_position, 550, y_position)
	y_position -= 20
	
	for item in order_items:
		p.drawString(50, y_position, f"{item['dish_name']} ({item['type']})")
		p.drawString(300, y_position, str(item['quantity']))
		p.drawString(400, y_position, f"₹{item['Price']:.2f}")
		subtotal = item['quantity'] * item['Price']
		p.drawString(500, y_position, f"₹{subtotal:.2f}")
		total += subtotal
		y_position -= 15
	
	y_position -= 20
	p.line(50, y_position, 550, y_position)
	y_position -= 15
	p.setFont("Helvetica-Bold", 14)
	p.drawString(400, y_position, f"Total: ₹{total:.2f}")
	
	p.showPage()
	p.save()
	
	buffer.seek(0)
	return send_file(
		buffer,
		as_attachment=True,
		download_name=f'bill_table_{table_no}.pdf',
		mimetype='application/pdf'
	)


@kitchen_bp.route("/finalize_bill", methods=["POST"])
def finalize_bill():
	table_no = request.form.get('table_no')
	payment_type = request.form.get('payment_type')
	
	db = get_db()
	cursor = db.cursor()
	
	try:
		cursor.execute("SELECT * FROM current_order WHERE table_no = ? AND status = 'Completed'", (table_no,))
		items = cursor.fetchall()
		
		if items:
			total_amount = sum(item['Price'] * item['quantity'] for item in items)
			
			sql_insert_all_orders = """
                INSERT INTO All_Orders (Order_id, item, type, Quantity, price, date_time, payment_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """
			for item in items:
				cursor.execute(sql_insert_all_orders, (
					item['order_id'],
					item['dish_name'],
					item['type'],
					item['quantity'],
					item['Price'],
					datetime.now().isoformat(),  # Use ISO format for SQLite TEXT
					payment_type
				))
			
			cursor.execute("DELETE FROM current_order WHERE table_no = ? AND status = 'Completed'", (table_no,))
			
			db.commit()
			flash(f"Bill for Table {table_no} has been finalized and paid via {payment_type}!", "success")
	
	except sqlite3.Error as err:
		flash(f"Error finalizing bill: {err}", "danger")
		db.rollback()
	finally:
		cursor.close()
	
	return redirect(url_for("kitchen.bills"))


@kitchen_bp.route("/reset_order_id", methods=["POST"])
def reset_order_id():
	db = get_db()
	cursor = db.cursor()
	cursor.execute("SELECT COUNT(*) FROM current_order")
	count = cursor.fetchone()[0]
	
	if count == 0:
		cursor.execute("DELETE FROM sqlite_sequence WHERE name='current_order'")
		flash("Table ID has been reset.", "success")
		db.commit()
	else:
		flash("Cannot reset ID. The table is not empty.", "danger")
	
	cursor.close()
	return redirect(url_for("kitchen.orders"))


app.register_blueprint(kitchen_bp, url_prefix="/kitchen")


# -------------------- Default Route --------------------
@app.route("/")
def home():
	return redirect(url_for("customer.customer_menu", table="1"))


@app.route("/admin")
def admin():
	return redirect(url_for("admin.dashboard"))


@app.route("/kitchen")
def kitchen():
	return redirect(url_for("kitchen.orders"))


# -------------------- Run App --------------------
if __name__ == "__main__":
	app.run(host="0.0.0.0", port=8000, debug=True)
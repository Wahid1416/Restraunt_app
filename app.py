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
)
import mysql.connector
import os
import json
import time
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from flask import current_app,g
import random


def get_db():
    if 'db' not in g:
        g.db = mysql.connector.connect(
            host=os.getenv("DB_HOST", "database-1.cveq8go2apfa.ap-south-1.rds.amazonaws.com"),  # fallback for local dev
            user=os.getenv("DB_USER", "admin"),
            password=os.getenv("DB_PASSWORD", "Wahid123"),  # your local MySQL password
            database=os.getenv("DB_NAME", "Restraunt"),
            auth_plugin='caching_sha2_password'  # ✅ works with MySQL 8/9
        )
    return g.db


# def get_db():
#     if 'db' not in g:
#         g.db = mysql.connector.connect(
#             host=os.getenv("DB_HOST", "localhost"),  # fallback for local dev
#             user=os.getenv("DB_USER", "root"),
#             password=os.getenv("DB_PASSWORD", ""),  # your local MySQL password
#             database=os.getenv("DB_NAME", "Restraunt"),
#             auth_plugin='caching_sha2_password'  # ✅ works with MySQL 8/9
#         )
#     return g.db
# -------------------- Flask App Setup --------------------
app = Flask(__name__)
app.secret_key = "supersecret"  # change in production

from twilio.rest import Client


# Twilio credentials (from console)
# account_sid = "ACc1b4158045f261a8cb58792d620d11fd"
# auth_token = "fa323539bcd623644474800f7ef6a154"
# twilio_number = "+17627950927"   # Your Twilio phone number

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_number = os.getenv("TWILIO_NUMBER")


client = Client(account_sid, auth_token)

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
    # Check if the session is not logged in or if the last activity timestamp is missing
    
    if x=="admin":
        if 'logged_in' not in session or 'last_activity' not in session:
            return True
        # Define the session timeout duration in seconds (1 hour = 3600 seconds)
        timeout = 3600
        
        # Check if the time since the last activity exceeds the timeout
        if time.time() - session['last_activity'] > timeout:
            return True
        
        # Update the last activity time on every request
        session['last_activity'] = time.time()
    
    if x=="kitchen":
        if 'is_kitchen' not in session or 'kitchen_last_activity' not in session:
            return True
        # Define the session timeout duration in seconds (1 hour = 3600 seconds)
        timeout = 3600*24
        
        # Check if the time since the last activity exceeds the timeout
        if time.time() - session['kitchen_last_activity'] > timeout:
            return True
        
        # Update the last activity time on every request
        session['kitchen_last_activity'] = time.time()
    return False


def cleanup_old_orders():
    db = get_db()
    cursor = db.cursor()
    
    try:
        # SQL query to delete all records from the All_Orders table older than 365 days
        cursor.execute("DELETE FROM All_Orders WHERE date_time < NOW() - INTERVAL 365 DAY")
        db.commit()
        
        # Return a success message
        print("sucess fully cleaned old orders")
    
    except mysql.connector.Error as err:
        # Return an error message if the query fails
        print("Error")
    
    cursor.close()
        
        
@admin_bp.before_request
def before_admin_request():
    if request.endpoint and request.endpoint.startswith('admin.'):
        # Exclude the login and forget_password pages from the check
        if request.endpoint not in ['admin.login', 'admin.forget_password']:
            if session.get('admin_device_id') != request.remote_addr:
                flash("Access denied. You can only access this page from the device you logged in on.", "danger")
                session.clear()
                return redirect(url_for("admin.login"))
            if is_session_expired("admin"):
                session.clear()
                flash("Your session has expired. Please log in again.", "info")
                return redirect(url_for("admin.login"))
    return

@admin_bp.route("/login",methods=["GET","POST"])
def login():
    try:
        message=request.args.get("message")
    except:
        message=None
    if request.method == "POST":
        un=request.form['username']
        ps=request.form['password']
        db = get_db()
        cursor = db.cursor(dictionary=True)  # ✅ dictionary=True → results as dict
        cursor.execute("SELECT * FROM login")  # ✅ no quotes around table name
        k = cursor.fetchall()[0]
        cursor.close()
        if k['Username']==un and k['Pass']==ps:
            session['last_activity'] = time.time()
            session['logged_in'] = True
            session['admin_device_id'] = request.remote_addr
            # print(ps)
            return redirect(url_for("admin.dashboard"))
        else:
            # print(un)
            return render_template("admin_login.html",error=True,message=message)
    return render_template("admin_login.html",error=False,message=message)

@admin_bp.route("/forget_password", methods=["GET","POST"])
def forget_password():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM login")
    k = cursor.fetchall()[0]
    cursor.close()
    print(k)
    if request.method == "POST":
        try:
            phone = int(request.form["phone"])
        except:
            return render_template("forget_password.html", val=str(k['phone_number'])[-4:], error=True)
        if phone==k['phone_number']:
            session["otp"] = str(random.randint(100000, 999999))
            send_otp("+91"+str(phone), session["otp"])
            return render_template("verify_otp.html",error=False)
        else:
            return render_template("forget_password.html",val=str(k['phone_number'])[-4:],error=True)
    return render_template("forget_password.html",val=str(k['phone_number'])[-4:],error=False)

@app.route("/verify_otp",methods=["POST"])
def verify_otp():
    try:
        otp = request.form['otp']
    except:
        return render_template("verify_otp.html",error=True)
    
    if otp==session['otp']:
        return render_template("reset_password.html",error=False)
    
    return render_template("verify_otp.html",error=True)

@app.route("/reset_password",methods=["POST"])
def reset_password():
    type=request.form['account_type']
    password = request.form['new_password']
    confirm_password = request.form['confirm_password']
    if type=="":
        return render_template("reset_password.html",error=True,message="Select proper account type")
    elif password!=confirm_password:
        return render_template("reset_password.html",error=True,message="Passwords and Confirm Password do not match")
    else:
        db=get_db()
        cursor = db.cursor(dictionary=True)
        if type=="kitchen":
            cursor.execute(f"UPDATE login SET kitchen_password='{password}'")
        elif type=="admin":
            cursor.execute(f"UPDATE login SET Pass='{password}'")
        db.commit()
        cursor.close()
        session.pop("otp", None)
        flash(" password reset successfully. Please login.", "success")
        return redirect(url_for("admin.login",message="Password reset successful"))
        
        
        
# In app.py, within the admin_bp blueprint

from datetime import date, timedelta

@admin_bp.route("/dashboard")
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for("admin.login"))
    
    cleanup_old_orders()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Calculate today's sales
    today = date.today()
    cursor.execute("SELECT SUM(Quantity * price) AS total FROM All_Orders WHERE DATE(date_time) = %s", (today,))
    sales_today = cursor.fetchone()['total'] or 0

    # Calculate yesterday's sales
    yesterday = date.today() - timedelta(days=1)
    cursor.execute("SELECT SUM(Quantity * price) AS total FROM All_Orders WHERE DATE(date_time) = %s", (yesterday,))
    sales_yesterday = cursor.fetchone()['total'] or 0

    # Fetch data for the sales chart (last 5 days)
    cursor.execute("""
        SELECT DATE(date_time) as sales_date, SUM(Quantity * price) as total_sales
        FROM All_Orders
        WHERE date_time >= CURDATE() - INTERVAL 5 DAY
        GROUP BY sales_date
        ORDER BY sales_date
    """)
    chart_data_rows = cursor.fetchall()

    chart_labels = [row['sales_date'].strftime('%Y-%m-%d') for row in chart_data_rows]
    chart_data_values = [row['total_sales'] for row in chart_data_rows]

    cursor.close()

    return render_template(
        "admin/dashboard.html",
        sales_today=sales_today,
        sales_yesterday=sales_yesterday, # ✅ NEW: Pass yesterday's sales
        chart_labels=chart_labels,
        chart_data=chart_data_values
    )


@admin_bp.route("/menu")
def menu():
    if not session.get('logged_in'):
        return redirect(url_for("admin.login"))

    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Get all categories from dishes table
    cursor.execute("SELECT `name` FROM categories")
    categories = [i["name"] for i in cursor.fetchall()]
    # print(categories)
    if not categories:
        categories = ["Default"]  # fallback if table empty

    # Get selected category from query string or default to first
    category = request.args.get("category", categories[0])
    
    # print(category)
    
    # If category doesn't exist, redirect to default
    if category not in categories:
        return redirect(url_for("admin.menu", category=categories[0]))

    # Fetch dishes for selected category
    cursor.execute(
        "SELECT * FROM dishes WHERE category_name=%s",
        (category,)
    )
    dishes = cursor.fetchall()
    cursor.close()
    # print(dishes)

    return render_template(
        "admin/menu.html",
        categories=categories,
        selected_category=category,
        dishes=dishes
    )


# Edit Dish
@admin_bp.route("/edit_dish", methods=["GET", "POST"])
def edit_dish():
    if session.get('logged_in') != True:
        return redirect(url_for("admin.login"))
    
    dish_id = request.args.get("id")
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Fetch dish details
    cursor.execute("SELECT * FROM dishes WHERE id=%s", (dish_id,))
    dish = cursor.fetchone()
    
    # Fetch all categories for dropdown
    cursor.execute("SELECT id, name FROM categories")
    categories = cursor.fetchall()
    
    if request.method == "POST":
        name = request.form["name"]
        category_name = request.form["category"]
        half_price = request.form.get("half_price") or None
        full_price = request.form.get("full_price") or None
        single_price = request.form.get("single_price") or None
        available = 1 if request.form.get("available") == "on" else 0
        is_veg = 1 if request.form.get("is_veg") == "1" else 0  # <-- New field
        
        # Update dish with Veg/Non-Veg
        cursor.execute("""
            UPDATE dishes SET name=%s, category_name=%s, half_price=%s, full_price=%s,
            single_price=%s, available=%s, is_veg=%s WHERE id=%s
        """, (name, category_name, half_price, full_price, single_price, available, is_veg, dish_id))
        db.commit()
        flash("Dish updated successfully!", "success")
        return redirect(url_for("admin.menu", category=category_name))  # Redirect to updated category
    
    cursor.close()
    return render_template("admin/edit_dish.html", dish=dish, categories=categories)


@admin_bp.route("/delete_dish")
def delete_dish():
    if session.get('logged_in') != True:
        return redirect(url_for("admin.login"))
    
    dish_id = request.args.get("id")
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # 1️⃣ Fetch the dish to get the image
    cursor.execute("SELECT image FROM dishes WHERE id=%s", (dish_id,))
    dish = cursor.fetchone()
    
    # 2️⃣ Delete the image file if it exists
    if dish and dish['image']:
        image_path = os.path.join(current_app.root_path, 'static', 'images', dish['image'])
        if os.path.exists(image_path):
            os.remove(image_path)
    
    # 3️⃣ Delete the dish from the database
    cursor.execute("DELETE FROM dishes WHERE id=%s", (dish_id,))
    db.commit()
    cursor.close()
    
    flash("Dish deleted successfully!", "info")
    return redirect(url_for("admin.menu"))


UPLOAD_FOLDER = "static/images"  # update if needed
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@admin_bp.route("/add_dish", methods=["GET", "POST"])
def add_dish():
    db = get_db()
    cursor = db.cursor(dictionary=True)  # dictionary=True gives results as dict

    if request.method == "POST":
        category_name = request.form["category"]
        name = request.form["name"]
        available = 1 if "available" in request.form else 0
        is_veg = 1 if request.form.get("is_veg") == "1" else 0

        half_price = request.form.get("half_price") or None
        full_price = request.form.get("full_price") or None
        single_price = request.form.get("single_price") or None

        # --- Insert into DB first (without image) ---
        cursor.execute("""
            INSERT INTO dishes (category_name, name, available, half_price, full_price, single_price, is_veg)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (category_name, name, available, half_price, full_price, single_price, is_veg))
        db.commit()

        dish_id = cursor.lastrowid  # get the inserted dish's ID

        # --- Handle Image ---
        image = None
        if "image" in request.files:
            file = request.files["image"]
            if file and allowed_file(file.filename):
                # Use the dish ID as filename and preserve the extension
                ext = os.path.splitext(file.filename)[1]
                filename = f"{dish_id}{ext}"
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                image = filename

                # Update dish record with image filename
                cursor.execute("UPDATE dishes SET image=%s WHERE id=%s", (image, dish_id))
                db.commit()

        cursor.close()
        flash("✅ Dish added successfully!", "success")
        return redirect(url_for("admin.menu", category=category_name))

    # --- Fetch categories for dropdown ---
    cursor.execute("SELECT id, name FROM categories")
    categories = cursor.fetchall()
    cursor.close()

    return render_template("admin/add_dish.html", categories=categories)


# Get all categories
@admin_bp.route("/categories")
def categories_page():
    db = get_db()
    cursor = db.cursor(dictionary=True)
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
        cursor.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
        db.commit()
        cursor.close()
    return redirect(url_for("admin.categories_page"))


# Edit category
@admin_bp.route("/edit_category/<category_name>", methods=["GET", "POST"])
def edit_category(category_name):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == "POST":
        new_name = request.form.get("category_name")
        if new_name:
            # Update category name
            cursor.execute("UPDATE categories SET name=%s WHERE name=%s", (new_name, category_name))
            # Update all dishes that belong to this category
            cursor.execute("UPDATE dishes SET category_name=%s WHERE category_name=%s", (new_name, category_name))
            db.commit()
            cursor.close()
            return redirect(url_for("admin.categories_page"))
    
    # GET → fetch category
    cursor.execute("SELECT * FROM categories WHERE name=%s", (category_name,))
    category = cursor.fetchone()
    cursor.close()
    if not category:
        flash("Category not found", "danger")
        return redirect(url_for("admin.categories_page"))
    
    return render_template("admin/edit_category.html",
                           category_name=category_name,
                           )


# Delete category


@admin_bp.route("/delete_category/<category_name>", methods=["POST"])
def delete_category(category_name):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # 1️⃣ Fetch all dishes under this category to delete images
    cursor.execute("SELECT image FROM dishes WHERE category_name=%s", (category_name,))
    dishes = cursor.fetchall()

    for dish in dishes:
        if dish['image']:
            image_path = os.path.join(current_app.root_path, 'static', 'images', dish['image'])
            if os.path.exists(image_path):
                os.remove(image_path)

    # 2️⃣ Delete all dishes under this category
    cursor.execute("DELETE FROM dishes WHERE category_name=%s", (category_name,))

    # 3️⃣ Delete category itself
    cursor.execute("DELETE FROM categories WHERE name=%s", (category_name,))

    db.commit()
    cursor.close()

    return redirect(url_for("admin.categories_page"))


# In your app.py file, within the admin_bp blueprint

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
                    cursor.execute("INSERT INTO payments_type (Payment_methods) VALUES (%s)", (name,))
                    db.commit()
                    flash("Payment method added successfully!", "success")
                except mysql.connector.Error as err:
                    flash(f"Error: {err}", "danger")
        elif 'delete_method' in request.form:
            method_name = request.form.get("method_name")
            try:
                cursor.execute("DELETE FROM payments_type WHERE Payment_methods=%s", (method_name,))
                db.commit()
                flash("Payment method deleted successfully!", "danger")
            except mysql.connector.Error as err:
                flash(f"Error: {err}", "danger")
        
        return redirect(url_for("admin.payment_methods"))
    
    # Fetch all payment methods to display
    cursor.execute("SELECT Payment_methods FROM payments_type")
    methods = [row[0] for row in cursor.fetchall()]
    cursor.close()
    print(methods)
    return render_template("admin/payment_methods.html", methods=methods)



# In your app.py file, within the admin_bp blueprint

# In your app.py file, within the admin_bp blueprint

# In your app.py file, within the admin_bp blueprint

@admin_bp.route("/reports")
def reports():
    if not session.get('logged_in'):
        return redirect(url_for("admin.login"))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    from_time = request.args.get('from_time')
    to_time = request.args.get('to_time')
    order_id = request.args.get('order_id')
    table_no = request.args.get('table_no')
    payment_type = request.args.get('payment_type')
    item_name = request.args.get('item_name')
    
    # Build the base SQL query for detailed orders
    query = "SELECT * FROM All_Orders"
    conditions = []
    params = []
    
    if from_date and from_time:
        start_datetime = f"{from_date} {from_time}"
        conditions.append("date_time >= %s")
        params.append(start_datetime)
    elif from_date:
        conditions.append("date_time >= %s")
        params.append(from_date)
    
    if to_date and to_time:
        end_datetime = f"{to_date} {to_time}"
        conditions.append("date_time <= %s")
        params.append(end_datetime)
    elif to_date:
        conditions.append("date_time <= %s")
        params.append(to_date)
    
    if order_id:
        conditions.append("Order_id = %s")
        params.append(order_id)
    if table_no:
        conditions.append("table_no = %s")
        params.append(table_no)
    if payment_type:
        conditions.append("payment_type = %s")
        params.append(payment_type)
    if item_name:
        conditions.append("item LIKE %s")
        params.append(f"%{item_name}%")
    
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += " ORDER BY date_time DESC"
    
    cursor.execute(query, tuple(params))
    all_orders = cursor.fetchall()
    
    # ✅ NEW: Query to compute total sales based on the same filters
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
                           total_sales=total_sales,  # ✅ NEW: Pass total sales to template
                           from_date=from_date,
                           to_date=to_date,
                           from_time=from_time,
                           to_time=to_time,
                           order_id=order_id,
                           table_no=table_no,
                           payment_type=payment_type,
                           item_name=item_name,
                           payment_methods=payment_methods)


# In your app.py file, within the admin_bp blueprint

@admin_bp.route("/analytics")
def analytics():
    if not session.get('logged_in'):
        return redirect(url_for("admin.login"))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # 1. Sales over time (e.g., last 30 days)
    cursor.execute("""
        SELECT DATE(date_time) AS sales_date, SUM(Quantity * price) AS total_sales
        FROM All_Orders
        WHERE date_time >= CURDATE() - INTERVAL 30 DAY
        GROUP BY sales_date
        ORDER BY sales_date ASC
    """)
    daily_sales_data = cursor.fetchall()
    
    daily_sales_labels = [row['sales_date'].strftime('%Y-%m-%d') for row in daily_sales_data]
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

# Register blueprint
app.register_blueprint(admin_bp, url_prefix="/admin")



# -------------------- Customer Blueprint --------------------



customer_bp = Blueprint("customer", __name__, template_folder="templates/customer")

# ... your other imports ...

# Define a folder for storing the cart JSON files
CARTS_FOLDER = "carts"
if not os.path.exists(CARTS_FOLDER):
    os.makedirs(CARTS_FOLDER)

# Helper function to get the cart file path for a specific table
def get_cart_file_path(table_number):
    return os.path.join(CARTS_FOLDER, f"cart_{table_number}.json")

# Helper function to read the cart from a JSON file
def load_cart(table_number):
    file_path = get_cart_file_path(table_number)
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return json.load(f)
    return {}

# Helper function to write the cart to a JSON file
def save_cart(table_number, cart_data):
    file_path = get_cart_file_path(table_number)
    with open(file_path, 'w') as f:
        json.dump(cart_data, f, indent=4)




# Make sure to include all your other imports here

# Helper function to get the cart file path for a specific table
def get_cart_file_path(table_number):
    return os.path.join("carts", f"cart_{table_number}.json")


# Helper function to read the cart from a JSON file
def load_cart(table_number):
    file_path = get_cart_file_path(table_number)
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return json.load(f)
    return {}




@customer_bp.route("/customer")
def customer_menu():
    table = request.args.get("table")
    if not table:
        return "Table number is required.", 400

    category = request.args.get("category")
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()

    if not category and categories:
        category = categories[0]['name']

    dishes = []
    if category:
        cursor.execute(
            "SELECT * FROM dishes WHERE available=1 AND category_name=%s",
            (category,)
        )
        dishes = cursor.fetchall()
    cursor.close()

    # ✅ Load the current cart from the JSON file
    cart = load_cart(table)

    return render_template(
        "customer/customer_menu.html",
        categories=categories,
        dishes=dishes,
        selected_category=category,
        table_number=table,
        cart=cart # ✅ Pass the cart to the template
    )



@customer_bp.route("/update-cart", methods=["POST"])
def update_cart():
    data = request.get_json()
    cart_data = data.get('cart', {})
    table_number = data.get('table')
    
    # Save the updated cart to the JSON file
    save_cart(table_number, cart_data)
    
    return jsonify({"success": True})

@customer_bp.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    # Handle the POST request from the menu page
    if request.method == "POST":
        data = request.get_json()
        
        # 🧪 This line will print the received JSON data to your terminal
        print("Received data from client:", data)
        
        table_number = data.get('table')
        cart_data = data.get('cart', {})
        
        # Save the received cart data to the JSON file
        save_cart(table_number, cart_data)
        return jsonify({"success": True})
    able = request.args.get("table")
    if not table:
        return "Table number is required.", 400


# In your app.py file within the customer_bp blueprint

@customer_bp.route("/checkout")
def checkout():
    table = request.args.get("table")
    if not table:
        return "Table number is required.", 400
    
    # Load the cart from the JSON file
    cart = load_cart(table)
    
    # Process the cart data to be displayed in the template
    cart_items = []
    total_price = 0
    
    for item_key, item_data in cart.items():
        # Calculate subtotal for each item
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
            # ✅ Extract the message from the cart item, defaulting to an empty string if it doesn't exist.
            message = item.get('request', '')

            sql = """
                INSERT INTO current_order
                (table_no, order_id, dish_name, type, quantity, Price, status, message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            # ✅ Add the message to the values tuple
            val = (table_number, order_id, dish_name, item_type, quantity, price, status, message)

            cursor.execute(sql, val)

        db.commit()

    except mysql.connector.Error as err:
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
    """
    Displays the real-time status of a customer's order by table number.
    """
    table_no = request.args.get("table")
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT status FROM current_order WHERE table_no = %s", (table_no,))
    statuses = cursor.fetchall()
    
    if not statuses:
        # If no items are found in current_order, check if it's a completed order
        status = "No Order Found"
    else:
        # Check the status of all items for the table
        all_completed = all(s['status'] == 'Completed' for s in statuses)
        if all_completed:
            status = "Ready for Billing"
        else:
            status = "In Progress"
    
    cursor.close()
    
    return render_template(
        "order_status.html",
        table_no=table_no,
        status=status
    )



app.register_blueprint(customer_bp, url_prefix="/customer")


# -------------------- kitchen Blueprint --------------------

kitchen_bp = Blueprint("kitchen", __name__, template_folder="templates/kitchen")


# In app.py, within the kitchen_bp blueprint

@kitchen_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form['password']
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT kitchen_password FROM login")
        saved_password = cursor.fetchone()['kitchen_password']
        cursor.close()
        print(len(saved_password))
        print(len(password))
        
        if password == saved_password:
            print("Logged in successfully")
            session['is_kitchen'] = True  # Differentiate kitchen from admin
            session['Kitchen_device_id'] = request.remote_addr  # Store device IP
            session['kitchen_last_activity'] = time.time()
            return redirect(url_for("kitchen.orders"))
        else:
            return render_template("kitchen/kitchen_login.html", error=True)
    
    return render_template("kitchen/kitchen_login.html", error=False)



@kitchen_bp.route("/logout", methods=["GET", "POST"])
def k_logout():
    session.pop("is_kitchen",None)
    session.pop("Kitchen_device_id",None)
    session.pop("kitchen_last_activity",None)
    return redirect(url_for("kitchen.login"))
# In app.py, modify the existing before_kitchen_request function

@kitchen_bp.before_request
def before_kitchen_request():
    # print("hi")
    if request.endpoint and request.endpoint.startswith('kitchen.'):
        # print("hi1")
        # Allow access to the login page
        if request.endpoint == 'kitchen.login':
            return
        
        # Check if the user is logged in as a kitchen head
        if not session.get('is_kitchen'):
            # print("hi2")
            return redirect(url_for("kitchen.login"))
        
        # Check if the device IP matches the one stored in the session
        if session.get('Kitchen_device_id') != request.remote_addr:
            # print("hi3")
            flash("Access denied. You can only access this page from the device you logged in on.", "danger")
            session.clear()
            return redirect(url_for("kitchen.login"))
        
        # Check for session expiration
        if is_session_expired("kitchen"):
            # print("hi4")
            session.clear()
            # print("please login again")
            flash("Your session has expired. Please log in again.", "info")
            return redirect(url_for("kitchen.login"))
    

@kitchen_bp.route("/orders", methods=["GET", "POST"])
def orders():
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == "POST":
        if 'update_status' in request.form:
            order_id = request.form.get('order_id')
            new_status = request.form.get('new_status')
            try:
                cursor.execute(
                    "UPDATE current_order SET status = %s WHERE order_id = %s",
                    (new_status, order_id)
                )
                db.commit()
                flash("Order status updated!", "success")
            except mysql.connector.Error as err:
                flash(f"Error updating status: {err}", "danger")
        
        elif 'update_quantity' in request.form:
            item_id = request.form.get('item_id')
            new_quantity = request.form.get('quantity')
            try:
                cursor.execute(
                    "UPDATE current_order SET quantity = %s WHERE id = %s",
                    (new_quantity, item_id)
                )
                db.commit()
                flash("Item quantity updated!", "success")
            except mysql.connector.Error as err:
                flash(f"Error updating quantity: {err}", "danger")
        
        
        elif 'delete_item' in request.form:
            item_id = request.form.get('item_id')
            try:
                cursor.execute(
                    "DELETE FROM current_order WHERE id = %s",
                    (item_id,)
                )
                db.commit()
                flash("Order item deleted successfully!", "danger")
            except mysql.connector.Error as err:
                flash(f"Error deleting item: {err}", "danger")
        return redirect(url_for("kitchen.orders"))
    
    cursor.execute("SELECT * FROM current_order ORDER BY table_no")
    raw_orders = cursor.fetchall()
    
    # for i in raw_orders:
    #     print(i)
    
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
    for i in orders.keys():
        print(orders[i])
    return render_template(
        "kitchen/orders.html",
        orders=orders,
        is_table_empty=is_table_empty
    )


# In your app.py file, within the kitchen_bp blueprint

@kitchen_bp.route("/orders_json")
def orders_json():
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
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


# In app.py, within the customer_bp blueprint




# Route for the main bills page
@kitchen_bp.route("/bills")
def bills():
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Fetch all orders that have a status of 'Completed'
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
                'order_ids': set()  # To track all order IDs for this table
            }
        orders_to_bill[table_no]['items'].append(item)
        orders_to_bill[table_no]['total_price'] += item['quantity'] * item['Price']
        orders_to_bill[table_no]['order_ids'].add(item['order_id'])
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT Payment_methods FROM payments_type")
    payment_types = [row['Payment_methods'] for row in cursor.fetchall()]
    cursor.close()
    
    return render_template(
        "kitchen/bills.html",
        orders=orders_to_bill,
        payment_types=payment_types
    )


# Route to generate and download the PDF
# In your app.py file, inside the kitchen_bp blueprint

@kitchen_bp.route("/generate_bill_pdf/<table_no>")
def generate_bill_pdf(table_no):
    if not session.get('logged_in'):
        return redirect(url_for("admin.login"))

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM current_order WHERE status = 'Completed' AND table_no = %s", (table_no,))
    order_items = cursor.fetchall()
    cursor.close()

    if not order_items:
        flash("Order not found.", "danger")
        return redirect(url_for("kitchen.bills"))

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)

    # Bill Header
    p.drawString(50, 750, "Restaurant Bill")
    p.setFont("Helvetica", 12)
    p.drawString(50, 730, f"Table: {table_no}")
    p.drawString(50, 715, f"Date: {time.strftime('%Y-%m-%d %H:%M')}")

    y_position = 690
    total = 0

    # Bill Items
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

    # Bill Footer
    y_position -= 20
    p.line(50, y_position, 550, y_position)
    y_position -= 15
    p.setFont("Helvetica-Bold", 14)
    p.drawString(400, y_position, f"Total: ₹{total:.2f}")

    p.showPage()
    p.save()

    buffer.seek(0)
    from flask import send_file
    # ✅ Corrected line
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'bill_table_{table_no}.pdf',
        mimetype='application/pdf'
    )




# Route to finalize the payment and move data
@kitchen_bp.route("/finalize_bill", methods=["POST"])
def finalize_bill():
    
    table_no = request.form.get('table_no')
    payment_type = request.form.get('payment_type')
    
    db = get_db()
    # ✅ Change to dictionary=True for safer access
    cursor = db.cursor(dictionary=True)
    
    try:
        # Fetch the completed order items for the given table
        cursor.execute("SELECT * FROM current_order WHERE table_no = %s AND status = 'Completed'", (table_no,))
        items = cursor.fetchall()
        
        if items:
            # ✅ Calculate total amount using column names
            total_amount = sum(item['Price'] * item['quantity'] for item in items)
            
            sql_insert_all_orders = """
                INSERT INTO All_Orders (Order_id, item, type, Quantity, price, date_time, payment_type)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s)
            """
            for item in items:
                # ✅ Pass item values by name for clarity
                cursor.execute(sql_insert_all_orders, (
                    item['order_id'],
                    item['dish_name'],
                    item['type'],
                    item['quantity'],
                    item['Price'],
                    payment_type
                ))
            
            # Delete all items for this table from current_order table
            cursor.execute("DELETE FROM current_order WHERE table_no = %s AND status = 'Completed'", (table_no,))
            
            db.commit()
            flash(f"Bill for Table {table_no} has been finalized and paid via {payment_type}!", "success")
    
    except mysql.connector.Error as err:
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
        cursor.execute("ALTER TABLE current_order AUTO_INCREMENT = 1")
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
    return redirect(url_for("customer.customer_menu",table="1"))
@app.route("/admin")
def admin():
    return redirect(url_for("admin.dashboard"))

@app.route("/kitchen")
def kitchen():
    return redirect(url_for("kitchen.orders"))


# -------------------- Run App --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000,debug=True)

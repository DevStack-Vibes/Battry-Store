from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.pdfgen import canvas
import io
import os
import sqlite3
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SHOP_NAME'] = "Haideri Battery Store"
app.config['SHOP_ADDRESS'] = "NoorKot Road, Sakhargarh"
app.config['SALESMAN_NAME'] = "Musawar Apal"
app.config['PHONE_NUMBER'] = "03005016501"

db = SQLAlchemy(app)

# Initialize Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Admin decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required!', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Battery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    model = db.Column(db.String(100))
    company = db.Column(db.String(100))
    weight = db.Column(db.Float)
    purchase_price = db.Column(db.Float, nullable=False)
    selling_price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    customer_name = db.Column(db.String(200))
    customer_phone = db.Column(db.String(20))
    items = db.Column(db.Text)  # JSON string of items
    subtotal = db.Column(db.Float, nullable=False)
    discount = db.Column(db.Float, default=0)
    scrap_deduction = db.Column(db.Float, default=0)  # New column
    total = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50))
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScrapInventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(100))
    name = db.Column(db.String(200), nullable=False)
    model = db.Column(db.String(100))
    weight = db.Column(db.Float)
    price = db.Column(db.Float, nullable=False)
    reason = db.Column(db.Text)
    sold_invoice = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def init_database():
    """Initialize database with all required tables and columns"""
    with app.app_context():
        try:
            # First, create all tables (if they don't exist)
            db.create_all()
            
            # Check if scrap_deduction column exists in Sale table
            # Use SQLAlchemy's inspector instead of direct SQLite connection
            from sqlalchemy import inspect
            
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('sale')]
            
            if 'scrap_deduction' not in columns:
                print("Adding scrap_deduction column to sale table...")
                
                # Use SQLAlchemy's text() for safe SQL execution
                from sqlalchemy import text
                
                with db.engine.connect() as conn:
                    # Try different SQL approaches
                    try:
                        conn.execute(text("ALTER TABLE sale ADD COLUMN scrap_deduction FLOAT DEFAULT 0"))
                        conn.commit()
                        print("✓ scrap_deduction column added successfully")
                    except Exception as e:
                        print(f"Could not add column using standard SQL: {e}")
                        
                        # Try alternative approach
                        try:
                            # Create a temporary table with the new schema
                            conn.execute(text("""
                                CREATE TABLE sale_new (
                                    id INTEGER PRIMARY KEY,
                                    invoice_number VARCHAR(50) UNIQUE NOT NULL,
                                    customer_name VARCHAR(200),
                                    customer_phone VARCHAR(20),
                                    items TEXT,
                                    subtotal FLOAT NOT NULL,
                                    discount FLOAT DEFAULT 0,
                                    scrap_deduction FLOAT DEFAULT 0,
                                    total FLOAT NOT NULL,
                                    payment_method VARCHAR(50),
                                    created_by VARCHAR(100),
                                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                                )
                            """))
                            
                            # Copy data from old table
                            conn.execute(text("""
                                INSERT INTO sale_new 
                                SELECT id, invoice_number, customer_name, customer_phone, 
                                       items, subtotal, discount, 0, total, 
                                       payment_method, created_by, created_at 
                                FROM sale
                            """))
                            
                            # Drop old table and rename new one
                            conn.execute(text("DROP TABLE sale"))
                            conn.execute(text("ALTER TABLE sale_new RENAME TO sale"))
                            conn.commit()
                            print("✓ Table recreated with scrap_deduction column")
                        except Exception as e2:
                            print(f"Could not recreate table: {e2}")
            
            # Create admin user if not exists
            if not User.query.filter_by(username='admin').first():
                admin = User(
                    username='admin',
                    password=generate_password_hash('admin123'),
                    role='admin'
                )
                db.session.add(admin)
                db.session.commit()
                print("✓ Admin user created: username='admin', password='admin123'")
                
        except Exception as e:
            print(f"Error during database initialization: {e}")
            # Try to create everything from scratch
            try:
                db.drop_all()
                db.create_all()
                print("✓ Database recreated from scratch")
                
                # Create admin user
                admin = User(
                    username='admin',
                    password=generate_password_hash('admin123'),
                    role='admin'
                )
                db.session.add(admin)
                db.session.commit()
                print("✓ Admin user created")
            except Exception as e2:
                print(f"Fatal error: Could not initialize database: {e2}")
# Custom Jinja2 filter for JSON parsing
@app.template_filter('fromjson')
def from_json(value):
    try:
        return json.loads(value)
    except:
        return []

# Initialize database
init_database()

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password!', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Get statistics
    total_batteries = Battery.query.count()
    
    # Get today's sales
    today = datetime.now().date()
    today_sales = Sale.query.filter(
        db.func.date(Sale.created_at) == today
    ).all()
    
    total_sales_today = len(today_sales)
    today_revenue = sum(sale.total for sale in today_sales)
    
    # Get all-time totals
    all_sales = Sale.query.all()
    total_sales_all = len(all_sales)
    total_revenue_all = sum(sale.total for sale in all_sales)
    
    # Get low stock items (quantity < 5)
    low_stock = Battery.query.filter(Battery.quantity < 5).count()
    
    # Get recent sales for dashboard
    recent_sales = Sale.query.order_by(Sale.id.desc()).limit(5).all()
    
    return render_template('dashboard.html',
                         total_batteries=total_batteries,
                         total_sales_today=total_sales_today,
                         today_revenue=today_revenue,
                         total_sales_all=total_sales_all,
                         total_revenue_all=total_revenue_all,
                         low_stock=low_stock,
                         recent_sales=recent_sales)

@app.route('/add_inventory', methods=['GET', 'POST'])
@login_required
def add_inventory():
    if request.method == 'POST':
        barcode = request.form.get('barcode')
        name = request.form.get('name')
        model = request.form.get('model')
        company = request.form.get('company')
        weight = request.form.get('weight', 0)
        purchase_price = request.form.get('purchase_price')
        selling_price = request.form.get('selling_price')
        quantity = request.form.get('quantity', 0)
        
        # Check if barcode exists
        existing = Battery.query.filter_by(barcode=barcode).first()
        if existing:
            flash('Barcode already exists!', 'danger')
            return redirect(url_for('add_inventory'))
        
        # Create new battery
        battery = Battery(
            barcode=barcode,
            name=name,
            model=model,
            company=company,
            weight=float(weight) if weight else 0,
            purchase_price=float(purchase_price),
            selling_price=float(selling_price),
            quantity=int(quantity)
        )
        
        db.session.add(battery)
        db.session.commit()
        
        flash('Battery added successfully!', 'success')
        return redirect(url_for('view_inventory'))
    
    return render_template('add_inventory.html')

@app.route('/view_inventory')
@login_required
def view_inventory():
    batteries = Battery.query.all()
    return render_template('view_inventory.html', batteries=batteries)

@app.route('/edit_inventory/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_inventory(id):
    battery = Battery.query.get_or_404(id)
    
    if request.method == 'POST':
        battery.name = request.form.get('name')
        battery.model = request.form.get('model')
        battery.company = request.form.get('company')
        battery.weight = float(request.form.get('weight', 0)) if request.form.get('weight') else 0
        battery.purchase_price = float(request.form.get('purchase_price'))
        battery.selling_price = float(request.form.get('selling_price'))
        battery.quantity = int(request.form.get('quantity', 0))
        battery.updated_at = datetime.utcnow()
        
        db.session.commit()
        flash('Battery updated successfully!', 'success')
        return redirect(url_for('view_inventory'))
    
    return render_template('edit_inventory.html', battery=battery)

@app.route('/delete_inventory/<int:id>')
@login_required
@admin_required
def delete_inventory(id):
    battery = Battery.query.get_or_404(id)
    db.session.delete(battery)
    db.session.commit()
    flash('Battery deleted successfully!', 'success')
    return redirect(url_for('view_inventory'))

@app.route('/get_battery_info/<barcode>')
@login_required
def get_battery_info(barcode):
    battery = Battery.query.filter_by(barcode=barcode).first()
    if battery:
        return jsonify({
            'success': True,
            'data': {
                'name': battery.name,
                'model': battery.model,
                'company': battery.company,
                'weight': battery.weight,
                'selling_price': battery.selling_price,
                'quantity': battery.quantity
            }
        })
    return jsonify({'success': False})

@app.route('/billing', methods=['GET', 'POST'])
@login_required
def billing():
    if request.method == 'POST':
        try:
            items = json.loads(request.form.get('items', '[]'))
            customer_name = request.form.get('customer_name', 'Walk-in Customer')
            customer_phone = request.form.get('customer_phone', '')
            discount = float(request.form.get('discount', 0))
            scrap_deduction = float(request.form.get('scrap_deduction', 0))
            scrap_items = json.loads(request.form.get('scrap_items', '[]'))
            payment_method = request.form.get('payment_method', 'cash')
            
            # Calculate totals
            subtotal = sum(item['total'] for item in items)
            total = subtotal - discount - scrap_deduction
            
            # Generate invoice number
            today = datetime.now().strftime('%Y%m%d')
            last_invoice = Sale.query.filter(
                Sale.invoice_number.like(f'INV-{today}-%')
            ).order_by(Sale.id.desc()).first()
            
            if last_invoice:
                last_num = int(last_invoice.invoice_number.split('-')[-1])
                invoice_number = f'INV-{today}-{last_num + 1:04d}'
            else:
                invoice_number = f'INV-{today}-0001'
            
            # Create sale record
            sale = Sale(
                invoice_number=invoice_number,
                customer_name=customer_name,
                customer_phone=customer_phone,
                items=json.dumps(items),
                subtotal=subtotal,
                discount=discount,
                scrap_deduction=scrap_deduction,
                total=total,
                payment_method=payment_method,
                created_by=current_user.username
            )
            
            db.session.add(sale)
            
            # Update inventory quantities
            for item in items:
                battery = Battery.query.filter_by(barcode=item['barcode']).first()
                if battery and battery.quantity >= item['quantity']:
                    battery.quantity -= item['quantity']
                elif battery:
                    flash(f'Not enough stock for {battery.name}. Available: {battery.quantity}, Requested: {item["quantity"]}', 'danger')
                    return redirect(url_for('billing'))
            
            # Add scrap items to scrap inventory
            for scrap in scrap_items:
                scrap_item = ScrapInventory(
                    barcode=scrap.get('barcode', ''),
                    name=scrap['name'],
                    model=scrap.get('model', ''),
                    weight=float(scrap.get('weight', 0)) if scrap.get('weight') else 0,
                    price=float(scrap['price']),
                    reason=scrap.get('reason', ''),
                    sold_invoice=invoice_number
                )
                db.session.add(scrap_item)
            
            db.session.commit()
            
            flash(f'Bill created successfully! Invoice: {invoice_number}', 'success')
            return redirect(url_for('invoice', invoice_number=invoice_number))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating bill: {str(e)}', 'danger')
            return redirect(url_for('billing'))
    
    return render_template('billing.html')

@app.route('/invoice/<invoice_number>')
@login_required
def invoice(invoice_number):
    sale = Sale.query.filter_by(invoice_number=invoice_number).first_or_404()
    items = json.loads(sale.items)
    
    # Get scrap items for this invoice
    scrap_items = ScrapInventory.query.filter_by(sold_invoice=invoice_number).all()
    
    return render_template('invoice.html', sale=sale, items=items, scrap_items=scrap_items)

@app.route('/print_invoice/<invoice_number>/<size>')
@login_required
def print_invoice(invoice_number, size):
    sale = Sale.query.filter_by(invoice_number=invoice_number).first_or_404()
    items = json.loads(sale.items)
    scrap_items = ScrapInventory.query.filter_by(sold_invoice=invoice_number).all()
    
    # Create PDF
    if size == 'a4':
        pagesize = A4
    else:  # thermal
        pagesize = (200, 300)  # Thermal printer size
    
    buffer = io.BytesIO()
    
    if size == 'thermal':
        # Simple thermal printer format
        c = canvas.Canvas(buffer, pagesize=pagesize)
        width, height = pagesize
        
        # Shop info
        c.setFont("Helvetica", 10)
        c.drawString(10, height - 20, app.config['SHOP_NAME'])
        c.drawString(10, height - 35, app.config['SHOP_ADDRESS'])
        c.drawString(10, height - 50, f"Salesman: {app.config['SALESMAN_NAME']}")
        c.drawString(10, height - 65, f"Phone: {app.config['PHONE_NUMBER']}")
        
        c.drawString(10, height - 85, "=" * 40)
        
        # Invoice details
        c.drawString(10, height - 105, f"Invoice: {sale.invoice_number}")
        c.drawString(10, height - 120, f"Date: {sale.created_at.strftime('%Y-%m-%d %H:%M')}")
        c.drawString(10, height - 135, f"Customer: {sale.customer_name}")
        
        c.drawString(10, height - 155, "=" * 40)
        
        # Items
        y = height - 175
        for item in items:
            c.drawString(10, y, f"{item['name'][:20]}")
            c.drawString(10, y - 15, f"  Qty: {item['quantity']} @ {item['price']} = {item['total']}")
            y -= 30
        
        # Scrap items
        if scrap_items:
            c.drawString(10, y - 10, "-" * 40)
            y -= 20
            c.drawString(10, y, "Scrap Items:")
            y -= 15
            for scrap in scrap_items:
                c.drawString(10, y, f"{scrap.name[:20]}")
                c.drawString(10, y - 15, f"  Price: -{scrap.price}")
                y -= 30
        
        c.drawString(10, y - 10, "=" * 40)
        
        # Totals
        c.drawString(10, y - 30, f"Subtotal: {sale.subtotal:.2f}")
        c.drawString(10, y - 45, f"Discount: {sale.discount:.2f}")
        if sale.scrap_deduction > 0:
            c.drawString(10, y - 60, f"Scrap Deduction: {sale.scrap_deduction:.2f}")
            c.drawString(10, y - 75, f"Total: {sale.total:.2f}")
            c.drawString(10, y - 90, f"Payment: {sale.payment_method}")
        else:
            c.drawString(10, y - 60, f"Total: {sale.total:.2f}")
            c.drawString(10, y - 75, f"Payment: {sale.payment_method}")
        
        c.drawString(10, y - 110, "Thank you for your business!")
        
        c.save()
    else:
        # A4 format with ReportLab
        doc = SimpleDocTemplate(buffer, pagesize=pagesize)
        elements = []
        styles = getSampleStyleSheet()
        
        # Shop info
        shop_info = f"""
        <para alignment="center">
        <font size="16"><b>{app.config['SHOP_NAME']}</b></font><br/>
        <font size="12">{app.config['SHOP_ADDRESS']}</font><br/>
        <font size="11">Salesman: {app.config['SALESMAN_NAME']} | Phone: {app.config['PHONE_NUMBER']}</font>
        </para>
        """
        elements.append(Paragraph(shop_info, styles["Normal"]))
        elements.append(Spacer(1, 20))
        
        # Invoice details
        invoice_info = f"""
        <para>
        <b>Invoice Number:</b> {sale.invoice_number}<br/>
        <b>Date:</b> {sale.created_at.strftime('%Y-%m-%d %H:%M')}<br/>
        <b>Customer:</b> {sale.customer_name}<br/>
        <b>Phone:</b> {sale.customer_phone}
        </para>
        """
        elements.append(Paragraph(invoice_info, styles["Normal"]))
        elements.append(Spacer(1, 20))
        
        # Items table
        table_data = [['Item', 'Qty', 'Price', 'Total']]
        for item in items:
            table_data.append([
                f"{item['name']}\n{item.get('model', '')}",
                item['quantity'],
                f"Rs. {item['price']:.2f}",
                f"Rs. {item['total']:.2f}"
            ])
        
        # Add scrap items if any
        if scrap_items:
            table_data.append(['', '', '', ''])
            table_data.append(['<b>Scrap Items:</b>', '', '', ''])
            for scrap in scrap_items:
                table_data.append([
                    f"{scrap.name}\n{scrap.model or ''}",
                    '1',
                    f"Rs. -{scrap.price:.2f}",
                    f"Rs. -{scrap.price:.2f}"
                ])
        
        # Add totals row
        table_data.append(['', '', '', ''])
        table_data.append(['', '', 'Subtotal:', f"Rs. {sale.subtotal:.2f}"])
        table_data.append(['', '', 'Discount:', f"Rs. -{sale.discount:.2f}"])
        if sale.scrap_deduction > 0:
            table_data.append(['', '', 'Scrap Deduction:', f"Rs. -{sale.scrap_deduction:.2f}"])
        table_data.append(['', '', 'Total:', f"Rs. {sale.total:.2f}"])
        
        table = Table(table_data, colWidths=[200, 50, 80, 80])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -len(scrap_items)-7 if scrap_items else -5), colors.beige),
            ('GRID', (0, 0), (-1, -len(scrap_items)-7 if scrap_items else -5), 1, colors.black),
            ('SPAN', (0, -5), (1, -5)),
            ('BACKGROUND', (-2, -5), (-1, -1), colors.lightgrey),
            ('FONTNAME', (-2, -5), (-1, -1), 'Helvetica-Bold'),
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 30))
        
        # Payment method
        payment_info = f"<para><b>Payment Method:</b> {sale.payment_method.upper()}</para>"
        elements.append(Paragraph(payment_info, styles["Normal"]))
        
        # Thank you message
        thank_you = "<para alignment='center'><font size='12'><b>Thank you for your business!</b></font></para>"
        elements.append(Spacer(1, 20))
        elements.append(Paragraph(thank_you, styles["Normal"]))
        
        doc.build(elements)
    
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f'invoice_{invoice_number}.pdf', mimetype='application/pdf')

@app.route('/daily_report')
@login_required
def daily_report():
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        report_date = datetime.now().date()
    
    # Get sales for the date
    sales = Sale.query.filter(
        db.func.date(Sale.created_at) == report_date
    ).all()
    
    # Calculate totals
    total_sales = len(sales)
    total_revenue = sum(sale.total for sale in sales)
    total_discount = sum(sale.discount for sale in sales)
    total_scrap_deduction = sum(sale.scrap_deduction for sale in sales)
    
    return render_template('daily_report.html',
                         sales=sales,
                         report_date=report_date,
                         total_sales=total_sales,
                         total_revenue=total_revenue,
                         total_discount=total_discount,
                         total_scrap_deduction=total_scrap_deduction)

@app.route('/profit_loss')
@login_required
def profit_loss():
    start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    
    # Get sales in date range
    sales = Sale.query.filter(
        Sale.created_at >= start_date,
        Sale.created_at <= end_date + ' 23:59:59'
    ).all()
    
    # Get all batteries for cost calculation
    batteries = Battery.query.all()
    battery_dict = {battery.barcode: battery for battery in batteries}
    
    # Calculate profit/loss
    total_revenue = sum(sale.total for sale in sales)
    total_cost = 0
    
    for sale in sales:
        items = json.loads(sale.items)
        for item in items:
            battery = battery_dict.get(item['barcode'])
            if battery:
                total_cost += battery.purchase_price * item['quantity']
    
    total_profit = total_revenue - total_cost
    profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    return render_template('profit_loss.html',
                         sales=sales,
                         start_date=start_date,
                         end_date=end_date,
                         total_revenue=total_revenue,
                         total_cost=total_cost,
                         total_profit=total_profit,
                         profit_margin=profit_margin,
                         batteries=batteries)

@app.route('/scrap_inventory', methods=['GET', 'POST'])
@login_required
def scrap_inventory():
    if request.method == 'POST':
        # Add scrap item manually
        barcode = request.form.get('barcode', '')
        name = request.form.get('name')
        model = request.form.get('model', '')
        weight = request.form.get('weight', 0)
        price = request.form.get('price')
        reason = request.form.get('reason', 'Manual Entry')
        
        scrap_item = ScrapInventory(
            barcode=barcode,
            name=name,
            model=model,
            weight=float(weight) if weight else 0,
            price=float(price),
            reason=reason,
            sold_invoice=None  # Not from a sale
        )
        
        db.session.add(scrap_item)
        db.session.commit()
        
        flash('Scrap item added successfully!', 'success')
        return redirect(url_for('scrap_inventory'))
    
    scraps = ScrapInventory.query.all()
    return render_template('scrap_inventory.html', scraps=scraps)

@app.route('/search_battery')
@login_required
def search_battery():
    query = request.args.get('q', '')
    batteries = Battery.query.filter(
        (Battery.barcode.contains(query)) |
        (Battery.name.contains(query)) |
        (Battery.model.contains(query))
    ).limit(10).all()
    
    results = []
    for battery in batteries:
        results.append({
            'barcode': battery.barcode,
            'name': battery.name,
            'model': battery.model,
            'company': battery.company,
            'selling_price': battery.selling_price,
            'quantity': battery.quantity
        })
    
    return jsonify(results)

@app.route('/delete_scrap/<int:id>')
@login_required
@admin_required
def delete_scrap(id):
    scrap = ScrapInventory.query.get_or_404(id)
    db.session.delete(scrap)
    db.session.commit()
    flash('Scrap item deleted successfully!', 'success')
    return redirect(url_for('scrap_inventory'))

def create_templates():
    """Create all template files"""
    templates = {
        'base.html': """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Haideri Battery Store{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.8.1/font/bootstrap-icons.css">
    <style>
        body { background-color: #f8f9fa; }
        .sidebar { min-height: 100vh; background: #2c3e50; }
        .sidebar .nav-link { color: #ecf0f1; padding: 15px 20px; }
        .sidebar .nav-link:hover { background-color: #34495e; }
        .main-content { padding: 20px; }
        .card { border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .stat-card { text-align: center; padding: 20px; }
        .stat-card i { font-size: 2.5rem; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 px-0 sidebar">
                <div class="text-center py-4">
                    <h4 class="text-white">Haideri Battery</h4>
                    <small class="text-muted">Management System</small>
                </div>
                <nav class="nav flex-column">
                    <a class="nav-link {% if request.endpoint == 'dashboard' %}active{% endif %}" href="{{ url_for('dashboard') }}"><i class="bi bi-speedometer2"></i> Dashboard</a>
                    <a class="nav-link {% if request.endpoint == 'add_inventory' %}active{% endif %}" href="{{ url_for('add_inventory') }}"><i class="bi bi-plus-circle"></i> Add Inventory</a>
                    <a class="nav-link {% if request.endpoint == 'view_inventory' %}active{% endif %}" href="{{ url_for('view_inventory') }}"><i class="bi bi-view-list"></i> View Inventory</a>
                    <a class="nav-link {% if request.endpoint == 'billing' %}active{% endif %}" href="{{ url_for('billing') }}"><i class="bi bi-receipt"></i> Billing</a>
                    <a class="nav-link {% if request.endpoint == 'daily_report' %}active{% endif %}" href="{{ url_for('daily_report') }}"><i class="bi bi-file-text"></i> Daily Report</a>
                    <a class="nav-link {% if request.endpoint == 'profit_loss' %}active{% endif %}" href="{{ url_for('profit_loss') }}"><i class="bi bi-graph-up"></i> Profit/Loss</a>
                    <a class="nav-link {% if request.endpoint == 'scrap_inventory' %}active{% endif %}" href="{{ url_for('scrap_inventory') }}"><i class="bi bi-trash"></i> Scrap Inventory</a>
                    <div class="mt-4"></div>
                    <a class="nav-link" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right"></i> Logout</a>
                </nav>
            </div>
            <div class="col-md-10 main-content">
                {% with messages = get_flashed_messages(with_categories=true) %}
                    {% if messages %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                                {{ message }}
                                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                            </div>
                        {% endfor %}
                    {% endif %}
                {% endwith %}
                {% block content %}{% endblock %}
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    {% block extra_js %}{% endblock %}
</body>
</html>""",
        
        'login.html': """{% extends "base.html" %}
{% block title %}Login{% endblock %}
{% block content %}
<div class="container">
    <div class="row justify-content-center mt-5">
        <div class="col-md-6">
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="bi bi-lock"></i> Haideri Battery Store - Login</h4>
                </div>
                <div class="card-body">
                    <form method="POST" action="{{ url_for('login') }}">
                        <div class="mb-3">
                            <label for="username" class="form-label">Username</label>
                            <input type="text" class="form-control" id="username" name="username" required>
                        </div>
                        <div class="mb-3">
                            <label for="password" class="form-label">Password</label>
                            <input type="password" class="form-control" id="password" name="password" required>
                        </div>
                        <button type="submit" class="btn btn-primary w-100">
                            <i class="bi bi-box-arrow-in-right"></i> Login
                        </button>
                    </form>
                    <div class="mt-3 text-center">
                        <small>Default credentials: admin / admin123</small>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}""",
        
        'dashboard.html': """{% extends "base.html" %}
{% block title %}Dashboard{% endblock %}
{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2"><i class="bi bi-speedometer2"></i> Dashboard</h1>
    <div class="btn-toolbar mb-2 mb-md-0">
        <span class="badge bg-primary">{{ current_user.username }} ({{ current_user.role }})</span>
    </div>
</div>

<!-- All-time Statistics -->
<div class="row mb-4">
    <div class="col-md-3">
        <div class="card stat-card bg-info text-white">
            <div class="card-body text-center">
                <i class="bi bi-battery-charging"></i>
                <h5>Total Batteries</h5>
                <h2>{{ total_batteries }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card stat-card bg-primary text-white">
            <div class="card-body text-center">
                <i class="bi bi-cart-check"></i>
                <h5>Total Sales (All-time)</h5>
                <h2>{{ total_sales_all }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card stat-card bg-success text-white">
            <div class="card-body text-center">
                <i class="bi bi-currency-rupee"></i>
                <h5>Total Revenue (All-time)</h5>
                <h2>Rs. {{ "%.2f"|format(total_revenue_all) }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card stat-card bg-danger text-white">
            <div class="card-body text-center">
                <i class="bi bi-exclamation-triangle"></i>
                <h5>Low Stock Items</h5>
                <h2>{{ low_stock }}</h2>
            </div>
        </div>
    </div>
</div>

<!-- Today's Statistics -->
<div class="row mb-4">
    <div class="col-md-6">
        <div class="card stat-card bg-warning text-dark">
            <div class="card-body text-center">
                <i class="bi bi-cart"></i>
                <h5>Today's Sales</h5>
                <h2>{{ total_sales_today }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-6">
        <div class="card stat-card bg-dark text-white">
            <div class="card-body text-center">
                <i class="bi bi-cash"></i>
                <h5>Today's Revenue</h5>
                <h2>Rs. {{ "%.2f"|format(today_revenue) }}</h2>
            </div>
        </div>
    </div>
</div>

<!-- Quick Actions -->
<div class="row mt-4">
    <div class="col-md-12">
        <div class="card">
            <div class="card-header"><h5><i class="bi bi-lightning"></i> Quick Actions</h5></div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-3">
                        <a href="{{ url_for('add_inventory') }}" class="btn btn-outline-primary w-100 mb-2">
                            <i class="bi bi-plus-circle"></i> Add New Battery
                        </a>
                    </div>
                    <div class="col-md-3">
                        <a href="{{ url_for('billing') }}" class="btn btn-outline-success w-100 mb-2">
                            <i class="bi bi-receipt"></i> Create New Bill
                        </a>
                    </div>
                    <div class="col-md-3">
                        <a href="{{ url_for('daily_report') }}" class="btn btn-outline-info w-100 mb-2">
                            <i class="bi bi-file-text"></i> Daily Report
                        </a>
                    </div>
                    <div class="col-md-3">
                        <a href="{{ url_for('scrap_inventory') }}" class="btn btn-outline-warning w-100 mb-2">
                            <i class="bi bi-trash"></i> Scrap Inventory
                        </a>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Recent Sales -->
<div class="row mt-4">
    <div class="col-md-12">
        <div class="card">
            <div class="card-header"><h5><i class="bi bi-clock-history"></i> Recent Sales</h5></div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Invoice</th>
                                <th>Customer</th>
                                <th>Date</th>
                                <th>Amount</th>
                                <th>Payment</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for sale in recent_sales %}
                            <tr>
                                <td>{{ sale.invoice_number }}</td>
                                <td>{{ sale.customer_name }}</td>
                                <td>{{ sale.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
                                <td>Rs. {{ "%.2f"|format(sale.total) }}</td>
                                <td><span class="badge bg-info">{{ sale.payment_method }}</span></td>
                                <td>
                                    <a href="{{ url_for('invoice', invoice_number=sale.invoice_number) }}" class="btn btn-sm btn-outline-primary">View</a>
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="6" class="text-center">No recent sales</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}""",
        
        'add_inventory.html': """{% extends "base.html" %}
{% block title %}Add Inventory{% endblock %}
{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2"><i class="bi bi-plus-circle"></i> Add New Battery</h1>
</div>

<div class="row">
    <div class="col-md-8">
        <div class="card">
            <div class="card-header"><h5>Battery Information</h5></div>
            <div class="card-body">
                <form method="POST" action="{{ url_for('add_inventory') }}">
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label for="barcode" class="form-label">Barcode *</label>
                            <input type="text" class="form-control" id="barcode" name="barcode" required>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label for="name" class="form-label">Battery Name *</label>
                            <input type="text" class="form-control" id="name" name="name" required>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label for="model" class="form-label">Model</label>
                            <input type="text" class="form-control" id="model" name="model">
                        </div>
                        <div class="col-md-6 mb-3">
                            <label for="company" class="form-label">Company</label>
                            <input type="text" class="form-control" id="company" name="company">
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-4 mb-3">
                            <label for="weight" class="form-label">Weight (kg)</label>
                            <input type="number" step="0.01" class="form-control" id="weight" name="weight">
                        </div>
                        <div class="col-md-4 mb-3">
                            <label for="purchase_price" class="form-label">Purchase Price *</label>
                            <input type="number" step="0.01" class="form-control" id="purchase_price" name="purchase_price" required>
                        </div>
                        <div class="col-md-4 mb-3">
                            <label for="selling_price" class="form-label">Selling Price *</label>
                            <input type="number" step="0.01" class="form-control" id="selling_price" name="selling_price" required>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label for="quantity" class="form-label">Quantity</label>
                            <input type="number" class="form-control" id="quantity" name="quantity" value="0">
                        </div>
                    </div>
                    <div class="mt-4">
                        <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> Save Battery</button>
                        <a href="{{ url_for('view_inventory') }}" class="btn btn-secondary"><i class="bi bi-x-circle"></i> Cancel</a>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}""",
        
        'view_inventory.html': """{% extends "base.html" %}
{% block title %}View Inventory{% endblock %}
{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2"><i class="bi bi-view-list"></i> Battery Inventory</h1>
</div>

<div class="card">
    <div class="card-header">
        <h5>All Batteries</h5>
    </div>
    <div class="card-body">
        <div class="table-responsive">
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th>Barcode</th>
                        <th>Name</th>
                        <th>Model</th>
                        <th>Company</th>
                        <th>Purchase</th>
                        <th>Selling</th>
                        <th>Qty</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for battery in batteries %}
                    <tr>
                        <td>{{ battery.barcode }}</td>
                        <td>{{ battery.name }}</td>
                        <td>{{ battery.model or '-' }}</td>
                        <td>{{ battery.company or '-' }}</td>
                        <td>Rs. {{ "%.2f"|format(battery.purchase_price) }}</td>
                        <td>Rs. {{ "%.2f"|format(battery.selling_price) }}</td>
                        <td>
                            <span class="badge {% if battery.quantity == 0 %}bg-danger{% elif battery.quantity < 5 %}bg-warning{% else %}bg-success{% endif %}">
                                {{ battery.quantity }}
                            </span>
                        </td>
                        <td>
                            <a href="{{ url_for('edit_inventory', id=battery.id) }}" class="btn btn-sm btn-outline-primary">
                                <i class="bi bi-pencil"></i>
                            </a>
                            <a href="{{ url_for('delete_inventory', id=battery.id) }}" class="btn btn-sm btn-outline-danger">
                                <i class="bi bi-trash"></i>
                            </a>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="8" class="text-center">No batteries found. <a href="{{ url_for('add_inventory') }}">Add one</a></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}""",
        
        'edit_inventory.html': """{% extends "base.html" %}
{% block title %}Edit Inventory{% endblock %}
{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2"><i class="bi bi-pencil"></i> Edit Battery</h1>
</div>

<div class="row">
    <div class="col-md-8">
        <div class="card">
            <div class="card-header"><h5>Edit Battery Information</h5></div>
            <div class="card-body">
                <form method="POST" action="{{ url_for('edit_inventory', id=battery.id) }}">
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label for="barcode" class="form-label">Barcode *</label>
                            <input type="text" class="form-control" id="barcode" name="barcode" value="{{ battery.barcode }}" readonly>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label for="name" class="form-label">Battery Name *</label>
                            <input type="text" class="form-control" id="name" name="name" value="{{ battery.name }}" required>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label for="model" class="form-label">Model</label>
                            <input type="text" class="form-control" id="model" name="model" value="{{ battery.model or '' }}">
                        </div>
                        <div class="col-md-6 mb-3">
                            <label for="company" class="form-label">Company</label>
                            <input type="text" class="form-control" id="company" name="company" value="{{ battery.company or '' }}">
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-4 mb-3">
                            <label for="weight" class="form-label">Weight (kg)</label>
                            <input type="number" step="0.01" class="form-control" id="weight" name="weight" value="{{ battery.weight or 0 }}">
                        </div>
                        <div class="col-md-4 mb-3">
                            <label for="purchase_price" class="form-label">Purchase Price *</label>
                            <input type="number" step="0.01" class="form-control" id="purchase_price" name="purchase_price" value="{{ battery.purchase_price }}" required>
                        </div>
                        <div class="col-md-4 mb-3">
                            <label for="selling_price" class="form-label">Selling Price *</label>
                            <input type="number" step="0.01" class="form-control" id="selling_price" name="selling_price" value="{{ battery.selling_price }}" required>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label for="quantity" class="form-label">Quantity</label>
                            <input type="number" class="form-control" id="quantity" name="quantity" value="{{ battery.quantity }}">
                        </div>
                    </div>
                    <div class="mt-4">
                        <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> Update Battery</button>
                        <a href="{{ url_for('view_inventory') }}" class="btn btn-secondary"><i class="bi bi-x-circle"></i> Cancel</a>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}""",
        
        'billing.html': """{% extends "base.html" %}
{% block title %}Billing{% endblock %}
{% block extra_js %}
<script>
let cartItems = [];
let scrapItems = [];

$(document).ready(function() {
    $('#barcode_input').focus();
    
    $('#barcode_input').on('keypress', function(e) {
        if(e.which === 13) {
            e.preventDefault();
            searchBarcode($(this).val());
            $(this).val('');
        }
    });
    
    $('#searchBtn').on('click', function() {
        searchBarcode($('#barcode_input').val());
        $('#barcode_input').val('').focus();
    });
    
    $('#addScrapBtn').on('click', function() {
        $('#scrapSection').show();
    });
    
    $('#cancelScrapBtn').on('click', function() {
        $('#scrapSection').hide();
        clearScrapForm();
    });
});

function searchBarcode(query) {
    if(!query) return;
    
    $.get('/search_battery?q=' + query, function(batteries) {
        if(batteries.length > 0) {
            const exactMatch = batteries.find(b => b.barcode === query);
            if(exactMatch) {
                addToCart(exactMatch.barcode);
            } else {
                $('#searchResults').empty();
                batteries.forEach(function(battery) {
                    $('#searchResults').append(`
                        <div class="list-group-item list-group-item-action" onclick="addToCart('${battery.barcode}')">
                            <div class="d-flex w-100 justify-content-between">
                                <h6 class="mb-1">${battery.name}</h6>
                                <small>Rs. ${battery.selling_price}</small>
                            </div>
                            <p class="mb-1">${battery.model || ''} | ${battery.company || ''}</p>
                            <small>Barcode: ${battery.barcode} | Stock: ${battery.quantity}</small>
                        </div>
                    `);
                });
            }
        } else {
            $('#searchResults').html('<div class="text-muted p-2">No batteries found</div>');
        }
    });
}

function addToCart(barcode) {
    $.get('/get_battery_info/' + barcode, function(response) {
        if(response.success) {
            const battery = response.data;
            
            if(battery.quantity <= 0) {
                alert('This item is out of stock!');
                return;
            }
            
            const existingItem = cartItems.find(item => item.barcode === barcode);
            
            if(existingItem) {
                if(existingItem.quantity >= battery.quantity) {
                    alert('Cannot add more than available stock!');
                    return;
                }
                existingItem.quantity += 1;
                existingItem.total = existingItem.quantity * existingItem.price;
            } else {
                cartItems.push({
                    barcode: barcode,
                    name: battery.name,
                    model: battery.model,
                    price: battery.selling_price,
                    quantity: 1,
                    total: battery.selling_price
                });
            }
            
            updateCart();
            $('#searchResults').empty();
            $('#barcode_input').focus();
        } else {
            alert('Battery not found in inventory!');
        }
    });
}

function updateCart() {
    let subtotal = 0;
    let html = '';
    
    cartItems.forEach((item, index) => {
        subtotal += item.total;
        html += `
            <tr>
                <td>${item.barcode}</td>
                <td>${item.name}</td>
                <td>${item.model || '-'}</td>
                <td>
                    <input type="number" class="form-control form-control-sm" 
                           value="${item.quantity}" min="1" 
                           onchange="updateQuantity(${index}, this.value)" style="width: 70px;">
                </td>
                <td>Rs. ${item.price.toFixed(2)}</td>
                <td>Rs. ${item.total.toFixed(2)}</td>
                <td>
                    <button class="btn btn-sm btn-danger" onclick="removeItem(${index})">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `;
    });
    
    $('#cartItems').html(html);
    $('#subtotal').text(subtotal.toFixed(2));
    calculateTotal();
}

function updateQuantity(index, quantity) {
    quantity = parseInt(quantity);
    if(quantity > 0) {
        const barcode = cartItems[index].barcode;
        $.get('/get_battery_info/' + barcode, function(response) {
            if(response.success && quantity > response.data.quantity) {
                alert('Cannot add more than available stock! Available: ' + response.data.quantity);
                return;
            }
            cartItems[index].quantity = quantity;
            cartItems[index].total = quantity * cartItems[index].price;
            updateCart();
        });
    }
}

function removeItem(index) {
    cartItems.splice(index, 1);
    updateCart();
}

function addScrapItem() {
    const scrapName = $('#scrap_name').val();
    const scrapPrice = parseFloat($('#scrap_price').val()) || 0;
    
    if(scrapName && scrapPrice > 0) {
        scrapItems.push({
            name: scrapName,
            model: $('#scrap_model').val(),
            barcode: $('#scrap_barcode').val(),
            weight: $('#scrap_weight').val(),
            price: scrapPrice,
            reason: $('#scrap_reason').val()
        });
        
        updateScrapList();
        calculateTotal();
        clearScrapForm();
    } else {
        alert('Please enter scrap item name and price!');
    }
}

function updateScrapList() {
    let html = '';
    let totalScrap = 0;
    
    scrapItems.forEach((item, index) => {
        totalScrap += item.price;
        html += `
            <div class="d-flex justify-content-between align-items-center mb-2 border-bottom pb-2">
                <div>
                    <strong>${item.name}</strong><br>
                    <small>Model: ${item.model || '-'} | Barcode: ${item.barcode || '-'} | Reason: ${item.reason || '-'}</small>
                </div>
                <div>
                    <span class="text-danger">-Rs. ${item.price.toFixed(2)}</span>
                    <button class="btn btn-sm btn-outline-danger ms-2" onclick="removeScrapItem(${index})">
                        <i class="bi bi-x"></i>
                    </button>
                </div>
            </div>
        `;
    });
    
    $('#scrapItemsList').html(html);
    $('#scrap_total').text(totalScrap.toFixed(2));
    $('#scrap_deduction').val(totalScrap.toFixed(2));
}

function removeScrapItem(index) {
    scrapItems.splice(index, 1);
    updateScrapList();
    calculateTotal();
}

function clearScrapForm() {
    $('#scrap_name').val('');
    $('#scrap_model').val('');
    $('#scrap_barcode').val('');
    $('#scrap_weight').val('');
    $('#scrap_price').val('');
    $('#scrap_reason').val('Defective');
}

function calculateTotal() {
    let subtotal = parseFloat($('#subtotal').text()) || 0;
    let discount = parseFloat($('#discount').val()) || 0;
    let scrapDeduction = scrapItems.reduce((sum, item) => sum + item.price, 0);
    let total = subtotal - discount - scrapDeduction;
    
    if(total < 0) total = 0;
    
    $('#total_amount').text(total.toFixed(2));
    $('#scrap_deduction_display').text(scrapDeduction.toFixed(2));
}

function processBill() {
    if(cartItems.length === 0) {
        alert('Please add at least one item to the cart!');
        return;
    }
    
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '{{ url_for("billing") }}';
    
    const itemsInput = document.createElement('input');
    itemsInput.type = 'hidden';
    itemsInput.name = 'items';
    itemsInput.value = JSON.stringify(cartItems);
    form.appendChild(itemsInput);
    
    const scrapInput = document.createElement('input');
    scrapInput.type = 'hidden';
    scrapInput.name = 'scrap_items';
    scrapInput.value = JSON.stringify(scrapItems);
    form.appendChild(scrapInput);
    
    const customerName = document.createElement('input');
    customerName.type = 'hidden';
    customerName.name = 'customer_name';
    customerName.value = $('#customer_name').val();
    form.appendChild(customerName);
    
    const customerPhone = document.createElement('input');
    customerPhone.type = 'hidden';
    customerPhone.name = 'customer_phone';
    customerPhone.value = $('#customer_phone').val();
    form.appendChild(customerPhone);
    
    const discount = document.createElement('input');
    discount.type = 'hidden';
    discount.name = 'discount';
    discount.value = $('#discount').val();
    form.appendChild(discount);
    
    const scrapDeduction = document.createElement('input');
    scrapDeduction.type = 'hidden';
    scrapDeduction.name = 'scrap_deduction';
    scrapDeduction.value = scrapItems.reduce((sum, item) => sum + item.price, 0);
    form.appendChild(scrapDeduction);
    
    const paymentMethod = document.createElement('input');
    paymentMethod.type = 'hidden';
    paymentMethod.name = 'payment_method';
    paymentMethod.value = $('#payment_method').val();
    form.appendChild(paymentMethod);
    
    document.body.appendChild(form);
    form.submit();
}

$(document).ready(function() {
    $('#discount').on('input', calculateTotal);
    $('#scrapSection').hide();
});
</script>
{% endblock %}

{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2"><i class="bi bi-receipt"></i> Billing System</h1>
</div>

<div class="row">
    <div class="col-md-8">
        <div class="card mb-3">
            <div class="card-header"><h5><i class="bi bi-upc-scan"></i> Add Items</h5></div>
            <div class="card-body">
                <div class="row mb-3">
                    <div class="col-md-8">
                        <div class="input-group">
                            <input type="text" class="form-control" id="barcode_input" placeholder="Scan barcode or enter manually">
                            <button class="btn btn-primary" type="button" id="searchBtn"><i class="bi bi-search"></i> Search</button>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <button class="btn btn-warning w-100" type="button" id="addScrapBtn">
                            <i class="bi bi-trash"></i> Add Scrap Item
                        </button>
                    </div>
                </div>
                
                <div id="searchResults" class="border rounded p-2 mb-3" style="max-height: 200px; overflow-y: auto;"></div>
                
                <div class="table-responsive">
                    <table class="table table-bordered">
                        <thead class="table-dark">
                            <tr>
                                <th>Barcode</th>
                                <th>Name</th>
                                <th>Model</th>
                                <th>Qty</th>
                                <th>Price</th>
                                <th>Total</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody id="cartItems"></tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <!-- Scrap Items Section -->
        <div class="card mb-3" id="scrapSection" style="display: none;">
            <div class="card-header bg-warning text-dark">
                <h5><i class="bi bi-trash"></i> Add Scrap Item</h5>
            </div>
            <div class="card-body">
                <div class="row mb-3">
                    <div class="col-md-3">
                        <input type="text" class="form-control" id="scrap_barcode" placeholder="Barcode (Optional)">
                    </div>
                    <div class="col-md-3">
                        <input type="text" class="form-control" id="scrap_name" placeholder="Item Name *" required>
                    </div>
                    <div class="col-md-2">
                        <input type="text" class="form-control" id="scrap_model" placeholder="Model">
                    </div>
                    <div class="col-md-2">
                        <input type="text" class="form-control" id="scrap_weight" placeholder="Weight">
                    </div>
                    <div class="col-md-2">
                        <input type="number" class="form-control" id="scrap_price" placeholder="Price *" step="0.01" required>
                    </div>
                </div>
                <div class="row mb-3">
                    <div class="col-md-10">
                        <select class="form-control" id="scrap_reason">
                            <option value="Defective">Defective</option>
                            <option value="Damaged">Damaged</option>
                            <option value="Expired">Expired</option>
                            <option value="Returned">Customer Return</option>
                            <option value="Other">Other</option>
                        </select>
                    </div>
                    <div class="col-md-2">
                        <button class="btn btn-success w-100" onclick="addScrapItem()">
                            <i class="bi bi-plus"></i> Add
                        </button>
                    </div>
                </div>
                <div class="mb-3">
                    <div class="border rounded p-2" style="max-height: 150px; overflow-y: auto;" id="scrapItemsList">
                        <!-- Scrap items will appear here -->
                    </div>
                </div>
                <div class="text-end">
                    <button class="btn btn-secondary" id="cancelScrapBtn">Cancel</button>
                </div>
            </div>
        </div>
    </div>
    
    <div class="col-md-4">
        <div class="card">
            <div class="card-header bg-success text-white"><h5><i class="bi bi-calculator"></i> Billing Summary</h5></div>
            <div class="card-body">
                <div class="mb-3">
                    <label class="form-label">Customer Name</label>
                    <input type="text" class="form-control" id="customer_name" value="Walk-in Customer">
                </div>
                <div class="mb-3">
                    <label class="form-label">Phone Number</label>
                    <input type="text" class="form-control" id="customer_phone">
                </div>
                
                <hr>
                
                <div class="mb-3">
                    <div class="d-flex justify-content-between">
                        <span>Subtotal:</span>
                        <strong>Rs. <span id="subtotal">0.00</span></strong>
                    </div>
                </div>
                
                <div class="mb-3">
                    <label class="form-label">Discount (Rs.)</label>
                    <input type="number" class="form-control" id="discount" value="0" step="0.01">
                </div>
                
                <div class="mb-3" id="scrapDeductionSection">
                    <div class="d-flex justify-content-between">
                        <span>Scrap Deduction:</span>
                        <span class="text-danger">Rs. <span id="scrap_deduction_display">0.00</span></span>
                    </div>
                </div>
                
                <hr>
                
                <div class="mb-3">
                    <div class="d-flex justify-content-between">
                        <h5>Total Amount:</h5>
                        <h3 class="text-success">Rs. <span id="total_amount">0.00</span></h3>
                    </div>
                </div>
                
                <div class="mb-3">
                    <label class="form-label">Payment Method</label>
                    <select class="form-select" id="payment_method">
                        <option value="cash">Cash</option>
                        <option value="card">Card</option>
                        <option value="bank_transfer">Bank Transfer</option>
                    </select>
                </div>
                
                <button class="btn btn-success btn-lg w-100 mb-3" onclick="processBill()">
                    <i class="bi bi-check-circle"></i> Process Bill
                </button>
                
                <div class="text-center">
                    <small class="text-muted">Scrap items will be deducted from total and added to scrap inventory</small>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}""",
        
        'invoice.html': """{% extends "base.html" %}
{% block title %}Invoice{% endblock %}
{% block content %}
<div class="container">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1><i class="bi bi-receipt"></i> Invoice</h1>
        <div>
            <a href="{{ url_for('print_invoice', invoice_number=sale.invoice_number, size='a4') }}" class="btn btn-primary">
                <i class="bi bi-printer"></i> Print A4
            </a>
            <a href="{{ url_for('print_invoice', invoice_number=sale.invoice_number, size='thermal') }}" class="btn btn-secondary">
                <i class="bi bi-printer"></i> Print Thermal
            </a>
            <a href="{{ url_for('dashboard') }}" class="btn btn-outline-secondary">
                <i class="bi bi-house"></i> Dashboard
            </a>
        </div>
    </div>

    <div class="card mb-4">
        <div class="card-header bg-primary text-white"><h4 class="mb-0">Invoice Preview</h4></div>
        <div class="card-body">
            <div class="text-center mb-4">
                <h2>Haideri Battery Store</h2>
                <p class="mb-1">NoorKot Road, Sakhargarh</p>
                <p class="mb-1">Salesman: Musawar Apal | Phone: 03005016501</p>
                <hr>
            </div>
            
            <div class="row mb-4">
                <div class="col-md-6">
                    <p><strong>Invoice Number:</strong> {{ sale.invoice_number }}</p>
                    <p><strong>Date:</strong> {{ sale.created_at.strftime('%Y-%m-%d %H:%M:%S') }}</p>
                </div>
                <div class="col-md-6">
                    <p><strong>Customer Name:</strong> {{ sale.customer_name }}</p>
                    <p><strong>Phone:</strong> {{ sale.customer_phone or 'N/A' }}</p>
                </div>
            </div>
            
            <div class="table-responsive mb-4">
                <table class="table table-bordered">
                    <thead class="table-dark">
                        <tr>
                            <th>#</th>
                            <th>Item Description</th>
                            <th>Qty</th>
                            <th>Unit Price</th>
                            <th>Total</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for item in items %}
                        <tr>
                            <td>{{ loop.index }}</td>
                            <td><strong>{{ item.name }}</strong><br><small>Barcode: {{ item.barcode }}</small></td>
                            <td>{{ item.quantity }}</td>
                            <td>Rs. {{ "%.2f"|format(item.price) }}</td>
                            <td>Rs. {{ "%.2f"|format(item.total) }}</td>
                        </tr>
                        {% endfor %}
                        
                        {% if scrap_items %}
                        <tr class="table-warning">
                            <td colspan="5"><strong>Scrap Items (Deducted from bill):</strong></td>
                        </tr>
                        {% for scrap in scrap_items %}
                        <tr class="table-warning">
                            <td>{{ loop.index + items|length }}</td>
                            <td><strong>{{ scrap.name }}</strong><br><small>Reason: {{ scrap.reason or 'N/A' }}</small></td>
                            <td>1</td>
                            <td class="text-danger">-Rs. {{ "%.2f"|format(scrap.price) }}</td>
                            <td class="text-danger">-Rs. {{ "%.2f"|format(scrap.price) }}</td>
                        </tr>
                        {% endfor %}
                        {% endif %}
                    </tbody>
                </table>
            </div>
            
            <div class="row justify-content-end">
                <div class="col-md-6">
                    <table class="table table-bordered">
                        <tr>
                            <td><strong>Subtotal:</strong></td>
                            <td class="text-end">Rs. {{ "%.2f"|format(sale.subtotal) }}</td>
                        </tr>
                        <tr>
                            <td><strong>Discount:</strong></td>
                            <td class="text-end text-danger">- Rs. {{ "%.2f"|format(sale.discount) }}</td>
                        </tr>
                        {% if sale.scrap_deduction > 0 %}
                        <tr>
                            <td><strong>Scrap Deduction:</strong></td>
                            <td class="text-end text-danger">- Rs. {{ "%.2f"|format(sale.scrap_deduction) }}</td>
                        </tr>
                        {% endif %}
                        <tr class="table-success">
                            <td><strong>Grand Total:</strong></td>
                            <td class="text-end"><h4 class="mb-0">Rs. {{ "%.2f"|format(sale.total) }}</h4></td>
                        </tr>
                    </table>
                </div>
            </div>
            
            <div class="mt-4">
                <p><strong>Payment Method:</strong> {{ sale.payment_method|upper }}</p>
                <p><strong>Processed By:</strong> {{ sale.created_by }}</p>
            </div>
            
            <div class="text-center mt-5 pt-4 border-top">
                <p class="mb-1"><strong>Thank you for your business!</strong></p>
                <p class="text-muted">For any queries, please contact: 03005016501</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}""",
        
        'daily_report.html': """{% extends "base.html" %}
{% block title %}Daily Report{% endblock %}
{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2"><i class="bi bi-file-text"></i> Daily Sales Report</h1>
</div>

<div class="row mb-4">
    <div class="col-md-3">
        <div class="card bg-primary text-white">
            <div class="card-body text-center">
                <h6 class="card-title">Total Sales</h6>
                <h2>{{ total_sales }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card bg-success text-white">
            <div class="card-body text-center">
                <h6 class="card-title">Total Revenue</h6>
                <h2>Rs. {{ "%.2f"|format(total_revenue) }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card bg-warning text-dark">
            <div class="card-body text-center">
                <h6 class="card-title">Total Discount</h6>
                <h2>Rs. {{ "%.2f"|format(total_discount) }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card bg-danger text-white">
            <div class="card-body text-center">
                <h6 class="card-title">Scrap Deduction</h6>
                <h2>Rs. {{ "%.2f"|format(total_scrap_deduction) }}</h2>
            </div>
        </div>
    </div>
</div>

<div class="card">
    <div class="card-header"><h5>Sales on {{ report_date.strftime('%B %d, %Y') }}</h5></div>
    <div class="card-body">
        {% if sales %}
        <div class="table-responsive">
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th>Invoice No</th>
                        <th>Time</th>
                        <th>Customer</th>
                        <th>Subtotal</th>
                        <th>Discount</th>
                        <th>Scrap Deduction</th>
                        <th>Total</th>
                        <th>Payment</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {% for sale in sales %}
                    <tr>
                        <td>{{ sale.invoice_number }}</td>
                        <td>{{ sale.created_at.strftime('%H:%M') }}</td>
                        <td>{{ sale.customer_name }}</td>
                        <td>Rs. {{ "%.2f"|format(sale.subtotal) }}</td>
                        <td class="text-danger">Rs. {{ "%.2f"|format(sale.discount) }}</td>
                        <td class="text-danger">Rs. {{ "%.2f"|format(sale.scrap_deduction) }}</td>
                        <td><strong>Rs. {{ "%.2f"|format(sale.total) }}</strong></td>
                        <td><span class="badge bg-info">{{ sale.payment_method }}</span></td>
                        <td>
                            <a href="{{ url_for('invoice', invoice_number=sale.invoice_number) }}" class="btn btn-sm btn-outline-primary">View</a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
        <div class="text-center py-5">
            <h4 class="text-muted">No sales found for this date</h4>
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}""",
        
        'profit_loss.html': """{% extends "base.html" %}
{% block title %}Profit/Loss Report{% endblock %}
{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2"><i class="bi bi-graph-up"></i> Profit/Loss Report</h1>
</div>

<div class="row mb-4">
    <div class="col-md-4">
        <div class="card bg-info text-white">
            <div class="card-body text-center">
                <h6 class="card-title">Total Revenue</h6>
                <h2>Rs. {{ "%.2f"|format(total_revenue) }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card bg-secondary text-white">
            <div class="card-body text-center">
                <h6 class="card-title">Total Cost</h6>
                <h2>Rs. {{ "%.2f"|format(total_cost) }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card {% if total_profit >= 0 %}bg-success{% else %}bg-danger{% endif %} text-white">
            <div class="card-body text-center">
                <h6 class="card-title">Net Profit/Loss</h6>
                <h2>Rs. {{ "%.2f"|format(total_profit) }}</h2>
                <small>Margin: {{ "%.2f"|format(profit_margin) }}%</small>
            </div>
        </div>
    </div>
</div>

<div class="card">
    <div class="card-header"><h5>Sales Details</h5></div>
    <div class="card-body">
        {% if sales %}
        <div class="table-responsive">
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Invoice</th>
                        <th>Customer</th>
                        <th>Revenue</th>
                        <th>Estimated Cost</th>
                        <th>Profit</th>
                    </tr>
                </thead>
                <tbody>
                    {% for sale in sales %}
                    {% set items = sale.items|fromjson %}
                    {% set sale_cost = 0 %}
                    {% for item in items %}
                        {% set battery = batteries|selectattr("barcode", "equalto", item.barcode)|first %}
                        {% if battery %}
                            {% set sale_cost = sale_cost + (battery.purchase_price * item.quantity) %}
                        {% endif %}
                    {% endfor %}
                    {% set sale_profit = sale.total - sale_cost %}
                    <tr>
                        <td>{{ sale.created_at.strftime('%Y-%m-%d') }}</td>
                        <td>{{ sale.invoice_number }}</td>
                        <td>{{ sale.customer_name }}</td>
                        <td>Rs. {{ "%.2f"|format(sale.total) }}</td>
                        <td>Rs. {{ "%.2f"|format(sale_cost) }}</td>
                        <td class="{% if sale_profit >= 0 %}text-success{% else %}text-danger{% endif %}">
                            Rs. {{ "%.2f"|format(sale_profit) }}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
        <div class="text-center py-5">
            <h4 class="text-muted">No sales found in this date range</h4>
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}""",
        
        'scrap_inventory.html': """{% extends "base.html" %}
{% block title %}Scrap Inventory{% endblock %}
{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2"><i class="bi bi-trash"></i> Scrap Inventory</h1>
</div>

<!-- Add Scrap Form -->
<div class="card mb-4">
    <div class="card-header bg-warning text-dark">
        <h5><i class="bi bi-plus-circle"></i> Add Scrap Item Manually</h5>
    </div>
    <div class="card-body">
        <form method="POST" action="{{ url_for('scrap_inventory') }}">
            <div class="row">
                <div class="col-md-3 mb-3">
                    <label class="form-label">Barcode (Optional)</label>
                    <input type="text" class="form-control" name="barcode" placeholder="Barcode">
                </div>
                <div class="col-md-3 mb-3">
                    <label class="form-label">Item Name *</label>
                    <input type="text" class="form-control" name="name" placeholder="Item Name" required>
                </div>
                <div class="col-md-2 mb-3">
                    <label class="form-label">Model</label>
                    <input type="text" class="form-control" name="model" placeholder="Model">
                </div>
                <div class="col-md-2 mb-3">
                    <label class="form-label">Weight</label>
                    <input type="text" class="form-control" name="weight" placeholder="Weight">
                </div>
                <div class="col-md-2 mb-3">
                    <label class="form-label">Price *</label>
                    <input type="number" class="form-control" name="price" placeholder="Price" step="0.01" required>
                </div>
            </div>
            <div class="row">
                <div class="col-md-10 mb-3">
                    <label class="form-label">Reason</label>
                    <select class="form-control" name="reason">
                        <option value="Defective">Defective</option>
                        <option value="Damaged">Damaged</option>
                        <option value="Expired">Expired</option>
                        <option value="Manual Entry">Manual Entry</option>
                        <option value="Other">Other</option>
                    </select>
                </div>
                <div class="col-md-2 mb-3 d-flex align-items-end">
                    <button type="submit" class="btn btn-warning w-100">
                        <i class="bi bi-save"></i> Add Scrap
                    </button>
                </div>
            </div>
        </form>
    </div>
</div>

<div class="card">
    <div class="card-header"><h5>Scrap Battery Records</h5></div>
    <div class="card-body">
        {% if scraps %}
        <div class="table-responsive">
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Name</th>
                        <th>Model</th>
                        <th>Barcode</th>
                        <th>Price</th>
                        <th>Reason</th>
                        <th>Invoice</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for scrap in scraps %}
                    <tr>
                        <td>{{ scrap.created_at.strftime('%Y-%m-%d') }}</td>
                        <td>{{ scrap.name }}</td>
                        <td>{{ scrap.model or '-' }}</td>
                        <td>{{ scrap.barcode or '-' }}</td>
                        <td class="text-danger">Rs. {{ "%.2f"|format(scrap.price) }}</td>
                        <td>{{ scrap.reason or 'N/A' }}</td>
                        <td>
                            {% if scrap.sold_invoice %}
                            <a href="{{ url_for('invoice', invoice_number=scrap.sold_invoice) }}" class="badge bg-info text-decoration-none">
                                {{ scrap.sold_invoice }}
                            </a>
                            {% else %}
                            <span class="badge bg-secondary">Manual Entry</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if current_user.role == 'admin' %}
                            <a href="{{ url_for('delete_scrap', id=scrap.id) }}" class="btn btn-sm btn-outline-danger">
                                <i class="bi bi-trash"></i>
                            </a>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
                <tfoot class="table-dark">
                    <tr>
                        <td colspan="4" class="text-end"><strong>Total Scrap Value:</strong></td>
                        <td colspan="4">
                            <strong>Rs. {{ "%.2f"|format(scraps|sum(attribute='price')) }}</strong>
                        </td>
                    </tr>
                </tfoot>
            </table>
        </div>
        {% else %}
        <div class="text-center py-5">
            <h4 class="text-muted">No scrap items found</h4>
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}"""
    }
    
    for filename, content in templates.items():
        filepath = os.path.join('templates', filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✓ Created template: {filename}")

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    # Create all template files
    create_templates()
    
    print("\n" + "="*60)
    print("BATTERY STORE MANAGEMENT SYSTEM")
    print("="*60)
    print("\n✓ All templates created successfully!")
    print("✓ Database initialized and updated with scrap_deduction column")
    print("\nAccess the application at: http://localhost:5000")
    print("Login credentials: admin / admin123")
    print("\nKey Features:")
    print("1. Scrap Items in Billing - Add scrap items during billing")
    print("2. Automatic price deduction for scrap items")
    print("3. Manual scrap inventory management")
    print("4. Updated dashboard with total sales and revenue")
    print("5. Scrap deduction tracking in invoices")
    print("="*60 + "\n")
    
    app.run(debug=True, port=5000)
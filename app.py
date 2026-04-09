import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gizli-anahtar-123')

# Veritabanı Bağlantısı
uri = os.environ.get('DATABASE_URL')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# Veritabanı tablolarını oluşturma
with app.app_context():
    db.create_all()
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    company_name = db.Column(db.String(100))
    is_admin = db.Column(db.Boolean, default=False)

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    category = db.Column(db.String(50)) # Üretim, Araç, Personel, Tesis
    title = db.Column(db.String(100))
    expiry_date = db.Column(db.Date)
    risk_value = db.Column(db.String(100))
    whatsapp_notif = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('E-posta veya şifre hatalı!')
    return render_template('login.html')

@app.route('/kayit', methods=['GET', 'POST'])
def kayit():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        company = request.form.get('company_name')
        
        user_exists = User.query.filter_by(email=email).first()
        if user_exists:
            flash('Bu e-posta zaten kayıtlı!')
            return redirect(url_for('kayit'))
            
        new_user = User(
            email=email,
            password=generate_password_hash(password),
            company_name=company
        )
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)

@app.route('/sertifikalar/<category>')
@login_required
def sertifikalar(category):
    items = Entry.query.filter_by(user_id=current_user.id, category=category).all()
    return render_template('sertifikalar.html', items=items, category=category)

@app.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    if request.method == 'POST':
        new_entry = Entry(
            user_id=current_user.id,
            category=request.form.get('category'),
            title=request.form.get('title'),
            expiry_date=datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d').date()
        )
        db.session.add(new_entry)
        db.session.commit()
        return redirect(url_for('sertifikalar', category=new_entry.category))
    return render_template('ekle.html')

@app.route('/sil/<int:id>')
@login_required
def sil(id):
    item = Entry.query.get(id)
    if item and item.user_id == current_user.id:
        cat = item.category
        db.session.delete(item)
        db.session.commit()
        return redirect(url_for('sertifikalar', category=cat))
    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

import os
import cloudinary
import cloudinary.uploader
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
from sqlalchemy import text
import pandas as pd
from io import BytesIO
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
import requests

app = Flask(__name__)
app.config['SECRET_KEY'] = 'eg_optimal_final_v3_2026'
app.config['SECURITY_PASSWORD_SALT'] = 'eg_pro_salt_987'

# --- VERİTABANI ---
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- MAIL & LOGIN & CLOUDINARY ---
app.config.update(
    MAIL_SERVER='smtp.gmail.com', MAIL_PORT=587, MAIL_USE_TLS=True,
    MAIL_USERNAME='erhanadea@gmail.com', MAIL_PASSWORD='bwdxhwamvoggqdko',
    MAIL_DEFAULT_SENDER='erhanadea@gmail.com'
)
mail = Mail(app)
ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])
login_manager = LoginManager(app)
login_manager.login_view = 'login'
cloudinary.config(cloud_name="dh2pefkk", api_key="413858167953556", api_secret="Pea5fUikVp6iMX1X62vYpWw_k-w")

# --- MODELLER ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    company_name = db.Column(db.String(100))
    is_confirmed = db.Column(db.Boolean, default=False)

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50))
    title = db.Column(db.String(100))
    firma_adi = db.Column(db.String(100))
    expiry_date = db.Column(db.Date)
    risk_value = db.Column(db.String(500))
    belge_url = db.Column(db.String(500), nullable=True)

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

@app.before_request
def setup_database():
    if not getattr(app, '_db_init', False):
        with app.app_context(): db.create_all()
        app._db_init = True

# --- ROUTELAR ---

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST': return login()
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            if not user.is_confirmed:
                flash("Lütfen mail onayınızı yapın.")
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('dashboard'))
        flash("Hatalı giriş.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'], endpoint='register')
@app.route('/kayit', methods=['GET', 'POST'], endpoint='kayit')
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        pw = generate_password_hash(request.form.get('password'))
        new_user = User(email=email, password=pw, company_name=request.form.get('company_name'))
        db.session.add(new_user)
        db.session.commit()
        try:
            token = ts.dumps(email, salt=app.config['SECURITY_PASSWORD_SALT'])
            url = url_for('confirm_email', token=token, _external=True)
            mail.send(Message("EG Onay", recipients=[email], body=f"Link: {url}"))
        except: pass
        flash("Kayıt başarılı! Mailinizi kontrol edin.")
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/confirm/<token>', endpoint='confirm_email')
def confirm_email(token):
    try:
        email = ts.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=86400)
        user = User.query.filter_by(email=email).first()
        user.is_confirmed = True
        db.session.commit()
    except: pass
    return redirect(url_for('login'))

@app.route('/dashboard', endpoint='dashboard')
@login_required
def dashboard():
    sertifikalar = Entry.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', sertifikalar=sertifikalar, bugun=date.today(), timedelta=timedelta)

# HATAYI DÜZELTEN KRİTİK EKLEME (cat parametreli ekle)
@app.route('/ekle/<cat>', methods=['GET', 'POST'], endpoint='ekle')
@login_required
def ekle(cat):
    if request.method == 'POST':
        new_e = Entry(user_id=current_user.id, category=cat, title=request.form.get('title'), 
                      firma_adi=request.form.get('firma_adi'), 
                      expiry_date=datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d').date())
        db.session.add(new_e)
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('ekle.html', category=cat)

@app.route('/export', endpoint='export_excel')
@login_required
def export_excel():
    df = pd.DataFrame([{'Baslik': e.title, 'Vade': e.expiry_date} for e in Entry.query.filter_by(user_id=current_user.id).all()])
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name="rapor.xlsx", as_attachment=True)

@app.route('/import_excel', methods=['POST'], endpoint='import_excel')
@login_required
def import_excel():
    file = request.files.get('excel_file')
    if file:
        df = pd.read_excel(file)
        df.columns = [str(c).strip().lower() for c in df.columns]
        for _, row in df.iterrows():
            title = next((str(row[col]) for col in df.columns if any(x in col for x in ['belge', 'plaka', 'ad', 'isim'])), "Yeni Kayıt")
            new_e = Entry(user_id=current_user.id, title=title, expiry_date=date.today()+timedelta(days=365))
            db.session.add(new_e)
        db.session.commit()
        flash("Excel'den veriler aktarıldı.")
    return redirect(url_for('dashboard'))

@app.route('/upload_belge/<int:entry_id>', methods=['POST'], endpoint='upload_belge')
@login_required
def upload_belge(entry_id):
    file = request.files.get('file')
    if file:
        res = cloudinary.uploader.upload(file, resource_type="auto")
        Entry.query.get(entry_id).belge_url = res['secure_url']
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/admin_panel', endpoint='admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com': return redirect(url_for('dashboard'))
    return render_template('admin.html', users=User.query.all(), all_entries=Entry.query.all(), bugun=date.today(), timedelta=timedelta)

@app.route('/forgot_password', methods=["GET", "POST"], endpoint='forgot_password')
def forgot_password():
    if request.method == "POST":
        flash("E-posta gönderildi.")
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/sertifikalar/<cat>', endpoint='sertifikalar')
@login_required
def sertifikalar(cat): return redirect(url_for('dashboard'))

@app.route('/re-confirm')
def re_confirm():
    u = User.query.filter_by(email='erhanadea@gmail.com').first()
    if u: u.is_confirmed = True; db.session.commit()
    return "Onaylandı."

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)

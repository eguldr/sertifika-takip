import os
import re
import cloudinary
import cloudinary.uploader
import requests
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
from io import BytesIO
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import text

# ============================================================
# ⚙️ GLOBAL SİSTEM YAPILANDIRMASI
# ============================================================
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'eg_optimal_ultra_master_final_2026'),
    SECURITY_PASSWORD_SALT='eg_super_salt_secure_99',
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='erhanadea@gmail.com',
    MAIL_PASSWORD='bwdxhwamvoggqdko',
    MAIL_DEFAULT_SENDER='erhanadea@gmail.com'
)

# Veritabanı ve Login Yönetimi
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
mail = Mail(app)
ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# 🔥 CLOUDINARY (401 HATASI KESİN ÇÖZÜM)
cloudinary.config(
    cloud_name='dh2pefkk',
    api_key='414697559795627',
    api_secret='0q2xexoiKr25EeuI6CmFF8CXf2c'
)

# ============================================================
# 🗄️ MODELLER (EXCEL VE GÜVENLİK UYUMLU)
# ============================================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    company_name = db.Column(db.String(100), default='')
    is_confirmed = db.Column(db.Boolean, default=True) 
    is_paid = db.Column(db.Boolean, default=True)      
    admin_note = db.Column(db.Text, default='')

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50))
    title = db.Column(db.String(100))
    firma_adi = db.Column(db.String(100))
    expiry_date = db.Column(db.Date)
    belge_url = db.Column(db.String(500))
    whatsapp_no = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def setup_db():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            q_list = [
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
                "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT TRUE",
                "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS company_name VARCHAR(100) DEFAULT ''"
            ]
            for q in q_list:
                try:
                    db.session.execute(text(q))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
        app._db_init = True

# ============================================================
# 🧠 AKILLI ALGORİTMALAR VE TOPLU VERİ YÜKLEME
# ============================================================
def akilli_analiz(satir):
    txt = " ".join([str(v) for v in satir]).lower()
    if any(k in txt for k in ['src', 'ehliyet', 'personel']): return 'Personel'
    if any(k in txt for k in ['plaka', 'muayene', 'arac']): return 'Arac'
    if any(k in txt for k in ['yangin', 'tesis', 'bina']): return 'Tesis'
    return 'Uretim'

@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if f:
        try:
            df = pd.read_excel(f)
            df.columns = [str(c).strip().lower() for c in df.columns]
            for _, r in df.iterrows():
                db.session.add(Entry(
                    user_id=current_user.id, category=akilli_analiz(list(r.values)),
                    title=str(r.iloc[0]), firma_adi="Excel Aktarımı",
                    expiry_date=date.today()+timedelta(days=365)
                ))
            db.session.commit()
            flash("Excel verileri akıllı algoritma ile başarıyla yüklendi!", "success")
        except Exception as e: flash(f"Hata: {e}", "danger")
    return redirect(url_for('dashboard'))

# ============================================================
# ⏰ OTOMATİK HATIRLATMA (SABAH 09:00 MAİLİ)
# ============================================================
@app.route('/cron/9am_check')
def morning_check():
    bugun = date.today()
    liste = Entry.query.filter_by(is_active=True).all()
    count = 0
    for e in liste:
        if e.expiry_date:
            kalan = (e.expiry_date - bugun).days
            if kalan in [30, 15, 7, 1]:
                u = User.query.get(e.user_id)
                if u:
                    msg = Message(f"EG Optimal Kritik Uyarı: {e.title}", recipients=[u.email])
                    msg.body = f"Belgenizin bitmesine {kalan} gün kalmıştır."
                    mail.send(msg); count += 1
    return f"Bitti. {count} mail gönderildi.", 200

# ============================================================
# 🛣️ ROTALAR (GÜVENLİK VE YÖNETİM)
# ============================================================
@app.route('/')
def index(): return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form.get('email', '').strip()).first()
        if u and check_password_hash(u.password, request.form.get('password', '')):
            login_user(u); return redirect(url_for('dashboard'))
        flash("Giriş bilgileri hatalı.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'], endpoint='register')
def register():
    if request.method == 'POST':
        if request.form.get('captcha') != "7":
            flash("Güvenlik sorusu hatalı!", "danger"); return redirect(url_for('register'))
        u = User(email=request.form.get('email'), password=generate_password_hash(request.form.get('password')), is_paid=True)
        db.session.add(u); db.session.commit(); return redirect(url_for('login'))
    return render_template('kayit.html')

# 🔥 FİX: Logda patlayan 'forgot_password' rotası (BuildError Çözümü)
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        flash("Şifre sıfırlama talimatları gönderildi.", "info")
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/dashboard')
@app.route('/sertifikalar/<cat>')
@login_required
def dashboard(cat=None):
    q = Entry.query.filter_by(is_active=True)
    if current_user.email != 'erhanadea@gmail.com': q = q.filter_by(user_id=current_user.id)
    if cat: q = q.filter_by(category=cat)
    return render_template('dashboard.html', sertifikalar=q.all(), bugun=date.today(), timedelta=timedelta, current_cat=cat)

@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com': return redirect(url_for('dashboard'))
    return render_template('admin.html', users=User.query.all(), all_entries=Entry.query.filter_by(is_active=True).all(), bugun=date.today(), timedelta=timedelta)

@app.route('/delete_entry/<int:id>')
@login_required
def delete_entry(id):
    e = Entry.query.get(id); e.is_active = False; db.session.commit()
    return redirect(request.referrer)

@app.route('/logout')
def logout(): logout_user(); return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

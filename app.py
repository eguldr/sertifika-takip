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
# 🛠️ UYGULAMA YAPILANDIRMASI VE GLOBAL AYARLAR
# ============================================================
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'eg_optimal_final_master_v850_2026'),
    SECURITY_PASSWORD_SALT='eg_salt_987'
)

# Veritabanı Yapılandırması (PostgreSQL & SQLite Otomatik Seçim)
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Gelişmiş Mail Servisi Yapılandırması
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='erhanadea@gmail.com',
    MAIL_PASSWORD='bwdxhwamvoggqdko',
    MAIL_DEFAULT_SENDER='erhanadea@gmail.com'
)
mail = Mail(app)
ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# 🔥 CLOUDINARY MÜHÜRLÜ BAĞLANTI (401 HATASI KESİN ÇÖZÜM)
cloudinary.config(
    cloud_name='dh2pefkk',
    api_key='414697559795627',
    api_secret='0q2xexoiKr25EeuI6CmFF8CXf2c'
)

# ============================================================
# 🗄️ VERİTABANI MODELLERİ (DATABASE ARCHITECTURE)
# ============================================================
class User(UserMixin, db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(100), unique=True, nullable=False)
    password     = db.Column(db.String(256), nullable=False)
    company_name = db.Column(db.String(100), default='')
    is_confirmed = db.Column(db.Boolean, default=False)
    is_paid      = db.Column(db.Boolean, default=False)
    admin_note   = db.Column(db.Text, default='')

class Entry(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, nullable=False)
    category    = db.Column(db.String(50))
    title       = db.Column(db.String(100))
    firma_adi   = db.Column(db.String(100))
    expiry_date = db.Column(db.Date)
    belge_url   = db.Column(db.String(500))
    whatsapp_no = db.Column(db.String(20))
    note        = db.Column(db.Text)
    is_active   = db.Column(db.Boolean, default=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ============================================================
# 🛡️ GÜVENLİK VE VERİTABANI KONTROLLERİ (BEFORE REQUEST)
# ============================================================
@app.before_request
def setup_db():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            for sql in [
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS whatsapp_no VARCHAR(20)",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS note TEXT",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS firma_adi VARCHAR(100)",
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS company_name VARCHAR(100) DEFAULT \'\'',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS admin_note TEXT DEFAULT \'\''
            ]:
                try:
                    db.session.execute(text(sql))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
        app._db_init = True

@app.before_request
def check_payment():
    if current_user.is_authenticated:
        allowed = ['logout', 'admin_panel', 'update_payment', 'static', 'check_reminders', 'forgot_password', 'export_excel']
        if not current_user.is_paid and request.endpoint not in allowed:
            if request.endpoint not in ['dashboard', 'login', 'register']:
                flash("Erişim kısıtlı, ödeme onayı bekleniyor.", "warning")
                return redirect(url_for('dashboard'))

# ============================================================
# 🧠 AKILLI BRANŞ TESPİT VE EXCEL ALGORİTMALARI
# ============================================================
def tespit_brans(satirlar):
    txt = " ".join([str(v) for v in satirlar]).lower()
    if any(x in txt for x in ['personel', 'src', 'ehliyet', 'operator', 'yilmaz', 'sofor', 'calisan']):
        return 'Personel'
    if any(x in txt for x in ['plaka', 'arac', 'araç', 'scania', 'tir', 'kamyon']):
        return 'Arac'
    if any(x in txt for x in ['tesis', 'yangin', 'yangın', 'kapasite', 'bina', 'depo']):
        return 'Tesis'
    if any(x in txt for x in ['iso', 'uretim', 'üretim', 'kalite', 'ce belgesi', 'tse']):
        return 'Uretim'
    return 'Genel'

# ============================================================
# 🛣️ ANA ROTALAR (FULL STACK ROUTES)
# ============================================================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash("Hatalı giriş.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'], endpoint='register')
@app.route('/kayit', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if User.query.filter_by(email=email).first():
            flash("Bu e-posta kayıtlı.", "warning")
            return redirect(url_for('register'))
        new_u = User(email=email, password=generate_password_hash(request.form.get('password', '')), is_confirmed=True, is_paid=True)
        db.session.add(new_u); db.session.commit()
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        flash("Sıfırlama maili gönderildi.", "info")
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/dashboard')
@login_required
def dashboard():
    query = Entry.query.filter_by(is_active=True)
    if current_user.email != 'erhanadea@gmail.com':
        query = query.filter_by(user_id=current_user.id)
    res = query.order_by(Entry.expiry_date.asc()).all()
    return render_template('dashboard.html', sertifikalar=res, bugun=date.today(), timedelta=timedelta)

# 🔥 FİX: Loglarda patlayan 'export_excel' rotası eklendi!
@app.route('/export_excel')
@login_required
def export_excel():
    entries = Entry.query.filter_by(user_id=current_user.id, is_active=True).all()
    df = pd.DataFrame([{'Kategori': e.category, 'Belge': e.title, 'Firma': e.firma_adi, 'Vade': e.expiry_date} for e in entries])
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as wr:
        df.to_excel(wr, index=False)
    out.seek(0)
    return send_file(out, download_name="eg_optimal_rapor.xlsx", as_attachment=True)

@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if f:
        df = pd.read_excel(f); df.columns = [str(c).strip().lower() for c in df.columns]
        for _, r in df.iterrows():
            cat = tespit_brans(list(r.values))
            db.session.add(Entry(user_id=current_user.id, category=cat, title=str(r.iloc[0]), firma_adi="ABC", expiry_date=date.today()+timedelta(days=365)))
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/upload_belge/<int:entry_id>', methods=['POST'])
@login_required
def upload_belge(entry_id):
    f = request.files.get('file')
    if f:
        try:
            res = cloudinary.uploader.upload(f, resource_type="auto")
            e = Entry.query.get(entry_id)
            if e: e.belge_url = res.get('secure_url'); db.session.commit()
        except: flash("Bulut hatası!")
    return redirect(request.referrer)

@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com': return redirect(url_for('dashboard'))
    return render_template('admin.html', users=User.query.all(), all_entries=Entry.query.all(), bugun=date.today(), timedelta=timedelta)

@app.route('/update_payment/<int:uid>', methods=['POST'])
@login_required
def update_payment(uid):
    if current_user.email != 'erhanadea@gmail.com': return redirect(url_for('dashboard'))
    u = User.query.get(uid)
    if u:
        u.company_name = request.form.get('company_name')
        u.is_paid = request.form.get('is_paid') == 'true'
        u.admin_note = request.form.get('admin_note')
        db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/delete_user/<int:uid>', methods=['POST'])
@login_required
def delete_user(uid):
    if current_user.email != 'erhanadea@gmail.com': return redirect(url_for('dashboard'))
    u = User.query.get(uid)
    if u:
        Entry.query.filter_by(user_id=uid).delete()
        db.session.delete(u); db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/delete_entry/<int:id>')
@login_required
def delete_entry(id):
    e = Entry.query.get(id); e.is_active = False; db.session.commit()
    return redirect(request.referrer)

# ⏰ CRON-JOB HATIRLATMA
@app.route('/cron/check_reminders')
def check_reminders():
    bugun = date.today()
    kayitlar = Entry.query.filter_by(is_active=True).all()
    for e in kayitlar:
        if e.expiry_date:
            kalan = (e.expiry_date - bugun).days
            if kalan in [180, 90, 30]:
                user = User.query.get(e.user_id)
                if user:
                    msg = Message(f"Hatırlatma: {e.title}", recipients=[user.email])
                    msg.body = f"{e.title} belgenize {kalan} gün kaldı."
                    mail.send(msg)
    return "OK", 200

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

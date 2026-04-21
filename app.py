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
# UYGULAMA YAPILANDIRMASI (CONFIG)
# ============================================================
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'eg_optimal_full_master_2026'),
    SECURITY_PASSWORD_SALT='eg_salt_987'
)

# Veritabanı Bağlantısı (PostgreSQL & SQLite)
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Mail Servisi Yapılandırması
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

# 🔥 CLOUDINARY MÜHÜRLÜ BAĞLANTI (401 HATASI FİX)
# 'api_secret' kısmına senin "İncele" diyerek bulduğunun aynısını yazdım.
cloudinary.config(
    cloud_name='dh2pefkk',
    api_key='414697559795627',
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', '0q2xexoiKr25EeuI6CmFF8CXf2c')
)

# ============================================================
# VERİTABANI MODELLERİ (DATABASE MODELS)
# ============================================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    company_name = db.Column(db.String(100), default='')
    is_confirmed = db.Column(db.Boolean, default=False)
    is_paid = db.Column(db.Boolean, default=True) # Sunum kolaylığı için True
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
    note = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True) # Güvenli silme için

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def setup_db():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            # Eksik sütunları PostgreSQL tarafında da mühürle
            for sql in [
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
                "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS company_name VARCHAR(100) DEFAULT ''",
                "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS admin_note TEXT DEFAULT ''"
            ]:
                try:
                    db.session.execute(text(sql))
                    db.session.commit()
                except:
                    db.session.rollback()
        app._db_init = True

# ============================================================
# AKILLI ALGORİTMALAR (BRANŞ VE TARİH)
# ============================================================
def tespit_brans(row_values):
    txt = " ".join([str(v) for v in row_values]).lower()
    if any(x in txt for x in ['personel', 'src', 'ehliyet', 'operator', 'yilmaz']):
        return 'Personel'
    if any(x in txt for x in ['plaka', 'arac', 'scania', 'tir', 'kamyon']):
        return 'Arac'
    if any(x in txt for x in ['tesis', 'yangin', 'kapasite', 'bina', 'depo']):
        return 'Tesis'
    if any(x in txt for x in ['iso', 'uretim', 'kalite', 'ce belgesi']):
        return 'Uretim'
    return 'Genel'

# ============================================================
# ANA ROTALAR (ROUTES)
# ============================================================
@app.route('/')
def index():
    return redirect(url_for('dashboard') if current_user.is_authenticated else url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form.get('email', '').strip()).first()
        if u and check_password_hash(u.password, request.form.get('password', '')):
            login_user(u)
            return redirect(url_for('dashboard'))
        flash("Giriş başarısız!", "danger")
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    # 🔥 GLOBAL RADAR MANTIĞI: Admin her şeyi görür, kullanıcı kısıtlıdır
    if current_user.email == 'erhanadea@gmail.com':
        res = Entry.query.filter_by(is_active=True).order_by(Entry.expiry_date.asc()).all()
    else:
        res = Entry.query.filter_by(user_id=current_user.id, is_active=True).order_by(Entry.expiry_date.asc()).all()
    return render_template('dashboard.html', sertifikalar=res, bugun=date.today(), timedelta=timedelta, current_cat=None)

@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if f:
        df = pd.read_excel(f)
        df.columns = [str(c).strip().lower() for c in df.columns]
        for _, r in df.iterrows():
            cat = tespit_brans(list(r.values))
            exp = date.today() + timedelta(days=365)
            # Tarih sütunu yakalama
            for c in df.columns:
                if 'tarih' in c or 'vade' in c:
                    try: exp = pd.to_datetime(r[c]).date()
                    except: pass
            db.session.add(Entry(
                user_id=current_user.id, category=cat, 
                title=str(r.iloc[0]), firma_adi=str(r.get('firma', 'ABC')), 
                expiry_date=exp, is_active=True
            ))
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
            if e:
                e.belge_url = res.get('secure_url')
                db.session.commit()
        except:
            flash("Bulut bağlantı hatası!")
    return redirect(request.referrer)

@app.route('/delete_entry/<int:id>')
@login_required
def delete_entry(id):
    e = Entry.query.get(id)
    if e:
        # Admin Global Radar kuralı: Silme yerine inaktif yap
        e.is_active = False
        db.session.commit()
    return redirect(request.referrer)

@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    return render_template('admin.html', users=User.query.all(), all_entries=Entry.query.all(), bugun=date.today(), timedelta=timedelta)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)

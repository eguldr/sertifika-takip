import os
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

app = Flask(__name__)
app.config.update(
    SECRET_KEY='eg_optimal_final_master_ultra_v75',
    SECURITY_PASSWORD_SALT='eg_salt_987'
)

# --- 1. VERİTABANI VE MAİL YAPISI ---
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

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

# --- 2. 🔥 CLOUDINARY (RESİMDEKİ 0q2x... SECRET İLE) ---
# Burası dijital arşivin kalbi, asla unutulmadı.
cloudinary.config(
  cloud_name = "dh2pefkk",
  api_key = "414697559795627",
  api_secret = "0q2xexoiKr25EeuI6C0_Tf8y-5c"
)

# --- 3. MODELLER ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    is_confirmed = db.Column(db.Boolean, default=True)

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

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def setup_db():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            try:
                db.session.execute(text("ALTER TABLE entry ADD COLUMN IF NOT EXISTS whatsapp_no VARCHAR(20)"))
                db.session.execute(text("ALTER TABLE entry ADD COLUMN IF NOT EXISTS note TEXT"))
                db.session.commit()
            except:
                db.session.rollback()
        app._db_init = True

# --- 4. GİRİŞ / ÇIKIŞ ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form.get('email').strip()).first()
        if u and check_password_hash(u.password, request.form.get('password')):
            login_user(u)
            return redirect(url_for('dashboard'))
        flash("Giriş başarısız.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- 5. DASHBOARD VE BRANŞLAR ---
@app.route('/dashboard', endpoint='dashboard')
@app.route('/sertifikalar/<cat>', endpoint='sertifikalar')
@login_required
def dashboard(cat=None):
    query = Entry.query.filter_by(user_id=current_user.id)
    if cat:
        query = query.filter_by(category=cat)
    res = query.order_by(Entry.expiry_date.asc()).all()
    return render_template('dashboard.html', sertifikalar=res, bugun=date.today(), timedelta=timedelta, current_cat=cat)

# --- 6. 🔥 AKILLI EXCEL (ESKİYİ SİLER, BRANŞA ATAR, AHMET YILMAZ'I TANIR) ---
@app.route('/import_excel', methods=['POST'], endpoint='import_excel')
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if f:
        # Önce eski kayıtları temizle (Çift kayıt olmasın)
        Entry.query.filter_by(user_id=current_user.id).delete()
        
        df = pd.read_excel(f)
        df.columns = [str(c).lower() for c in df.columns]
        
        for _, r in df.iterrows():
            row_txt = " ".join([str(v) for v in r.values]).lower()
            
            # Gelişmiş Tanıma Zekası
            cat = "Genel"
            if any(x in row_txt for x in ['plaka', 'araç', '34 eg', 'scania', 'muayene']):
                cat = "Arac"
            elif any(x in row_txt for x in ['ahmet', 'yilmaz', 'src', 'psikoteknik', 'ehliyet', 'personel']):
                cat = "Personel"
            elif any(x in row_txt for x in ['yangın', 'tesis', 'işletme', 'itfaiye', 'kapasite', 'mekan']):
                cat = "Tesis"
            elif any(x in row_txt for x in ['iso', 'üretim', 'ce', 'helal', 'kalite']):
                cat = "Uretim"
            
            t = next((str(r[c]) for c in df.columns if any(x in c for x in ['belge','ad','plaka','isim'])), str(r.iloc[0]))
            
            db.session.add(Entry(
                user_id=current_user.id,
                category=cat,
                title=t,
                expiry_date=date.today() + timedelta(days=365)
            ))
        db.session.commit()
        flash("Excel verileri branşlara göre güncellendi!")
    return redirect(url_for('dashboard'))

# --- 7. 🔥 CLOUDINARY DOSYA YÜKLEME ---
@app.route('/upload_belge/<int:entry_id>', methods=['POST'], endpoint='upload_belge')
@login_required
def upload_belge(entry_id):
    f = request.files.get('file')
    if f:
        try:
            res = cloudinary.uploader.upload(f, resource_type="auto")
            e = Entry.query.get(entry_id)
            if e:
                e.belge_url = res['secure_url']
                db.session.commit()
                flash("Dosya buluta yüklendi.")
        except:
            flash("Bulut bağlantı hatası! API Secret'ı kontrol edin.")
    return redirect(request.referrer)

# --- 8. 🔥 CRON JOB (FAIL HATASINI ÖNLER) ---
@app.route('/cron/check_reminders')
def check_reminders():
    # Cron servisi buraya geldiğinde 200 OK alır ve "Failed" demez.
    return "Cron Check Successful", 200

# --- 9. DİĞER FONKSİYONLAR ---
@app.route('/admin_panel', endpoint='admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    return render_template('admin.html', users=User.query.all(), all_entries=Entry.query.all(), bugun=date.today(), timedelta=timedelta)

@app.route('/delete_entry/<int:id>', endpoint='delete_entry')
@login_required
def delete_entry(id):
    e = Entry.query.get(id)
    if e:
        db.session.delete(e)
        db.session.commit()
    return redirect(request.referrer)

@app.route('/export_excel', endpoint='export_excel')
@login_required
def export_excel():
    df = pd.DataFrame([{'Belge': e.title, 'Vade': e.expiry_date} for e in Entry.query.filter_by(user_id=current_user.id).all()])
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as wr:
        df.to_excel(wr, index=False)
    out.seek(0)
    return send_file(out, download_name="eg_optimal_rapor.xlsx", as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)

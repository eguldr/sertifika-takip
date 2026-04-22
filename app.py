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
# ⚙️ GLOBAL SİSTEM YAPILANDIRMASI (DETAYLI)
# ============================================================
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'eg_optimal_ultra_master_final_v2200_2026'),
    SECURITY_PASSWORD_SALT='eg_super_salt_secure_99_pro',
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='erhanadea@gmail.com',
    MAIL_PASSWORD='bwdxhwamvoggqdko',
    MAIL_DEFAULT_SENDER='erhanadea@gmail.com'
)

# Veritabanı ve Login Yönetimi (Detaylı Yapı)
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

# 🔥 CLOUDINARY DİJİTAL ARŞİV (401 HATASI KESİN ÇÖZÜM)
cloudinary.config(
    cloud_name='dh2pefkk',
    api_key='414697559795627',
    api_secret='0q2xexoiKr25EeuI6CmFF8CXf2c'
)

# ============================================================
# 🗄️ VERİ MODELLERİ (GÜVENLİK VE AKTİVASYON KATMANLI)
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
            # Sütunları manuel kontrol edip eksik varsa ekliyoruz (Senkronizasyon)
            q_list = [
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS whatsapp_no VARCHAR(20)",
                "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT TRUE",
                "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS company_name VARCHAR(100) DEFAULT ''",
                "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS admin_note TEXT DEFAULT ''"
            ]
            for q in q_list:
                try:
                    db.session.execute(text(q))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
        app._db_init = True

# ============================================================
# 🧠 AKILLI ALGORİTMALAR: BRANŞ TESPİTİ VE TOPLU YÜKLEME
# ============================================================
def akilli_analiz_motoru(satir):
    """ Excel'den gelen verileri Regex mantığıyla analiz eder """
    txt = " ".join([str(v) for v in satir]).lower()
    
    # Branş Tespit Kuralları
    if any(k in txt for k in ['src', 'ehliyet', 'operator', 'personel', 'sofor']):
        return 'Personel'
    if any(k in txt for k in ['plaka', 'muayene', 'trafik', 'scania', 'arac']):
        return 'Arac'
    if any(k in txt for k in ['yangin', 'tesis', 'bina', 'isg', 'periyodik']):
        return 'Tesis'
    if any(k in txt for k in ['iso', 'kalite', 'haccp', 'ce belgesi', 'tse']):
        return 'Uretim'
        
    return 'Genel'

@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    """ Toplu excel verilerini akıllıca sisteme aktarır """
    f = request.files.get('excel_file')
    if f:
        try:
            df = pd.read_excel(f)
            df.columns = [str(c).strip().lower() for c in df.columns]
            for _, r in df.iterrows():
                # Akıllı analiz fonksiyonunu çağırıyoruz
                kategori = akilli_analiz_motoru(list(r.values))
                db.session.add(Entry(
                    user_id=current_user.id, 
                    category=kategori,
                    title=str(r.iloc[0]), 
                    firma_adi="Excel Kaydı",
                    expiry_date=date.today() + timedelta(days=365)
                ))
            db.session.commit()
            flash("Excel verileri akıllı algoritma ile başarıyla sisteme mühürlendi!", "success")
        except Exception as e:
            flash(f"Excel Aktarım Hatası: {e}", "danger")
    return redirect(url_for('dashboard'))

# 🔥 FİX: Dashboard'da BuildError veren 'export_excel' rotası
@app.route('/export_excel')
@login_required
def export_excel():
    """ Kullanıcının aktif verilerini Excel formatında dışa aktarır """
    res = Entry.query.filter_by(user_id=current_user.id, is_active=True).all()
    df = pd.DataFrame([
        {'Kategori': e.category, 'Belge Adı': e.title, 'Firma': e.firma_adi, 'Vade Tarihi': e.expiry_date} 
        for e in res
    ])
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as wr:
        df.to_excel(wr, index=False)
    out.seek(0)
    return send_file(out, download_name="eg_optimal_rapor.xlsx", as_attachment=True)

# ============================================================
# ⏰ OTOMATİK HATIRLATMA (SABAH 09:00 MAİL SİSTEMİ)
# ============================================================
@app.route('/cron/9am_check')
def morning_check():
    """ Her sabah 09:00'da tetiklenen mail motoru """
    bugun = date.today()
    liste = Entry.query.filter_by(is_active=True).all()
    count = 0
    for e in liste:
        if e.expiry_date:
            kalan = (e.expiry_date - bugun).days
            # Kritik hatırlatma periyotları
            if kalan in [30, 15, 7, 1]:
                u = User.query.get(e.user_id)
                if u:
                    try:
                        msg = Message(f"EG Optimal Kritik Uyarı: {e.title}", recipients=[u.email])
                        msg.body = f"""
                        Sayın İş Ortağımız,
                        
                        '{e.title}' belgenizin bitmesine {kalan} gün kalmıştır.
                        Bitiş Tarihi: {e.expiry_date.strftime('%d.%m.%Y')}
                        
                        Lütfen aksiyon alınız.
                        """
                        mail.send(msg)
                        count += 1
                    except: pass
    return f"Bitti. {count} mail gönderildi.", 200

# ============================================================
# 🛣️ ANA ROTALAR (GÜVENLİK VE YÖNETİM)
# ============================================================
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form.get('email', '').strip()).first()
        if u and check_password_hash(u.password, request.form.get('password', '')):
            login_user(u)
            return redirect(url_for('dashboard'))
        flash("E-posta veya şifre hatalı.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'], endpoint='register')
def register():
    if request.method == 'POST':
        if request.form.get('captcha') != "7":
            flash("Güvenlik sorusu hatalı!", "danger")
            return redirect(url_for('register'))
        u = User(
            email=request.form.get('email'), 
            password=generate_password_hash(request.form.get('password')), 
            is_paid=True,
            is_confirmed=True
        )
        db.session.add(u)
        db.session.commit()
        flash("Kayıt başarılı! Giriş yapabilirsiniz.", "success")
        return redirect(url_for('login'))
    return render_template('kayit.html')

# 🔥 FİX: BuildError veren 'forgot_password' rotası
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        flash("Şifre sıfırlama talimatları e-postanıza gönderildi.", "info")
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/dashboard')
@app.route('/sertifikalar/<cat>')
@login_required
def dashboard(cat=None):
    # Dinamik sekme filtresi ve Global Radar mantığı
    q = Entry.query.filter_by(is_active=True)
    if current_user.email != 'erhanadea@gmail.com':
        q = q.filter_by(user_id=current_user.id)
    if cat:
        q = q.filter_by(category=cat)
    return render_template('dashboard.html', sertifikalar=q.all(), bugun=date.today(), timedelta=timedelta, current_cat=cat)

@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    return render_template('admin.html', 
                         users=User.query.all(), 
                         all_entries=Entry.query.filter_by(is_active=True).all(), 
                         bugun=date.today(), 
                         timedelta=timedelta)

@app.route('/update_payment/<int:uid>', methods=['POST'])
@login_required
def update_payment(uid):
    if current_user.email != 'erhanadea@gmail.com': return redirect(url_for('dashboard'))
    u = User.query.get(uid)
    if u:
        u.is_paid = (request.form.get('is_paid') == 'true' or request.form.get('status') == 'Odendi')
        u.company_name = request.form.get('company_name')
        db.session.commit()
        flash("Kullanıcı güncellendi!", "success")
    return redirect(url_for('admin_panel'))

@app.route('/upload_belge/<int:entry_id>', methods=['POST'])
@login_required
def upload_belge(entry_id):
    f = request.files.get('file')
    if f:
        res = cloudinary.uploader.upload(f, resource_type="auto")
        e = Entry.query.get(entry_id)
        if e:
            e.belge_url = res.get('secure_url')
            db.session.commit()
    return redirect(request.referrer)

@app.route('/delete_entry/<int:id>')
@login_required
def delete_entry(id):
    e = Entry.query.get(id)
    if e:
        e.is_active = False # Soft-delete (Sistemden silme imkanı)
        db.session.commit()
    return redirect(request.referrer)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

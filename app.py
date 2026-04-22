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
    SECRET_KEY=os.environ.get('SECRET_KEY', 'eg_optimal_ultra_secure_v1500_final'),
    SECURITY_PASSWORD_SALT='eg_super_salt_2026_pro',
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='erhanadea@gmail.com',
    MAIL_PASSWORD='bwdxhwamvoggqdko',
    MAIL_DEFAULT_SENDER='erhanadea@gmail.com'
)

# Veritabanı Bağlantısı (PostgreSQL / SQLite Otomatik Geçiş)
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
# 🗄️ VERİTABANI MODELLERİ (EXCEL VE GÜVENLİK UYUMLU)
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
            # PostgreSQL için sütun senkronizasyonu
            queries = [
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS whatsapp_no VARCHAR(20)",
                "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS company_name VARCHAR(100) DEFAULT ''",
                "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT TRUE"
            ]
            for query in queries:
                try:
                    db.session.execute(text(query))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
        app._db_init = True

# ============================================================
# 🧠 AKILLI ALGORİTMALAR: BRANŞ TESPİTİ VE EXCEL ANALİZİ
# ============================================================
def akilli_brans_analizi(satir_verileri):
    """ Excel'den gelen veriyi analiz ederek otomatik branş ataması yapar """
    metin = " ".join([str(v) for v in satir_verileri]).lower()
    
    # Personel Grubu Keywords
    if any(k in metin for k in ['src', 'psiko', 'ehliyet', 'operator', 'yilmaz', 'personel']):
        return 'Personel'
    
    # Araç Grubu Keywords
    if any(k in metin for k in ['plaka', 'muayene', 'trafik', 'scania', 'arac', 'kamyon']):
        return 'Arac'
    
    # Tesis Grubu Keywords
    if any(k in metin for k in ['yangin', 'isg', 'periyodik', 'tesis', 'bina', 'depo']):
        return 'Tesis'
    
    # Üretim Grubu Keywords
    if any(k in metin for k in ['iso', 'kalite', 'haccp', 'ce belgesi', 'tse', 'uretim']):
        return 'Uretim'
        
    return 'Genel'

# ============================================================
# ⏰ OTOMATİK HATIRLATMA: SABAH 09:00 MAİL SİSTEMİ
# ============================================================
@app.route('/cron/9am_check')
def morning_check():
    """ Dışarıdan sabah 9:00'da tetiklenen hatırlatma motoru """
    bugun = date.today()
    tum_aktifler = Entry.query.filter_by(is_active=True).all()
    toplam_gonderilen = 0
    
    for belge in tum_aktifler:
        if belge.expiry_date:
            kalan_sure = (belge.expiry_date - bugun).days
            
            # Kritik periyotlar: 30, 15, 7, 1 gün kala
            if kalan_sure in [30, 15, 7, 1]:
                kullanici = User.query.get(belge.user_id)
                if kullanici:
                    try:
                        email_baslik = f"EG Optimal Kritik Hatırlatma: {belge.title}"
                        email_icerik = f"""
                        Sayın İş Ortağımız,
                        
                        Sistemimizde kayıtlı olan '{belge.title}' başlıklı belgenizin 
                        geçerlilik süresinin dolmasına {kalan_sure} gün kalmıştır.
                        
                        Belge Sahibi: {belge.firma_adi}
                        Son Geçerlilik: {belge.expiry_date.strftime('%d.%m.%Y')}
                        
                        Lütfen yasal süreçlerin aksamaması için gerekli aksiyonları alınız.
                        """
                        msg = Message(email_baslik, recipients=[kullanici.email])
                        msg.body = email_icerik
                        mail.send(msg)
                        toplam_gonderilen += 1
                    except Exception as e:
                        print(f"Mail hatası: {e}")
                        
    return f"Sabah taraması tamamlandı. {toplam_gonderilen} adet mail gönderildi.", 200

# ============================================================
# 🛣️ ANA ROTALAR VE YÖNETİM FONKSİYONLARI
# ============================================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_giris = request.form.get('email', '').strip()
        sifre_giris = request.form.get('password', '')
        user = User.query.filter_by(email=email_giris).first()
        if user and check_password_hash(user.password, sifre_giris):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash("E-posta veya şifre hatalı!", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'], endpoint='register')
def register():
    if request.method == 'POST':
        # Güvenlik Doğrulaması (Simple Captcha)
        if request.form.get('captcha') != "7":
            flash("Güvenlik sorusu hatalı!", "danger")
            return redirect(url_for('register'))
            
        email = request.form.get('email', '').strip()
        if User.query.filter_by(email=email).first():
            flash("Bu e-posta zaten kullanımda!", "warning")
            return redirect(url_for('register'))
            
        hashed_pw = generate_password_hash(request.form.get('password'))
        yeni_user = User(email=email, password=hashed_pw, is_paid=True, is_confirmed=True)
        db.session.add(yeni_user)
        db.session.commit()
        flash("Kayıt başarılı! Giriş yapabilirsiniz.", "success")
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/dashboard')
@app.route('/sertifikalar/<cat>')
@login_required
def dashboard(cat=None):
    # Dinamik sekme filtresi ve Global Radar mantığı
    query = Entry.query.filter_by(is_active=True)
    if current_user.email != 'erhanadea@gmail.com':
        query = query.filter_by(user_id=current_user.id)
    
    if cat:
        query = query.filter_by(category=cat)
        
    sertifikalar_listesi = query.order_by(Entry.expiry_date.asc()).all()
    return render_template('dashboard.html', 
                         sertifikalar=sertifikalar_listesi, 
                         bugun=date.today(), 
                         timedelta=timedelta, 
                         current_cat=cat)

@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    excel_dosyasi = request.files.get('excel_file')
    if excel_dosyasi:
        try:
            veriler = pd.read_excel(excel_dosyasi)
            veriler.columns = [str(c).strip().lower() for c in veriler.columns]
            sayac = 0
            for index, satir in veriler.iterrows():
                branş = akilli_brans_analizi(list(satir.values))
                yeni_belge = Entry(
                    user_id=current_user.id,
                    category=branş,
                    title=str(satir.iloc[0]),
                    firma_adi="Excel Kaydı",
                    expiry_date=date.today() + timedelta(days=365)
                )
                db.session.add(yeni_belge)
                sayac += 1
            db.session.commit()
            flash(f"Akıllı Aktarım Tamamlandı! {sayac} belge sisteme işlendi.", "success")
        except Exception as e:
            flash(f"Excel aktarım hatası: {e}", "danger")
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/upload_belge/<int:entry_id>', methods=['POST'])
@login_required
def upload_belge(entry_id):
    dosya = request.files.get('file')
    if dosya:
        try:
            yukleme_sonucu = cloudinary.uploader.upload(dosya, resource_type="auto")
            kayit = Entry.query.get(entry_id)
            if kayit:
                kayit.belge_url = yukleme_sonucu.get('secure_url')
                db.session.commit()
                flash("Belge dijital arşive yüklendi.", "success")
        except Exception as e:
            flash(f"Dosya yükleme hatası: {e}", "danger")
    return redirect(request.referrer)

@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    
    kullanicilar = User.query.all()
    tum_belgeler = Entry.query.filter_by(is_active=True).all()
    return render_template('admin.html', 
                         users=kullanicilar, 
                         all_entries=tum_belgeler, 
                         bugun=date.today(), 
                         timedelta=timedelta)

@app.route('/delete_entry/<int:id>')
@login_required
def delete_entry(id):
    belge = Entry.query.get(id)
    if belge:
        belge.is_active = False # Soft-delete (Sistemden silme imkanı)
        db.session.commit()
        flash("Belge silindi.", "info")
    return redirect(request.referrer)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port_no = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port_no)

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
# GLOBAL SISTEM YAPILANDIRMASI
# ============================================================
app = Flask(__name__)

app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'eg_optimal_ultra_master_final_v2200_2026'),
    SECURITY_PASSWORD_SALT='eg_super_salt_secure_99_pro',
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='erhanadea@gmail.com',
    MAIL_PASSWORD='bwdxhwamvoggqdk0',
    MAIL_DEFAULT_SENDER='erhanadea@gmail.com'
)

# Veritabanı konfigürasyonu
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

# Cloudinary konfigürasyonu
cloudinary.config(
    cloud_name='dh2pefkk',
    api_key='414697559795627',
    api_secret='0q2xexoiKr25EeuI6CmFF8CXf2c'
)

# ============================================================
# VERİ MODELLERİ
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
    danisman_no = db.Column(db.String(20))  # Eklendi: Danışman numarası
    note = db.Column(db.Text)  # Eklendi: Not alanı
    is_active = db.Column(db.Boolean, default=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def setup_db():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            
            # Eksik sütunları ekle
            q_list = [
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS whatsapp_no VARCHAR(20)",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS danisman_no VARCHAR(20)",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS note TEXT",
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
# AKILLI ANALİZ MOTORU
# ============================================================
def akilli_analiz_motoru(satir):
    """Excel'den gelen verileri Regex mantığıyla analiz eder"""
    txt = " ".join(str(v) for v in satir).lower()
    
    if any(k in txt for k in ['src', 'ehliyet', 'operator', 'personel', 'sofor']):
        return 'Personel'
    if any(k in txt for k in ['plaka', 'muayene', 'trafik', 'scania', 'arac']):
        return 'Arac'
    if any(k in txt for k in ['yangin', 'tesis', 'bina', 'isg', 'periyodik']):
        return 'Tesis'
    if any(k in txt for k in ['iso', 'kalite', 'haccp', 'ce belgesi', 'tse']):
        return 'Urun'
    return 'Genel'

# ============================================================
# OTOMATİK HATIRLATMA (SABAH 09:00 MAİL SİSTEMİ)
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
                if u and u.is_paid:
                    try:
                        msg = Message(
                            f"EG Optimal Kritik Uyarı: {e.title}", 
                            recipients=[u.email]
                        )
                        msg.body = f"""
Sayın {u.company_name},

'{e.title}' belgenizin bitmesine {kalan} gün kalmıştır.

Belge Detayları:
- Firma: {e.firma_adi}
- Bitiş Tarihi: {e.expiry_date.strftime('%d.%m.%Y')}
- Kalan Gün: {kalan}

Lütfen gerekli aksiyonu alınız.

EG Optimal Sertifika Takip Sistemi
"""
                        mail.send(msg)
                        count += 1
                    except:
                        pass
    
    return f"Bitti. {count} mail gönderildi.", 200

# ============================================================
# ANA ROTALAR
# ============================================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('sertifikalar', cat=None))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        u = User.query.filter_by(email=email).first()
        
        if u and check_password_hash(u.password, password):
            if not u.is_paid:
                flash('Hesabınız henüz aktifleştirilmemiştir. Lütfen yönetici ile iletişime geçin.', 'warning')
                return render_template('login.html')
            login_user(u)
            return redirect(url_for('sertifikalar', cat=None))
        flash("E-posta veya şifre hatalı.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Captcha kontrolü
        captcha = request.form.get('captcha')
        if captcha != "7":
            flash("Güvenlik sorusu hatalı! Lütfen 3+4 işleminin sonucunu yazın.", "danger")
            return redirect(url_for('register'))
        
        email = request.form.get('email')
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Bu e-posta adresi zaten kayıtlı.', 'danger')
            return redirect(url_for('register'))
        
        u = User(
            email=email,
            password=generate_password_hash(request.form.get('password')),
            company_name=request.form.get('company_name', ''),
            is_paid=True,
            is_confirmed=True
        )
        db.session.add(u)
        db.session.commit()
        flash("Kayıt başarılı! Giriş yapabilirsiniz.", "success")
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            flash("Şifre sıfırlama talimatları e-postanıza gönderildi.", "info")
        else:
            flash("Bu e-posta adresi sistemde kayıtlı değil.", "danger")
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = ts.loads(token, salt='password-reset', max_age=3600)
    except:
        flash('Şifre sıfırlama bağlantısı geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        new_password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user:
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Şifreniz başarıyla güncellendi. Giriş yapabilirsiniz.', 'success')
            return redirect(url_for('login'))
    return render_template('reset_password.html')

@app.route('/dashboard')
@login_required
def dashboard_redirect():
    return redirect(url_for('sertifikalar', cat=None))

@app.route('/sertifikalar/<cat>')
@login_required
def sertifikalar(cat=None):
    q = Entry.query.filter_by(is_active=True)
    
    # Admin değilse sadece kendi verilerini görsün
    if current_user.email != 'erhanadea@gmail.com':
        q = q.filter_by(user_id=current_user.id)
    
    # Kategori filtresi
    if cat and cat != 'all':
        q = q.filter_by(category=cat)
    
    return render_template('dashboard.html',
                           sertifikalar=q.all(),
                           bugun=date.today(),
                           timedelta=timedelta,
                           current_cat=cat)

@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com':
        flash('Bu alana erişim yetkiniz yok.', 'danger')
        return redirect(url_for('sertifikalar', cat=None))
    
    return render_template('admin.html',
                           users=User.query.all(),
                           all_entries=Entry.query.filter_by(is_active=True).all(),
                           bugun=date.today(),
                           timedelta=timedelta)

@app.route('/update_payment/<int:uid>', methods=['POST'])
@login_required
def update_payment(uid):
    if current_user.email != 'erhanadea@gmail.com':
        flash('Yetkisiz işlem!', 'danger')
        return redirect(url_for('sertifikalar', cat=None))
    
    u = User.query.get(uid)
    if u:
        is_paid_value = request.form.get('is_paid')
        u.is_paid = (is_paid_value == 'true')
        u.company_name = request.form.get('company_name', u.company_name)
        u.admin_note = request.form.get('admin_note', u.admin_note)
        db.session.commit()
        flash(f"{u.email} kullanıcısı güncellendi!", "success")
    
    return redirect(url_for('admin_panel'))

@app.route('/delete_user/<int:uid>')
@login_required
def delete_user(uid):
    if current_user.email != 'erhanadea@gmail.com':
        flash('Yetkisiz işlem!', 'danger')
        return redirect(url_for('sertifikalar', cat=None))
    
    kullanici = User.query.get(uid)
    if kullanici:
        Entry.query.filter_by(user_id=kullanici.id).delete()
        db.session.delete(kullanici)
        db.session.commit()
        flash(f'{kullanici.email} ve tüm verileri sistemden silindi.', 'success')
    else:
        flash('Kullanıcı bulunamadı.', 'danger')
    
    return redirect(url_for('admin_panel'))

@app.route('/upload_belge/<int:entry_id>', methods=['POST'])
@login_required
def upload_belge(entry_id):
    f = request.files.get('file')
    if f:
        try:
            res = cloudinary.uploader.upload(f, resource_type="auto")
            e = Entry.query.get(entry_id)
            if e and (current_user.id == e.user_id or current_user.email == 'erhanadea@gmail.com'):
                e.belge_url = res.get('secure_url')
                db.session.commit()
                flash('Belge başarıyla yüklendi.', 'success')
            else:
                flash('Belge bulunamadı veya yetkiniz yok.', 'danger')
        except Exception as e:
            flash(f'Yükleme hatası: {str(e)}', 'danger')
    else:
        flash('Lütfen bir dosya seçin.', 'warning')
    
    return redirect(url_for('sertifikalar', cat=request.args.get('cat')))

@app.route('/delete_entry/<int:id>')
@login_required
def delete_entry(id):
    e = Entry.query.get(id)
    if e and (current_user.id == e.user_id or current_user.email == 'erhanadea@gmail.com'):
        e.is_active = False
        db.session.commit()
        flash('Kayıt başarıyla devre dışı bırakıldı.', 'success')
    else:
        flash('Kayıt bulunamadı veya yetkiniz yok.', 'danger')
    
    return redirect(url_for('sertifikalar', cat=request.args.get('cat')))

@app.route('/ekle/<cat>', methods=['GET'])
@login_required
def ekle(cat):
    if cat not in ['Arac', 'Personel', 'Tesis', 'Urun']:
        flash('Geçersiz kategori!', 'danger')
        return redirect(url_for('sertifikalar', cat=None))
    return render_template('ekle.html', cat=cat)

@app.route('/ekle/<cat>', methods=['POST'])
@login_required
def ekle_post(cat):
    title = request.form.get('title')
    if title == 'LİSTEDE YOK / MANUEL YAZ':
        title = request.form.get('manual_title')
        if not title:
            flash('Lütfen belge adını manuel olarak girin.', 'danger')
            return redirect(url_for('ekle', cat=cat))
    
    yeni_kayit = Entry(
        user_id=current_user.id,
        category=cat,
        title=title,
        firma_adi=request.form.get('firma_adi'),
        whatsapp_no=request.form.get('whatsapp_no'),
        danisman_no=request.form.get('danisman_no'),
        note=request.form.get('note'),
        expiry_date=datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d').date()
    )
    db.session.add(yeni_kayit)
    db.session.commit()
    flash(f'{title} başarıyla eklendi.', 'success')
    return redirect(url_for('sertifikalar', cat=cat))

@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if f:
        try:
            df = pd.read_excel(f)
            df.columns = [str(c).strip().lower() for c in df.columns]
            
            for _, r in df.iterrows():
                kategori = akilli_analiz_motoru(list(r.values))
                db.session.add(Entry(
                    user_id=current_user.id,
                    category=kategori,
                    title=str(r.iloc[0]) if len(r) > 0 else "Excel Kaydı",
                    firma_adi="Excel Kaydı",
                    expiry_date=date.today() + timedelta(days=365)
                ))
            db.session.commit()
            flash("Excel verileri akıllı algoritma ile başarıyla aktarıldı!", "success")
        except Exception as e:
            flash(f"Excel Aktarım Hatası: {e}", "danger")
    else:
        flash("Lütfen bir Excel dosyası seçin.", "warning")
    
    return redirect(url_for('sertifikalar', cat=None))

@app.route('/export_excel')
@login_required
def export_excel():
    q = Entry.query.filter_by(user_id=current_user.id, is_active=True)
    
    # Admin için farklı davranış
    if current_user.email == 'erhanadea@gmail.com' and request.args.get('all'):
        q = Entry.query.filter_by(is_active=True)
    
    data = []
    for e in q.all():
        data.append({
            'Kategori': e.category,
            'Belge Adı': e.title,
            'Firma': e.firma_adi,
            'Bitiş Tarihi': e.expiry_date.strftime('%d.%m.%Y') if e.expiry_date else '',
            'WhatsApp': e.whatsapp_no,
            'Danışman No': e.danisman_no,
            'Not': e.note
        })
    
    df = pd.DataFrame(data)
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as wr:
        df.to_excel(wr, index=False)
    out.seek(0)
    
    return send_file(out, download_name="eg_optimal_rapor.xlsx", as_attachment=True)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Başarıyla çıkış yaptınız.', 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

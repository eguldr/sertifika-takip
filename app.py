import os
import re
import cloudinary
import cloudinary.uploader
import pandas as pd
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
from io import BytesIO
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# ============================================================
# GLOBAL SISTEM YAPILANDIRMASI
# ============================================================
app = Flask(__name__)

app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'gizli-anahtar-123456'),
    SECURITY_PASSWORD_SALT=os.environ.get('SECURITY_PASSWORD_SALT', 'eg_super_salt_secure_99_pro'),
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME=os.environ.get('MAIL_USERNAME', 'erhanadea@gmail.com'),
    MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD', 'bwdxhwamvoggqdk0'),
    MAIL_DEFAULT_SENDER=os.environ.get('MAIL_USERNAME', 'erhanadea@gmail.com')
)

# Veritabanı konfigürasyonu - PostgreSQL için düzeltme
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

# Cloudinary konfigürasyonu - Render env'den al
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'dh2pefkk'),
    api_key=os.environ.get('CLOUDINARY_API_KEY', '414697559795627'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', '0q2xexoiKr25EeuI6CmFF8CXf2c')
)

# reCAPTCHA anahtarları
RECAPTCHA_SITE_KEY = os.environ.get('RECAPTCHA_SITE_KEY', '6Leewb8sAAAAAG-f0E4VY7aYZ1T-S_1H21ckRpsO')
RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY', '6Leewb8sAAAAA0tdMrBprUj0T8uy3VwjOY0jT0-j')

# ============================================================
# VERİ MODELLERİ
# ============================================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    company_name = db.Column(db.String(100), default='')
    is_confirmed = db.Column(db.Boolean, default=False)
    is_paid = db.Column(db.Boolean, default=False)
    admin_note = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50))
    title = db.Column(db.String(100))
    firma_adi = db.Column(db.String(100))
    expiry_date = db.Column(db.Date)
    belge_url = db.Column(db.String(500))
    whatsapp_no = db.Column(db.String(20))
    danisman_no = db.Column(db.String(20))
    note = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.before_request
def setup_db():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            app._db_init = True


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================
def verify_recaptcha(recaptcha_response):
    """Google reCAPTCHA doğrulaması yapar"""
    data = {
        'secret': RECAPTCHA_SECRET_KEY,
        'response': recaptcha_response
    }
    try:
        r = requests.post('https://www.google.com/recaptcha/api/siteverify', data=data)
        result = r.json()
        return result.get('success', False)
    except:
        return False


def akilli_analiz_motoru(satir):
    txt = " ".join(str(v) for v in satir).lower()
    
    if any(k in txt for k in ['src', 'ehliyet', 'operator', 'personel', 'sofor', 'sürücü', 'psikoteknik']):
        return 'Personel'
    if any(k in txt for k in ['plaka', 'muayene', 'trafik', 'scania', 'arac', 'araç', 'filo', 'kasko', 'sigorta']):
        return 'Arac'
    if any(k in txt for k in ['yangin', 'tesis', 'bina', 'isg', 'periyodik', 'mekan', 'fabrika', 'itfaiye', 'kapasite']):
        return 'Tesis'
    return 'Urun'


def send_confirmation_email(user_email, token):
    confirm_url = url_for('confirm_email', token=token, _external=True)
    msg = Message("EG Optimal - Email Doğrulama", recipients=[user_email])
    msg.body = f"""
EG Optimal Sertifika Takip Sistemi'ne hoş geldiniz!

Email adresinizi doğrulamak için aşağıdaki bağlantıya tıklayın:
{confirm_url}

Bu bağlantı 24 saat geçerlidir.

Doğrulama tamamlandıktan sonra yönetici onayı bekleyeceksiniz.

EG Optimal Ekibi
"""
    mail.send(msg)


# ============================================================
# OTOMATİK HATIRLATMA
# ============================================================
@app.route('/cron/9am_check')
def morning_check():
    bugun = date.today()
    liste = Entry.query.filter_by(is_active=True).all()
    count = 0
    
    for e in liste:
        if e.expiry_date:
            kalan = (e.expiry_date - bugun).days
            if kalan in [30, 15, 7, 1, 0]:
                u = User.query.get(e.user_id)
                if u and u.is_paid and u.is_confirmed:
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
                    except Exception as ex:
                        print(f"Mail gönderilemedi: {ex}")
    
    return f"Bitti. {count} mail gönderildi.", 200


# ============================================================
# ANA ROTALAR
# ============================================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('sertifikalar', cat='all'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        u = User.query.filter_by(email=email).first()
        
        if u and check_password_hash(u.password, password):
            if not u.is_confirmed:
                flash('Lütfen önce email adresinizi doğrulayın. Spam klasörünü kontrol edin.', 'warning')
                return render_template('login.html')
            if not u.is_paid:
                flash('Hesabınız henüz aktifleştirilmemiştir. Lütfen yönetici ile iletişime geçin.', 'warning')
                return render_template('login.html')
            login_user(u)
            return redirect(url_for('sertifikalar', cat='all'))
        flash("E-posta veya şifre hatalı.", "danger")
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # reCAPTCHA doğrulaması
        recaptcha_response = request.form.get('g-recaptcha-response')
        if not verify_recaptcha(recaptcha_response):
            flash('reCAPTCHA doğrulaması başarısız! Lütfen tekrar deneyin.', 'danger')
            return redirect(url_for('register'))
        
        email = request.form.get('email')
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Bu e-posta adresi zaten kayıtlı.', 'danger')
            return redirect(url_for('register'))
        
        password = request.form.get('password')
        if len(password) < 6:
            flash('Şifre en az 6 karakter olmalıdır.', 'danger')
            return redirect(url_for('register'))
        
        u = User(
            email=email,
            password=generate_password_hash(password),
            company_name=request.form.get('company_name', ''),
            is_paid=False,
            is_confirmed=False
        )
        db.session.add(u)
        db.session.commit()
        
        token = ts.dumps(email, salt='email-confirm')
        send_confirmation_email(email, token)
        
        flash("Kayıt başarılı! Lütfen email adresinizi doğrulayın. (Spam klasörünü kontrol edin)", "success")
        return redirect(url_for('login'))
    
    return render_template('kayit.html', site_key=RECAPTCHA_SITE_KEY)


@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = ts.loads(token, salt='email-confirm', max_age=86400)
    except:
        flash('Doğrulama bağlantısı geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('login'))
    
    user = User.query.filter_by(email=email).first()
    if user:
        user.is_confirmed = True
        db.session.commit()
        flash('Email adresiniz başarıyla doğrulandı! Yönetici onayı bekleniyor.', 'success')
    else:
        flash('Kullanıcı bulunamadı.', 'danger')
    
    return redirect(url_for('login'))


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            token = ts.dumps(email, salt='password-reset')
            reset_url = url_for('reset_password', token=token, _external=True)
            msg = Message("EG Optimal - Şifre Sıfırlama", recipients=[email])
            msg.body = f"""
Şifrenizi sıfırlamak için aşağıdaki bağlantıya tıklayın:
{reset_url}

Bu bağlantı 1 saat geçerlidir.

Eğer bu işlemi siz yapmadıysanız, bu maili dikkate almayın.
"""
            mail.send(msg)
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
        if len(new_password) < 6:
            flash('Şifre en az 6 karakter olmalıdır.', 'danger')
            return redirect(url_for('reset_password', token=token))
        
        user = User.query.filter_by(email=email).first()
        if user:
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Şifreniz başarıyla güncellendi. Giriş yapabilirsiniz.', 'success')
            return redirect(url_for('login'))
    return render_template('reset_password.html')


@app.route('/sertifikalar/<cat>')
@login_required
def sertifikalar(cat='all'):
    q = Entry.query.filter_by(is_active=True)
    
    if current_user.email != 'erhanadea@gmail.com':
        q = q.filter_by(user_id=current_user.id)
    
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
        return redirect(url_for('sertifikalar', cat='all'))
    
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
        return redirect(url_for('sertifikalar', cat='all'))
    
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
        return redirect(url_for('sertifikalar', cat='all'))
    
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
    cat = request.args.get('cat', 'all')
    
    if f and f.filename:
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
    
    return redirect(url_for('sertifikalar', cat=cat))


@app.route('/delete_entry/<int:id>')
@login_required
def delete_entry(id):
    cat = request.args.get('cat', 'all')
    e = Entry.query.get(id)
    
    if e and (current_user.id == e.user_id or current_user.email == 'erhanadea@gmail.com'):
        e.is_active = False
        db.session.commit()
        flash('Kayıt başarıyla devre dışı bırakıldı.', 'success')
    else:
        flash('Kayıt bulunamadı veya yetkiniz yok.', 'danger')
    
    return redirect(url_for('sertifikalar', cat=cat))


@app.route('/ekle/<cat>', methods=['GET'])
@login_required
def ekle(cat):
    if cat not in ['Arac', 'Personel', 'Tesis', 'Urun']:
        flash('Geçersiz kategori!', 'danger')
        return redirect(url_for('sertifikalar', cat='all'))
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
    
    expiry_date_str = request.form.get('expiry_date')
    if not expiry_date_str:
        flash('Lütfen bitiş tarihini girin.', 'danger')
        return redirect(url_for('ekle', cat=cat))
    
    yeni_kayit = Entry(
        user_id=current_user.id,
        category=cat,
        title=title,
        firma_adi=request.form.get('firma_adi', ''),
        whatsapp_no=request.form.get('whatsapp_no', ''),
        danisman_no=request.form.get('danisman_no', ''),
        note=request.form.get('note', ''),
        expiry_date=datetime.strptime(expiry_date_str, '%Y-%m-%d').date()
    )
    db.session.add(yeni_kayit)
    db.session.commit()
    flash(f'{title} başarıyla eklendi.', 'success')
    return redirect(url_for('sertifikalar', cat=cat))


@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if f and f.filename:
        try:
            df = pd.read_excel(f)
            
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
    
    return redirect(url_for('sertifikalar', cat='all'))


@app.route('/export_excel')
@login_required
def export_excel():
    q = Entry.query.filter_by(user_id=current_user.id, is_active=True)
    
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

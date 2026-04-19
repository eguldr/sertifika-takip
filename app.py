import os
import requests
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta, date

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer

# ============================================================
# UYGULAMA KURULUMU
# ============================================================
app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gizli-anahtar-123456')

# Veritabanı
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Mail Ayarları
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'erhanadea@gmail.com'
app.config['MAIL_PASSWORD'] = 'awdxhwawnvoggdko'
app.config['MAIL_DEFAULT_SENDER'] = 'erhanadea@gmail.com'

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])


# ============================================================
# VERİTABANI MODELLERİ
# ============================================================
class User(UserMixin, db.Model):
    __tablename__ = 'kullanici_tablosu'
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(100), unique=True)
    password     = db.Column(db.String(256))
    company_name = db.Column(db.String(100))
    is_admin     = db.Column(db.Boolean, default=False)
    is_confirmed = db.Column(db.Boolean, default=False)


class Entry(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer)
    category    = db.Column(db.String(50))
    title       = db.Column(db.String(100))
    firma_adi   = db.Column(db.String(100))
    whatsapp_no = db.Column(db.String(20))
    expiry_date = db.Column(db.Date)
    risk_value  = db.Column(db.String(100))


class HatirlatmaLog(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    entry_id  = db.Column(db.Integer)
    firma_adi = db.Column(db.String(100))
    belge_adi = db.Column(db.String(100))
    tarih     = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.before_request
def setup_database():
    if not hasattr(app, 'db_initialized'):
        with app.app_context():
            db.create_all()
        app.db_initialized = True


# ============================================================
# OTOMATİK HATIRLATMA SİSTEMİ (6-3-1 AY)
# ============================================================
@app.route('/cron/check_reminders')
def cron_check_reminders():
    """
    Bu yol (route) her gün bir kez tetiklendiğinde 
    vadesi yaklaşan sertifikalar için otomatik mail atar.
    """
    with app.app_context():
        bugun = date.today()
        tum_kayitlar = Entry.query.all()
        gonderilen_sayisi = 0
        
        for e in tum_kayitlar:
            if not e.expiry_date:
                continue
                
            kalan_gun = (e.expiry_date - bugun).days
            
            # 180 Gün (6 Ay), 90 Gün (3 Ay), 30 Gün (1 Ay)
            if kalan_gun in [180, 90, 30]:
                user = User.query.get(e.user_id)
                if user:
                    vade_adi = {180: "6 Ay", 90: "3 Ay", 30: "1 Ay"}[kalan_gun]
                    
                    try:
                        msg = Message(
                            f"⚠️ EG Optimal Hatırlatma: {e.title} ({vade_adi})",
                            recipients=[user.email]
                        )
                        msg.body = f"""Sayın Kullanıcımız,

EG Optimal Danışmanlık Takip Sistemindeki kaydınıza göre;
'{e.title}' isimli belgenizin bitmesine tam {vade_adi} kalmıştır.

Belge Bilgileri:
- Firma: {e.firma_adi}
- Bitiş Tarihi: {e.expiry_date.strftime('%d.%m.%Y')}

Lütfen yenileme süreçleri için hazırlık yapınız.

İyi çalışmalar,
EG Optimal Danışmanlık
"""
                        mail.send(msg)
                        
                        # Log kaydı ekle
                        yeni_log = HatirlatmaLog(
                            entry_id=e.id,
                            firma_adi=e.firma_adi,
                            belge_adi=e.title
                        )
                        db.session.add(yeni_log)
                        gonderilen_sayisi += 1
                    except Exception as ex:
                        print(f"Hatırlatma maili hatası: {ex}")

        db.session.commit()
        return f"İşlem Tamamlandı. {gonderilen_sayisi} adet hatırlatma gönderildi.", 200


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================
def send_confirmation_email(user_email, cert_name, expiry_date):
    try:
        msg = Message(
            "EG Optimal - Sertifika Takip Onayı",
            recipients=[user_email]
        )
        msg.body = f"""Merhaba,

'{cert_name}' isimli belgeniz sisteme başarıyla kaydedilmiştir.
Bitiş Tarihi: {expiry_date}

Süre dolmasına 6 ay, 3 ay ve 30 gün kala size otomatik hatırlatma yapılacaktır.

İyi çalışmalar,
EG Optimal Dijital Takip Sistemi
"""
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Mail hatası: {e}")
        return False


def send_verification_email(user_email):
    try:
        token = ts.dumps(user_email, salt='email-confirm')
        confirm_url = url_for('confirm_email', token=token, _external=True)

        msg = Message(
            "EG Optimal - Hesabınızı Onaylayın 🛡️",
            recipients=[user_email]
        )
        msg.body = f"""Merhaba,

EG Optimal Sertifika Takip Sistemine kayıt olduğunuz için teşekkürler.
Hesabınızı aktifleştirmek için lütfen aşağıdaki linke tıklayın:

{confirm_url}

Bu link 24 saat boyunca geçerlidir.
"""
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Doğrulama maili hatası: {e}")
        return False


def verify_recaptcha(response_token):
    secret = os.environ.get('RECAPTCHA_SECRET_KEY')
    if not secret: return True # Geliştirme aşaması için
    result = requests.post(
        'https://www.google.com/recaptcha/api/siteverify',
        data={'secret': secret, 'response': response_token}
    ).json()
    return result.get('success', False)


# ============================================================
# ROTALAR
# ============================================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/kayit', methods=['GET', 'POST'])
def kayit():
    if request.method == 'POST':
        if not verify_recaptcha(request.form.get('g-recaptcha-response', '')):
            flash("Lütfen robot olmadığınızı doğrulayın!", "danger")
            return redirect(url_for('kayit'))

        email        = request.form.get('email', '').strip()
        password     = request.form.get('password', '')
        company_name = request.form.get('company_name', '').strip()

        if User.query.filter_by(email=email).first():
            flash('Bu e-posta adresi zaten kayıtlı!', 'warning')
            return redirect(url_for('kayit'))

        new_user = User(
            email=email,
            password=generate_password_hash(password),
            company_name=company_name,
            is_admin=False,
            is_confirmed=False
        )
        db.session.add(new_user)
        db.session.commit()

        send_verification_email(email)
        flash('Kayıt başarılı! Lütfen e-postanızı onaylayın.', 'success')
        return redirect(url_for('login'))

    return render_template(
        'kayit.html',
        recaptcha_site_key=os.environ.get('RECAPTCHA_SITE_KEY', '')
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            user.is_admin = (user.email == 'erhanadea@gmail.com')
            db.session.commit()
            login_user(user)
            return redirect(url_for('dashboard'))

        flash('E-posta veya şifre hatalı!', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = ts.loads(token, salt='email-confirm', max_age=86400)
    except Exception:
        flash('Onay linki geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first_or_404()
    if user.is_confirmed:
        flash('Hesabınız zaten onaylanmış.', 'info')
    else:
        user.is_confirmed = True
        db.session.commit()
        flash('Hesabınız başarıyla onaylandı! Giriş yapabilirsiniz.', 'success')
    return redirect(url_for('login'))


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user  = User.query.filter_by(email=email).first()
        if user:
            token       = ts.dumps(email, salt='recover-key')
            recover_url = url_for('reset_password', token=token, _external=True)
            msg = Message(
                "Şifre Sıfırlama Talebi - Sertifika Takip",
                recipients=[email]
            )
            msg.body = (
                f"Şifrenizi sıfırlamak için şu bağlantıya tıklayın:\n\n"
                f"{recover_url}\n\nBu bağlantı 30 dakika geçerlidir."
            )
            mail.send(msg)
        flash('E-posta adresiniz kayıtlıysa şifre sıfırlama bağlantısı gönderilecektir.', 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = ts.loads(token, salt='recover-key', max_age=1800)
    except Exception:
        flash('Şifre sıfırlama bağlantısı geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        user     = User.query.filter_by(email=email).first()
        if user:
            user.password = generate_password_hash(password)
            db.session.commit()
            flash('Şifreniz başarıyla güncellendi. Giriş yapabilirsiniz.', 'success')
            return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)


@app.route('/dashboard')
@login_required
def dashboard():
    bugun  = date.today()
    tum_kayitlar = Entry.query.filter_by(user_id=current_user.id).all()

    # İstatistikler
    urun  = Entry.query.filter_by(user_id=current_user.id, category='Urun').count()
    arac  = Entry.query.filter_by(user_id=current_user.id, category='Arac').count()
    pers  = Entry.query.filter_by(user_id=current_user.id, category='Personel').count()
    tesis = Entry.query.filter_by(user_id=current_user.id, category='Tesis').count()

    kat_isim = {
        'Urun':     'Üretim & Ürün',
        'Arac':     'Araç & Filo',
        'Personel': 'Personel & SRC',
        'Tesis':    'Tesis & Mekan'
    }

   return render_template(
        'dashboard.html',
        user=current_user,
        urun=urun, arac=arac, pers=pers, tesis=tesis,
        sertifikalar=tum_kayitlar,
        kat_isim=kat_isim,
        timedelta=timedelta,
        bugun=bugun
    )


@app.route('/sertifikalar')
@login_required
def sertifikalar():
    cat   = request.args.get('cat')
    bugun = date.today()
    items = Entry.query.filter_by(user_id=current_user.id, category=cat).all()

    return render_template('sertifikalar.html', items=items, bugun=bugun, cat=cat)


@app.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    if request.method == 'POST':
        exp_str     = request.form.get('expiry_date')
        category    = request.form.get('category')
        title       = request.form.get('title')
        expiry_date = datetime.strptime(exp_str, '%Y-%m-%d').date() if exp_str else None

        new_entry = Entry(
            user_id     = current_user.id,
            category    = category,
            title       = title,
            firma_adi   = request.form.get('firma_adi', ''),
            whatsapp_no = request.form.get('whatsapp_no', ''),
            risk_value  = request.form.get('risk_value', ''),
            expiry_date = expiry_date
        )
        db.session.add(new_entry)
        db.session.commit()
        send_confirmation_email(current_user.email, title, expiry_date)
        return redirect(url_for('sertifikalar', cat=new_entry.category))

    return render_template('ekle.html')


@app.route('/sil/<int:id>')
@login_required
def sil(id):
    item = Entry.query.get(id)
    if item and item.user_id == current_user.id:
        cat = item.category
        db.session.delete(item)
        db.session.commit()
        return redirect(url_for('sertifikalar', cat=cat))
    return redirect(url_for('dashboard'))


@app.route('/export')
@login_required
def export_excel():
    entries = Entry.query.filter_by(user_id=current_user.id).all()
    data = [
        {
            "Firma Adı":    e.firma_adi,
            "Belge Adı":    e.title,
            "Plaka/TC/Not": e.risk_value,
            "WhatsApp":     e.whatsapp_no,
            "Bitiş Tarihi": e.expiry_date.strftime('%d.%m.%Y') if e.expiry_date else ""
        }
        for e in entries
    ]
    df     = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sertifikalar')
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="EG_Optimal_Rapor.xlsx"
    )


@app.route('/admin_panel')
@login_required
def admin_panel():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    logs  = HatirlatmaLog.query.order_by(HatirlatmaLog.tarih.desc()).limit(50).all()
    users = User.query.all()
    return render_template('admin.html', logs=logs, users=users)


if __name__ == '__main__':
    app.run()

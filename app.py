import requests
import os
import pandas as pd
from io import BytesIO
from flask import send_file
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta, date
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'erhan-gizli-anahtar-99')
from itsdangerous import URLSafeTimedSerializer
ts = URLSafeTimedSerializer(app.secret_key)
# Mail Sunucusu Ayarları
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'erhanadea@gmail.com'
app.config['MAIL_PASSWORD'] = 'awdxhwawnvoggdko'
app.config['MAIL_DEFAULT_SENDER'] = 'erhanadea@gmail.com'

mail = Mail(app)
def send_confirmation_email(user_email, cert_name, expiry_date):
    try:
        msg = Message("EG Optimal - Sertifika Takip Onayı",
                      recipients=[user_email])
        msg.body = f"""
Merhaba,

'{cert_name}' isimli belgeniz sisteme başarıyla kaydedilmiştir.
Bitiş Tarihi: {expiry_date}

Süre dolmasına 30 gün kala size tekrar hatırlatma yapılacaktır.

İyi çalışmalar,
EG Optimal Dijital Takip Sistemi
        """
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Mail hatası: {e}")
        return False
def send_verification_email(user_email):
    token = ts.dumps(user_email, salt='email-confirm')
    confirm_url = url_for('confirm_email', token=token, _external=True)
    
    msg = Message("EG Optimal - Hesabınızı Onaylayın 🛡️", recipients=[user_email])
    msg.body = f"""
Merhaba,

EG Optimal Sertifika Takip Sistemine kayıt olduğunuz için teşekkürler.
Hesabınızı aktifleştirmek için lütfen aşağıdaki linke tıklayın:

{confirm_url}

Bu link 24 saat boyunca geçerlidir.
    """
    mail.send(msg)
    try:
        msg = Message("EG Optimal'e Hoş Geldiniz! 🚀",
                      recipients=[user_email])
        msg.body = f"""
Merhaba,

EG Optimal Sertifika & Risk Takip sistemine başarıyla kayıt oldunuz. 

Artık belgelerinizin süresini unutma derdine son! Sisteme giriş yaparak hemen ilk sertifikanızı ekleyebilir ve otomatik bildirimleri aktif edebilirsiniz.

Keyifli kullanımlar dileriz.

Saygılarımızla,
EG Optimal Ekibi
        """
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Hoşgeldin maili hatası: {e}")
        return False


app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gizli-anahtar-123456')

uri = os.environ.get('DATABASE_URL')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

# Eğer DATABASE_URL gelmezse çökmemesi için:
app.config['SQLALCHEMY_DATABASE_URI'] = uri or 'sqlite:///test.db'

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)


class User(UserMixin, db.Model):
    __tablename__ = 'kullanici_tablosu'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(256))
    company_name = db.Column(db.String(100))
    is_admin = db.Column(db.Boolean, default=False)
    is_confirmed = db.Column(db.Boolean, default=False)


class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    category = db.Column(db.String(50))
    title = db.Column(db.String(100))
    firma_adi = db.Column(db.String(100))
    whatsapp_no = db.Column(db.String(20))
    expiry_date = db.Column(db.Date)
    risk_value = db.Column(db.String(100))


class HatirlatmaLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer)
    firma_adi = db.Column(db.String(100))
    belge_adi = db.Column(db.String(100))
    tarih = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.before_request
def setup_database():
    # Bu kontrol sayesinde sadece bir kez çalışır, her sayfada sıfırlamaz
    if not hasattr(app, 'db_initialized'):
        with app.app_context():
            db.create_all() # Yenileri kurar (is_confirmed dahil)
        app.db_initialized = True

@app.route('/export')
@login_required
def export_excel():
    entries = Entry.query.all()
    data = []
    for e in entries:
        data.append({
            "Firma Adı": e.firma_adi,
            "Belge Adı": e.title,
            "Plaka/TC/Not": e.risk_value,
            "WhatsApp": e.whatsapp_no,
            "Bitiş Tarihi": e.expiry_date.strftime('%d.%m.%Y') if e.expiry_date else ""
        })
    
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sertifikalar')
    
    output.seek(0)
    return send_file(output, 
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, 
                     download_name="EG_Optimal_Rapor.xlsx")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            if user.email == 'erhanadea@gmail.com':
                user.is_admin = True
            else:
                user.is_admin = False
            
            db.session.commit()
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('E-posta veya şifre hatalı!')
    return render_template('login.html')


@app.route('/kayit', methods=['GET', 'POST'])
def kayit():
    if request.method == 'POST':
        # reCAPTCHA Doğrulama
        recaptcha_response = request.form.get('g-recaptcha-response')
        verify_response = requests.post(
            'https://www.google.com/recaptcha/api/siteverify',
            data={
                'secret': '6LdXpb8sAAAAAF9M42YWYdQStV9o-1DjOB2AeELk',
                'response': recaptcha_response
            }
        ).json()

        if not verify_response.get('success'):
            flash("Lütfen robot olmadığınızı doğrulayın!", "danger")
            return redirect(url_for('kayit'))
        email = request.form.get('email')
        password = request.form.get('password')
        company_name = request.form.get('company_name')
        if User.query.filter_by(email=email).first():
            flash('Bu e-posta zaten kayıtlı!')
            return redirect(url_for('kayit'))
        new_user = User(
            email=email,
            password=generate_password_hash(password),
            company_name=company_name,
            is_admin=True
        )
        db.session.add(new_user)
        db.session.commit()
        send_verification_email(email)
        return redirect(url_for('login'))
    return render_template('kayit.html')


@app.route('/dashboard')
@login_required
def dashboard():
    bugun = date.today()
    gun_30 = bugun + timedelta(days=30)
    gun_60 = bugun + timedelta(days=60)
    gun_90 = bugun + timedelta(days=90)

    tum_kayitlar = Entry.query.filter_by(user_id=current_user.id).all()

    urun  = Entry.query.filter_by(user_id=current_user.id, category='Urun').count()
    arac  = Entry.query.filter_by(user_id=current_user.id, category='Arac').count()
    pers  = Entry.query.filter_by(user_id=current_user.id, category='Personel').count()
    tesis = Entry.query.filter_by(user_id=current_user.id, category='Tesis').count()

    suresi_dolan = [e for e in tum_kayitlar if e.expiry_date and e.expiry_date < bugun]
    kritik_30    = [e for e in tum_kayitlar if e.expiry_date and bugun <= e.expiry_date <= gun_30]
    uyari_60     = [e for e in tum_kayitlar if e.expiry_date and gun_30 < e.expiry_date <= gun_60]
    bilgi_90     = [e for e in tum_kayitlar if e.expiry_date and gun_60 < e.expiry_date <= gun_90]

    kat_isim = {
        'Urun': 'Üretim & Ürün',
        'Arac': 'Araç & Filo',
        'Personel': 'Personel & SRC',
        'Tesis': 'Tesis & Mekan'
    }

    return render_template('dashboard.html',
        user=current_user,
        urun=urun, arac=arac, pers=pers, tesis=tesis,
        suresi_dolan=suresi_dolan,
        kritik_30=kritik_30,
        uyari_60=uyari_60,
        bilgi_90=bilgi_90,
        kat_isim=kat_isim,
        bugun=bugun
    )


@app.route('/sertifikalar')
@login_required
def sertifikalar():
    cat = request.args.get('cat')
    bugun = date.today()
    items = Entry.query.filter_by(user_id=current_user.id, category=cat).all()
    for item in items:
        if item.expiry_date:
            item.kalan_gun = (item.expiry_date - bugun).days
            if item.kalan_gun < 0:
                item.durum = 'danger'
            elif item.kalan_gun <= 30:
                item.durum = 'danger'
            elif item.kalan_gun <= 60:
                item.durum = 'warning'
            else:
                item.durum = 'success'
        else:
            item.kalan_gun = None
            item.durum = 'secondary'
    return render_template('sertifikalar.html', items=items, bugun=bugun, cat=cat)


@app.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    if request.method == 'POST':
        exp_str = request.form.get('expiry_date')
        # ŞU ÜÇ SATIRI BURAYA EKLE:
        category = request.form.get('category')
        title = request.form.get('title')
        expiry_date = datetime.strptime(exp_str, '%Y-%m-%d').date() if exp_str else None

        new_entry = Entry(
            user_id=current_user.id,
            category=category,
            title=title,
            firma_adi=request.form.get('firma_adi', ''),
            whatsapp_no=request.form.get('whatsapp_no', ''),
            risk_value=request.form.get('risk_value', ''),
            expiry_date=expiry_date
        )
        db.session.add(new_entry)
        db.session.commit()
        # Kayıt başarılı, şimdi mail gönder:
        send_confirmation_email(current_user.email, title, expiry_date)
        
        return redirect(url_for('sertifikalar', cat=new_entry.category))
    return render_template('ekle.html')


@app.route('/log_ekle/<int:id>')
@login_required
def log_ekle(id):
    item = Entry.query.get(id)
    if item:
        yeni_log = HatirlatmaLog(
            entry_id=item.id,
            firma_adi=item.firma_adi,
            belge_adi=item.title
        )
        db.session.add(yeni_log)
        db.session.commit()
    return "OK"


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


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- 1. E-posta Onay Rotası ---
@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = ts.loads(token, salt='email-confirm', max_age=86400)
    except:
        flash('Onay linki geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first_or_404()
    
    if user.is_confirmed:
        flash('Hesabınız zaten onaylanmış.', 'info')
    else:
        user.is_confirmed = True
        db.session.commit()
        flash('Hesabınız başarıyla onaylandı! Artık giriş yapabilirsiniz.', 'success')
        
    return redirect(url_for('login'))

# --- 2. Admin Paneli Rotası ---
@app.route('/admin_panel')
@login_required
def admin_panel():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    logs = HatirlatmaLog.query.order_by(HatirlatmaLog.tarih.desc()).limit(50).all()
    users = User.query.all()
    return render_template('admin.html', logs=logs, users=users)

# --- 3. Uygulamayı Çalıştıran Blok ---
if __name__ == '__main__':
    app.run()

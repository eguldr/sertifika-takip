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
# UYGULAMA KURULUMU
# ============================================================
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'eg_optimal_final_master_v86'),
    SECURITY_PASSWORD_SALT='eg_salt_987'
)

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
    MAIL_USERNAME=os.environ.get('MAIL_USERNAME', 'erhanadea@gmail.com'),
    MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD', 'bwdxhwamvoggqdko'),
    MAIL_DEFAULT_SENDER=os.environ.get('MAIL_USERNAME', 'erhanadea@gmail.com')
)
mail = Mail(app)
ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])
login_manager = LoginManager(app)
login_manager.login_view = 'login'

cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'dh2pefkko'),
    api_key=os.environ.get('CLOUDINARY_API_KEY', '414697559795627'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', '')
)


# ============================================================
# VERİTABANI MODELLERİ
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
    is_active = db.Column(db.Boolean, default=True)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.before_request
def setup_db():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            for sql in [
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS whatsapp_no VARCHAR(20)",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS note TEXT",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS belge_url VARCHAR(500)",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS firma_adi VARCHAR(100)",
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS company_name VARCHAR(100) DEFAULT \'\'',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS admin_note TEXT DEFAULT \'\'',
            ]:
                try:
                    db.session.execute(text(sql))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
        app._db_init = True


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================
def verify_recaptcha(response_token):
    secret = os.environ.get('RECAPTCHA_SECRET_KEY')
    if not secret:
        return True
    result = requests.post(
        'https://www.google.com/recaptcha/api/siteverify',
        data={'secret': secret, 'response': response_token}
    ).json()
    return result.get('success', False)


def send_verification_email(user_email):
    try:
        token       = ts.dumps(user_email, salt='email-confirm')
        confirm_url = url_for('confirm_email', token=token, _external=True)
        msg = Message("EG Optimal - Hesabinizi Onayin", recipients=[user_email])
        msg.body = (
            f"Hesabinizi aktiflesirmek icin asagidaki linke tiklayin:\n\n"
            f"{confirm_url}\n\nBu link 24 saat boyunca gecerlidir.\n\nEG Optimal"
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Dogrulama maili hatasi: {e}")
        return False


def send_belge_email(user_email, cert_name, expiry_date):
    try:
        msg = Message("EG Optimal - Belge Kaydedildi", recipients=[user_email])
        msg.body = (
            f"'{cert_name}' isimli belgeniz sisteme kaydedildi.\n"
            f"Bitis Tarihi: {expiry_date}\n\n"
            f"6 ay, 3 ay ve 30 gun kala otomatik hatirlatma yapilacaktir.\n\nEG Optimal"
        )
        mail.send(msg)
    except Exception as e:
        print(f"Belge maili hatasi: {e}")


def tespit_brans(satirlar):
    """
    Excel satırındaki tüm değerleri birleştirip branş tespiti yapar.
    Önce Personel (isim kalıpları dahil), sonra Araç, Tesis, Üretim kontrol edilir.
    """
    txt = " ".join([str(v) for v in satirlar]).lower()

    # --- PERSONEL: İsim kalıpları + meslek unvanları ---
    personel_keywords = [
        'personel', 'src', 'ehliyet', 'calisan', 'operator', 'operatör',
        'sofor', 'sürücü', 'forklift', 'muhendis', 'teknisyen', 'usta',
        'isci', 'stajyer', 'mudur', 'müdür', 'uzman', 'tekniker',
        'hemşire', 'doktor', 'güvenlik', 'bekci', 'temizlik'
    ]
    # İsim tespiti: büyük harfle başlayan 2+ kelime yan yana (Ad Soyad kalıbı)
    isim_pattern = bool(re.search(r'[a-züğşıöçA-ZÜĞŞİÖÇ][a-züğşıöçA-ZÜĞŞİÖÇ]+\s+[a-züğşıöçA-ZÜĞŞİÖÇ][a-züğşıöçA-ZÜĞŞİÖÇ]+', ' '.join([str(v) for v in satirlar])))

    if any(x in txt for x in personel_keywords) or isim_pattern:
        return 'Personel'

    # --- ARAÇ ---
    arac_keywords = [
        'plaka', 'arac', 'araç', 'scania', 'tir', 'kamyon', 'truck',
        'ford', 'mercedes', 'volvo', 'daf', 'man ', 'fiat', 'renault',
        'iveco', 'isuzu', 'otobüs', 'minibus', 'forklift makinesi',
        'iş makinesi', 'vinc', 'vinç', 'ekskavatör'
    ]
    if any(x in txt for x in arac_keywords):
        return 'Arac'

    # --- TESİS ---
    tesis_keywords = [
        'tesis', 'yangin', 'yangın', 'kapasite', 'bina', 'depo',
        'fabrika', 'imalathane', 'atölye', 'elektrik', 'asansor',
        'kazan', 'tank', 'kompresör', 'basınçlı'
    ]
    if any(x in txt for x in tesis_keywords):
        return 'Tesis'

    # --- ÜRETİM ---
    uretim_keywords = [
        'iso', 'uretim', 'üretim', 'kalite', 'ce belgesi', 'haccp',
        'gıda', 'gida', 'helal', 'organik', 'akreditasyon', 'tsе', 'tse'
    ]
    if any(x in txt for x in uretim_keywords):
        return 'Uretim'

    return 'Genel'


# ============================================================
# AUTH ROTALARI
# ============================================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form.get('email', '').strip()).first()
        if u and check_password_hash(u.password, request.form.get('password', '')):
            login_user(u)
            return redirect(url_for('dashboard'))
        flash("Giris basarisiz. E-posta veya sifre hatali.", "danger")
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/kayit', methods=['GET', 'POST'])
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if not verify_recaptcha(request.form.get('g-recaptcha-response', '')):
            flash("Lutfen robot olmadiginizi dogrulayin!", "danger")
            return redirect(url_for('register'))

        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if User.query.filter_by(email=email).first():
            flash("Bu e-posta zaten kayitli.", "warning")
            return redirect(url_for('register'))

        u = User(
            email        = email,
            password     = generate_password_hash(password),
            is_confirmed = False,
            is_paid      = False
        )
        db.session.add(u)
        db.session.commit()
        send_verification_email(email)
        flash("Kayit basarili! Lutfen e-postanizi onayin.", "success")
        return redirect(url_for('login'))

    return render_template('kayit.html',
        recaptcha_site_key=os.environ.get('RECAPTCHA_SITE_KEY', ''))


# ============================================================
# E-POSTA DOĞRULAMA
# ============================================================
@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = ts.loads(token, salt='email-confirm', max_age=86400)
    except Exception:
        flash("Onay linki gecersiz veya suresi dolmus.", "danger")
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first_or_404()
    if user.is_confirmed:
        flash("Hesabiniz zaten onaylanmis.", "info")
    else:
        user.is_confirmed = True
        db.session.commit()
        flash("Hesabiniz onaylandi! Giris yapabilirsiniz.", "success")
    return redirect(url_for('login'))


# ============================================================
# ŞİFRE SIFIRLAMA
# ============================================================
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user  = User.query.filter_by(email=email).first()
        if user:
            token       = ts.dumps(email, salt='recover-key')
            recover_url = url_for('reset_password', token=token, _external=True)
            try:
                msg = Message("Sifre Sifirlama - EG Optimal", recipients=[email])
                msg.body = (
                    f"Sifrenizi sifirlamak icin:\n\n{recover_url}\n\n"
                    f"Bu baglanti 30 dakika gecerlidir."
                )
                mail.send(msg)
            except Exception as e:
                print(f"Sifre sifirlama maili hatasi: {e}")
        flash("Kayitli e-postaniza sifirlama baglantisi gonderildi.", "info")
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = ts.loads(token, salt='recover-key', max_age=1800)
    except Exception:
        flash("Sifre sifirlama baglantisi gecersiz veya suresi dolmus.", "danger")
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        user     = User.query.filter_by(email=email).first()
        if user:
            user.password = generate_password_hash(password)
            db.session.commit()
            flash("Sifreniz guncellendi. Giris yapabilirsiniz.", "success")
            return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)


# ============================================================
# DASHBOARD
# ============================================================
@app.route('/dashboard')
@login_required
def dashboard():
    # Admin ise tüm kayıtları görsün
    if current_user.email == 'erhanadea@gmail.com':
        res = Entry.query.filter_by(is_active=True)\
                   .order_by(Entry.expiry_date.asc()).all()
    else:
        res = Entry.query.filter_by(user_id=current_user.id, is_active=True)\
                   .order_by(Entry.expiry_date.asc()).all()
    return render_template('dashboard.html',
        sertifikalar=res,
        bugun=date.today(),
        timedelta=timedelta,
        current_cat=None
    )


@app.route('/sertifikalar/<cat>')
@login_required
def sertifikalar(cat):
    if current_user.email == 'erhanadea@gmail.com':
        Entry.query.filter_by(user_id=current_user.id, category=cat, is_active=True)
                   .order_by(Entry.expiry_date.asc()).all()
    else:
        res = Entry.query.filter_by(user_id=current_user.id, category=cat)\
                   .order_by(Entry.expiry_date.asc()).all()
    return render_template('dashboard.html',
        sertifikalar=res,
        bugun=date.today(),
        timedelta=timedelta,
        current_cat=cat
    )


# ============================================================
# KAYIT EKLE / SİL
# ============================================================
@app.route('/kayit_ekle/<cat>', methods=['GET', 'POST'])
@login_required
def kayit_ekle(cat):
    if request.method == 'POST':
        exp_str     = request.form.get('expiry_date')
        title       = request.form.get('title', '')
        firma_adi   = request.form.get('firma_adi', '')
        whatsapp_no = request.form.get('whatsapp_no', '')
        note        = request.form.get('note', '')
        expiry_date = datetime.strptime(exp_str, '%Y-%m-%d').date() if exp_str else date.today()

        new_e = Entry(
            user_id     = current_user.id,
            category    = cat,
            title       = title,
            firma_adi   = firma_adi,
            whatsapp_no = whatsapp_no,
            note        = note,
            expiry_date = expiry_date
        )
        db.session.add(new_e)
        db.session.commit()
        send_belge_email(current_user.email, title, expiry_date)
        return redirect(url_for('sertifikalar', cat=cat))

    return render_template('ekle.html', cat=cat)


@app.route('/delete_entry/<int:id>')
@login_required
def delete_entry(id):
    e = Entry.query.get(id)
    if e and (e.user_id == current_user.id or current_user.email == 'erhanadea@gmail.com'):
        e.is_active = False
        db.session.commit()
        db.session.commit()
    return redirect(request.referrer or url_for('dashboard'))


# ============================================================
# CLOUDINARY BELGE YÜKLEME
# ============================================================
@app.route('/upload_belge/<int:entry_id>', methods=['POST'])
@login_required
def upload_belge(entry_id):
    f = request.files.get('file')
    if f:
        try:
            res = cloudinary.uploader.upload(f, resource_type="auto")
            e   = Entry.query.get(entry_id)
            if e and (e.user_id == current_user.id or current_user.email == 'erhanadea@gmail.com'):
                e.belge_url = res.get('secure_url')
                db.session.commit()
        except Exception as ex:
            flash(f"Bulut yukleme hatasi: {ex}", "danger")
    return redirect(request.referrer or url_for('dashboard'))


# ============================================================
# EXCEL İÇE AKTAR — Akıllı Branş + Firma + Gerçek Tarih
# ============================================================
@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if not f:
        flash("Dosya secilmedi.", "warning")
        return redirect(url_for('dashboard'))

    
    db.session.commit()

    df = pd.read_excel(f)
    df.columns = [str(c).strip() for c in df.columns]

    # Sütun bul
    def find_col(keywords):
        for col in df.columns:
            col_lower = col.lower()
            if any(k in col_lower for k in keywords):
                return col
        return None

    title_col = find_col(['belge', 'plaka', 'isim', 'ad', 'tanim', 'title'])
    firma_col = find_col(['firma', 'kurum', 'sirket', 'company', 'müşteri', 'musteri'])
    tarih_col = find_col(['bitis', 'tarih', 'expiry', 'son', 'gecerlilik', 'vade'])

    eklenen = 0
    for _, r in df.iterrows():
        satirlar = list(r.values)

        # Branş tespiti
        cat = tespit_brans(satirlar)

        # Başlık
        title = str(r[title_col]).strip() if title_col and pd.notna(r.get(title_col)) else str(r.iloc[0])

        # Firma adı
        firma = str(r[firma_col]).strip() if firma_col and pd.notna(r.get(firma_col)) else ''

        # Bitiş tarihi — Excel'den oku, yoksa 365 gün sonrası
        expiry = date.today() + timedelta(days=365)
        if tarih_col and pd.notna(r.get(tarih_col)):
            try:
                expiry = pd.to_datetime(r[tarih_col], dayfirst=True).date()
            except Exception:
                pass

        db.session.add(Entry(
            user_id     = current_user.id,
            category    = cat,
            title       = title,
            firma_adi   = firma,
            expiry_date = expiry
        ))
        eklenen += 1

    db.session.commit()
    flash(f"Excel basariyla yuklendi. {eklenen} kayit eklendi.", "success")
    return redirect(url_for('dashboard'))


# ============================================================
# EXCEL DIŞA AKTAR
# ============================================================
@app.route('/export_excel')
@login_required
def export_excel():
    if current_user.email == 'erhanadea@gmail.com':
        entries = Entry.query.all()
    else:
        entries = Entry.query.filter_by(user_id=current_user.id).all()

    data = [
        {
            "Kategori":     e.category,
            "Firma Adi":    e.firma_adi,
            "Belge Adi":    e.title,
            "WhatsApp":     e.whatsapp_no,
            "Not":          e.note,
            "Bitis Tarihi": e.expiry_date.strftime('%d.%m.%Y') if e.expiry_date else "",
            "Belge URL":    e.belge_url or ""
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


# ============================================================
# ADMİN PANELİ
# ============================================================
@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))

    tum_kullanicilar  = User.query.all()
    odeme_yapmayanlar = User.query.filter_by(is_paid=False).all()
    tum_belgeler      = Entry.query.order_by(Entry.expiry_date.asc()).all()
    bugun             = date.today()

    # Her kullanıcının belge sayısı
    kullanici_belge = {}
    for u in tum_kullanicilar:
        kullanici_belge[u.id] = Entry.query.filter_by(user_id=u.id).count()

    return render_template('admin.html',
        users             = tum_kullanicilar,
        odeme_yapmayanlar = odeme_yapmayanlar,
        all_entries       = tum_belgeler,
        kullanici_belge   = kullanici_belge,
        bugun             = bugun,
        timedelta         = timedelta
    )


@app.route('/update_payment/<int:uid>', methods=['GET', 'POST'])
@login_required
def update_payment(uid):
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    user = User.query.get(uid)
    if user:
        if request.method == 'POST':
            user.company_name = request.form.get('company_name', '')
            user.is_paid      = request.form.get('is_paid') == 'true'
            user.admin_note   = request.form.get('admin_note', '')
        else:
            user.is_paid = not user.is_paid
        db.session.commit()
        flash(f"{user.email} guncellendi.", "success")
    return redirect(url_for('admin_panel'))


@app.route('/delete_user/<int:uid>')
@login_required
def delete_user(uid):
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    user = User.query.get(uid)
    if user:
        Entry.query.filter_by(user_id=uid).delete()
        db.session.delete(user)
        db.session.commit()
        flash("Kullanici silindi.", "success")
    return redirect(url_for('admin_panel'))


# ============================================================
# OTOMATİK HATIRLATMA
# ============================================================
@app.route('/cron/check_reminders')
def check_reminders():
    bugun    = date.today()
    kayitlar = Entry.query.all()
    gonderr  = 0

    for e in kayitlar:
        if not e.expiry_date:
            continue
        kalan = (e.expiry_date - bugun).days
        if kalan in [180, 90, 30]:
            user = User.query.get(e.user_id)
            if user:
                vade = {180: "6 Ay", 90: "3 Ay", 30: "1 Ay"}[kalan]
                try:
                    msg = Message(
                        f"EG Optimal Hatirlatma: {e.title} ({vade})",
                        recipients=[user.email]
                    )
                    msg.body = (
                        f"'{e.title}' belgenizin bitmesine {vade} kalmistir.\n"
                        f"Firma: {e.firma_adi}\n"
                        f"Bitis: {e.expiry_date.strftime('%d.%m.%Y')}\n\n"
                        f"EG Optimal Danismanlik"
                    )
                    mail.send(msg)
                    gonderr += 1
                except Exception as ex:
                    print(f"Hatirlatma hatasi: {ex}")

    return f"OK - {gonderr} hatirlatma gonderildi.", 200


# ============================================================
if __name__ == '__main__':
    app.run(debug=True)

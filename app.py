import os
import time
import hashlib
from google import genai
client = genai.Client(api_key=os.environ.get('GEMINI_API_KEY'))
import re
import cloudinary
import cloudinary.uploader
import requests
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
from io import BytesIO
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import text

# ============================================================
# UYGULAMA KURULUMU
# ============================================================
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'eg_optimal_ultra_master_final_v2200_2026'),
    SECURITY_PASSWORD_SALT='eg_super_salt_secure_99_pro',
)

uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db            = SQLAlchemy(app)
ts            = URLSafeTimedSerializer(app.config['SECRET_KEY'])
login_manager = LoginManager(app)
login_manager.login_view = 'login'

cloudinary.config(
    cloud_name='dh2pefkko',
    api_key='626365126779241',
    api_secret='A1q12Oiih6Gc6PfKdPFextUsm-l',
    secure=True
)

BREVO_API_KEY    = os.environ.get('BREVO_API_KEY', '')
BREVO_SENDER_MAIL = os.environ.get('BREVO_SENDER_MAIL', 'eguldr@gmail.com')
BREVO_SENDER_NAME = 'EG Optimal'

# ============================================================
# VERİTABANI MODELLERİ
# ============================================================
class User(UserMixin, db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    email           = db.Column(db.String(100), unique=True, nullable=False)
    password        = db.Column(db.String(256), nullable=False)
    company_name    = db.Column(db.String(100), default='')
    is_confirmed    = db.Column(db.Boolean, default=False)   # E-posta doğrulama
    is_paid         = db.Column(db.Boolean, default=False)
    admin_note      = db.Column(db.Text, default='')
    kvkk_onay       = db.Column(db.Boolean, default=False)
    sektor          = db.Column(db.String(50), default='genel')  # lojistik / gida / danismanlik / genel


class Entry(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, nullable=False)
    category    = db.Column(db.String(50))
    title       = db.Column(db.String(100))
    firma_adi   = db.Column(db.String(100))
    expiry_date = db.Column(db.Date)
    belge_url   = db.Column(db.String(500))
    whatsapp_no = db.Column(db.String(20))
    danisman_no = db.Column(db.String(20))
    note        = db.Column(db.Text)
    is_active   = db.Column(db.Boolean, default=True)
    dosya_hash  = db.Column(db.String(64))  # Delta işleme için


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.before_request
def setup_db():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            for sql in [
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS whatsapp_no VARCHAR(20)",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS danisman_no VARCHAR(20)",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS note TEXT",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS belge_url VARCHAR(500)",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS firma_adi VARCHAR(100)",
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS dosya_hash VARCHAR(64)",
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_confirmed BOOLEAN DEFAULT FALSE',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS company_name VARCHAR(100) DEFAULT \'\'',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS admin_note TEXT DEFAULT \'\'',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS kvkk_onay BOOLEAN DEFAULT FALSE',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS sektor VARCHAR(50) DEFAULT \'genel\'',
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
def send_mail(to, subject, body):
    """Brevo HTTP API üzerinden mail gönder (SMTP port sorunu yok)"""
    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": BREVO_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_MAIL},
                "to": [{"email": to}],
                "subject": subject,
                "textContent": body
            },
            timeout=15
        )
        print(f"Brevo yanit: {response.status_code} - {response.text[:200]}")
        return response.status_code == 201
    except Exception as e:
        print(f"Mail hatasi: {e}")
        return False


def send_verification_mail(email, token):
    """E-posta doğrulama maili gönder"""
    verify_url = url_for('verify_email', token=token, _external=True)
    body = (
        f"Merhaba,\n\n"
        f"EG Optimal'e kayıt olduğunuz için teşekkürler!\n\n"
        f"Hesabınızı aktifleştirmek için aşağıdaki bağlantıya tıklayın:\n\n"
        f"{verify_url}\n\n"
        f"Bu bağlantı 24 saat geçerlidir.\n\n"
        f"Saygılarımızla,\nEG Optimal Ekibi"
    )
    return send_mail(email, "EG Optimal - E-posta Doğrulama", body)


def cloudinary_belge_url(url):
    if not url:
        return url
    if not url.lower().endswith(".pdf"):
        return url
    if "/fl_inline/" in url:
        return url
    return re.sub(r'(/upload/)', r'\1fl_inline/', url, count=1)


app.jinja_env.globals['cloudinary_belge_url'] = cloudinary_belge_url


def ai_ile_analiz_et(satir_metni):
    time.sleep(2)
    prompt = f"Veri: {satir_metni}. Sadece şu kategorilerden birini yaz: Arac, Tesis, Urun, Personel."
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        cevap = response.text.strip().replace("'", "").replace('"', '')
        valid_cats = ['Arac', 'Tesis', 'Urun', 'Personel']
        return cevap if cevap in valid_cats else 'Urun'
    except Exception as e:
        print(f"AI LIMIT VEYA HATA: {e}")
        return 'Genel'


def akilli_analiz_motoru(satir):
    txt = " ".join([str(v) for v in satir]).lower()

    personel_kw = ['src', 'ehliyet', 'operator', 'operatör', 'sofor', 'şoför',
                   'personel', 'psikoteknik', 'isg', 'mesleki yeterlilik',
                   'yetki', 'kullanım', 'kullanim', 'belgesi', 'vinc', 'vinç']
    if any(k in txt for k in personel_kw):
        return 'Personel'

    if any(k in txt for k in ['plaka', 'scania', 'muayene', 'kamyon', 'ford',
                               'mercedes', 'volvo', 'tir', 'tır', 'araç', 'arac',
                               'kasko', 'egzoz', 'takograf', 'k belgesi', 'vdi 2700',
                               'emisyon', 'pul', 'lojistik']):
        return 'Arac'

    if any(k in txt for k in ['yangin', 'yangın', 'tüp', 'bina', 'fabrika', 'kapasite',
                               'tesis', 'itfaiye', 'ced', 'çed', 'sanayi sicil', 'ruhsat',
                               'atik', 'atık', 'tabs', 'cevre', 'çevre', 'asansor', 'asansör',
                               'söndürme', 'sondurme', 'gazlı', 'gazli', 'oda']):
        return 'Tesis'

    if any(k in txt for k in ['sertifika', 'iso', 'kalite', 'ce belgesi', 'brc', 'fssc',
                               'atex', 'ukca', 'eac', 'gdp', 'gmp', 'kalibrasyon',
                               'haccp', 'helal', 'organik', 'gida', 'gıda', 'hijyen']):
        return 'Urun'

    return ai_ile_analiz_et(txt)


# ============================================================
# AUTH — KAYIT, GİRİŞ, DOĞRULAMA
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
            # Admin her zaman girebilir
            if not u.is_confirmed and u.email != 'erhanadea@gmail.com':
                flash("Lütfen önce e-postanızı doğrulayın. Gelen kutunuzu kontrol edin.", "warning")
                return redirect(url_for('login'))
            login_user(u)
            return redirect(url_for('dashboard'))
        flash("E-posta veya şifre hatalı.", "danger")
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/auth_register_new', methods=['GET', 'POST'])
@app.route('/register', methods=['GET', 'POST'])
@app.route('/kayit', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Robot kontrolü
        robot_cevap = request.form.get('robot_kontrol', '').strip()
        if robot_cevap != '5':
            flash("Robot kontrolü başarısız. 2 + 3 = 5 olmalıdır.", "danger")
            return redirect(url_for('register'))

        # KVKK kontrolü
        kvkk = request.form.get('kvkk_onay')
        if not kvkk:
            flash("Devam edebilmek için KVKK metnini onaylamanız gerekmektedir.", "danger")
            return redirect(url_for('register'))

        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        sektor   = request.form.get('sektor', 'genel')

        if User.query.filter_by(email=email).first():
            flash("Bu e-posta zaten kayıtlı.", "warning")
            return redirect(url_for('register'))

        u = User(
            email        = email,
            password     = generate_password_hash(password),
            company_name = request.form.get('company_name', ''),
            is_confirmed = False,  # E-posta doğrulanana kadar False
            is_paid      = False,
            kvkk_onay    = True,
            sektor       = sektor
        )
        db.session.add(u)
        db.session.commit()

        # Doğrulama maili gönder
        token = ts.dumps(email, salt='email-confirm-key')
        mail_gitti = send_verification_mail(email, token)

        if mail_gitti:
            flash("Kayıt başarılı! E-postanıza doğrulama bağlantısı gönderdik. Lütfen gelen kutunuzu kontrol edin.", "success")
        else:
            flash("Kayıt başarılı ancak doğrulama maili gönderilemedi. Lütfen bizimle iletişime geçin.", "warning")

        return redirect(url_for('login'))

    return render_template('kayit.html')


@app.route('/verify_email/<token>')
def verify_email(token):
    """E-posta doğrulama linki"""
    try:
        email = ts.loads(token, salt='email-confirm-key', max_age=86400)  # 24 saat
    except Exception:
        flash("Doğrulama linki geçersiz veya süresi dolmuş.", "danger")
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first()
    if user:
        user.is_confirmed = True
        db.session.commit()
        flash("E-postanız doğrulandı! Artık giriş yapabilirsiniz.", "success")
    return redirect(url_for('login'))


@app.route('/resend_verification', methods=['POST'])
def resend_verification():
    """Doğrulama mailini tekrar gönder"""
    email = request.form.get('email', '').strip()
    user = User.query.filter_by(email=email).first()
    if user and not user.is_confirmed:
        token = ts.dumps(email, salt='email-confirm-key')
        send_verification_mail(email, token)
    flash("Doğrulama maili tekrar gönderildi.", "info")
    return redirect(url_for('login'))


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user  = User.query.filter_by(email=email).first()
        if user:
            token       = ts.dumps(email, salt='recover-key')
            recover_url = url_for('reset_password', token=token, _external=True)
            send_mail(email, "Şifre Sıfırlama - EG Optimal",
                      f"Merhaba,\n\nŞifrenizi sıfırlamak için:\n\n{recover_url}\n\n"
                      f"Bu link 30 dakika geçerlidir.\n\nEG Optimal Ekibi")
        flash("Kayıtlı e-postanıza sıfırlama bağlantısı gönderildi.", "info")
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = ts.loads(token, salt='recover-key', max_age=1800)
    except Exception:
        flash("Link geçersiz veya süresi dolmuş.", "danger")
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        user = User.query.filter_by(email=email).first()
        if user:
            user.password = generate_password_hash(request.form.get('password', ''))
            db.session.commit()
            flash("Şifreniz güncellendi.", "success")
            return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)


# ============================================================
# DASHBOARD
# ============================================================
@app.route('/dashboard')
@app.route('/dashboard/<cat>')
@login_required
def dashboard(cat=None):
    try:
        sorgu = Entry.query.filter(
            Entry.is_active == True,
            Entry.user_id == current_user.id
        )
        if cat and cat != 'all':
            sorgu = sorgu.filter(Entry.category == cat)
        liste = sorgu.order_by(Entry.expiry_date.asc()).all()
    except Exception as e:
        print(f"Dashboard sorgu hatasi: {e}")
        liste = []
        flash("Veri yüklenirken hata oluştu.", "danger")

    return render_template('dashboard.html',
        sertifikalar = liste,
        bugun        = date.today(),
        timedelta    = timedelta,
        current_cat  = cat or 'all'
    )


@app.route('/sertifikalar/<cat>')
@login_required
def sertifikalar(cat):
    return redirect(url_for('dashboard', cat=cat))


# ============================================================
# KAYIT EKLE
# ============================================================
@app.route('/kayit_ekle/<cat>', methods=['GET', 'POST'])
@login_required
def ekle(cat):
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if title == 'LİSTEDE YOK / MANUEL YAZ':
            title = request.form.get('manual_title', '').strip()

        exp_str = request.form.get('expiry_date', '')
        try:
            expiry = datetime.strptime(exp_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            flash('Geçerli bir tarih giriniz.', 'danger')
            return render_template('ekle.html', cat=cat)

        try:
            yeni = Entry(
                user_id     = current_user.id,
                category    = cat,
                title       = title,
                firma_adi   = request.form.get('firma_adi', '').strip(),
                whatsapp_no = request.form.get('whatsapp_no', '').strip(),
                danisman_no = request.form.get('danisman_no', '').strip(),
                note        = request.form.get('note', '').strip(),
                expiry_date = expiry,
                is_active   = True
            )
            db.session.add(yeni)
            db.session.commit()
            flash(f'{title} başarıyla takibe alındı!', 'success')
            return redirect(url_for('dashboard', cat=cat))
        except Exception as e:
            db.session.rollback()
            flash(f'Kayıt hatası: {str(e)}', 'danger')

    return render_template('ekle.html', cat=cat)


# ============================================================
# SİL
# ============================================================
@app.route('/sil/<int:id>')
@app.route('/delete_entry/<int:id>')
@login_required
def sil(id):
    cat = request.args.get('cat', 'all')
    try:
        e = Entry.query.get(id)
        if e and (e.user_id == current_user.id or current_user.email == 'erhanadea@gmail.com'):
            e.is_active = False
            db.session.commit()
            flash("Kayıt silindi.", "success")
        else:
            flash("Kayıt bulunamadı veya yetkiniz yok.", "danger")
    except Exception as ex:
        flash(f"Silme hatası: {ex}", "danger")
    return redirect(url_for('dashboard', cat=cat))


# ============================================================
# CLOUDINARY BELGE YÜKLEME
# ============================================================
@app.route('/upload_belge/<int:entry_id>', methods=['POST'])
@login_required
def upload_belge(entry_id):
    f   = request.files.get('file')
    cat = request.args.get('cat', 'all')
    if f:
        try:
            res = cloudinary.uploader.unsigned_upload(
                f,
                upload_preset='erhan_preset',
                resource_type='raw'
            )
            e = Entry.query.get(entry_id)
            if e and (e.user_id == current_user.id or current_user.email == 'erhanadea@gmail.com'):
                raw_url = res.get('secure_url')
                if not raw_url:
                    raise Exception("Cloudinary URL alınamadı")
                e.belge_url = cloudinary_belge_url(raw_url)
                db.session.commit()
                flash("Belge başarıyla yüklendi.", "success")
            else:
                flash("Yetki hatası.", "danger")
        except Exception as ex:
            print(f"CLOUDINARY HATA: {ex}")
            flash(f"Yükleme hatası: {ex}", "danger")
    else:
        flash("Lütfen bir dosya seçin.", "warning")
    return redirect(url_for('dashboard', cat=cat))


# ============================================================
# EXCEL İÇE AKTAR — Hibrit Akıllı Analiz
# ============================================================
@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if not f:
        flash("Dosya seçilmedi.", "warning")
        return redirect(url_for('dashboard'))
    try:
        Entry.query.filter_by(user_id=current_user.id).update({'is_active': False})
        db.session.commit()

        df = pd.read_excel(f)
        df.columns = [str(c).strip() for c in df.columns]

        def find_col(keywords):
            for col in df.columns:
                if any(k in col.lower() for k in keywords):
                    return col
            return None

        title_col = find_col(['belge', 'plaka', 'isim', 'ad', 'tanim', 'title'])
        firma_col = find_col(['firma', 'kurum', 'sirket', 'company', 'musteri'])
        tarih_col = find_col(['bitis', 'tarih', 'expiry', 'son', 'gecerlilik', 'vade'])

        eklenen = 0
        for _, r in df.iterrows():
            satirlar = list(r.values)
            cat      = akilli_analiz_motoru(satirlar)
            title    = str(r[title_col]).strip() if title_col and pd.notna(r.get(title_col)) else str(r.iloc[0])
            firma    = str(r[firma_col]).strip() if firma_col and pd.notna(r.get(firma_col)) else ''
            expiry   = date.today() + timedelta(days=365)

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
                expiry_date = expiry,
                is_active   = True
            ))
            eklenen += 1

        db.session.commit()
        flash(f"Excel başarıyla yüklendi. {eklenen} kayıt eklendi.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Excel hatası: {str(e)}", "danger")
    return redirect(url_for('dashboard'))


# ============================================================
# EXCEL DIŞA AKTAR
# ============================================================
@app.route('/export_excel')
@login_required
def export_excel():
    try:
        if current_user.email == 'erhanadea@gmail.com':
            entries = Entry.query.filter_by(is_active=True).all()
        else:
            entries = Entry.query.filter_by(user_id=current_user.id, is_active=True).all()

        data = [{
            "Kategori":     e.category,
            "Firma":        e.firma_adi,
            "Belge Adı":    e.title,
            "WhatsApp":     e.whatsapp_no,
            "Not":          e.note,
            "Bitiş Tarihi": e.expiry_date.strftime('%d.%m.%Y') if e.expiry_date else "",
            "Belge URL":    e.belge_url or ""
        } for e in entries]

        df     = pd.DataFrame(data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sertifikalar')
        output.seek(0)
        return send_file(output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True, download_name="EG_Optimal_Rapor.xlsx")
    except Exception as e:
        flash(f"Dışa aktarım hatası: {e}", "danger")
        return redirect(url_for('dashboard'))
{% extends "base.html" %}
{% block content %}
<style>
    :root {
        --navy: #1a1c4b;
        --accent: #c5a059;
        --danger: #dc2626;
        --warn: #d97706;
        --success: #059669;
    }
    body { background: #f0f4f8; }

    /* ── KRİTİK BANNER ── */
    .critical-banner {
        background: linear-gradient(135deg, #fff 0%, #fff5f5 100%);
        border-left: 6px solid var(--danger);
        border-radius: 12px;
        padding: 16px 24px;
        margin-bottom: 24px;
        display: flex; align-items: center; justify-content: space-between;
        box-shadow: 0 4px 20px rgba(220,38,38,0.12);
        animation: pulse-border 2s infinite;
    }
    @keyframes pulse-border {
        0%,100% { box-shadow: 0 4px 20px rgba(220,38,38,0.12); }
        50%      { box-shadow: 0 4px 28px rgba(220,38,38,0.28); }
    }
    .critical-banner .c-text { color: var(--danger); font-weight: 700; font-size: 1rem; }

    /* ── SAYFA BAŞLIĞI ── */
    .page-header {
        display: flex; justify-content: space-between; align-items: center;
        margin-bottom: 24px; flex-wrap: wrap; gap: 12px;
    }
    .page-header h2 { color: var(--navy); font-weight: 800; font-size: 1.6rem; margin: 0; }
    .page-header .sub { color: #94a3b8; font-size: 0.82rem; margin-top: 2px; }

    /* ── KPI KARTLARI ── */
    .kpi-card {
        background: white; border-radius: 14px; padding: 20px 24px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        border-top: 4px solid transparent;
        cursor: pointer; transition: all 0.25s;
        position: relative; overflow: hidden;
    }
    .kpi-card:hover { transform: translateY(-3px); box-shadow: 0 8px 24px rgba(0,0,0,0.1); }
    .kpi-card::after {
        content: ''; position: absolute; right: -12px; top: -12px;
        width: 70px; height: 70px; border-radius: 50%;
        background: currentColor; opacity: 0.04;
    }
    .kpi-card.danger  { border-top-color: var(--danger); }
    .kpi-card.warning { border-top-color: var(--warn); }
    .kpi-card.primary { border-top-color: var(--navy); }
    .kpi-label { font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
    .kpi-value { font-size: 2.4rem; font-weight: 800; line-height: 1; }
    .kpi-card.danger  .kpi-label, .kpi-card.danger  .kpi-value { color: var(--danger); }
    .kpi-card.warning .kpi-label, .kpi-card.warning .kpi-value { color: var(--warn); }
    .kpi-card.primary .kpi-label, .kpi-card.primary .kpi-value { color: var(--navy); }

    /* ── TABLO ── */
    .data-card {
        background: white; border-radius: 14px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.07); overflow: hidden;
    }
    .data-card .table { margin: 0; }
    .data-card .table thead th {
        background: var(--navy); color: white; font-size: 0.68rem;
        text-transform: uppercase; letter-spacing: 1.2px;
        padding: 14px 16px; border: none; font-weight: 600;
    }
    .data-card .table tbody td { padding: 14px 16px; vertical-align: middle; border-color: #f1f5f9; }
    .data-card .table tbody tr:hover { background: #f8fafc; }

    .belge-title { font-weight: 700; color: var(--navy); font-size: 0.9rem; }
    .belge-meta  { color: #94a3b8; font-size: 0.75rem; margin-top: 2px; }

    .badge-days {
        display: inline-block; padding: 5px 14px; border-radius: 20px;
        font-size: 0.78rem; font-weight: 700;
    }
    .badge-days.danger  { background: #fef2f2; color: var(--danger); border: 1px solid #fecaca; }
    .badge-days.warning { background: #fffbeb; color: var(--warn);   border: 1px solid #fde68a; }
    .badge-days.success { background: #f0fdf4; color: var(--success); border: 1px solid #bbf7d0; }

    .btn-action { border: none; background: none; padding: 6px 8px; border-radius: 8px; transition: 0.2s; }
    .btn-action:hover { background: #f1f5f9; }
    .btn-action.danger-hover:hover { background: #fef2f2; color: var(--danger); }

    /* ── PDF YÜKLEME ALANI ── */
    .upload-zone {
        border: 2px dashed #cbd5e1; border-radius: 12px;
        padding: 32px; text-align: center; cursor: pointer;
        transition: all 0.2s; background: #f8fafc;
    }
    .upload-zone:hover, .upload-zone.dragover {
        border-color: var(--navy); background: #f0f4ff;
    }
    .upload-zone i { font-size: 2.5rem; color: #94a3b8; margin-bottom: 12px; display: block; }

    /* ── PROGRESS BAR ── */
    .progress-overlay {
        display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(15,16,53,0.7); z-index: 9999;
        align-items: center; justify-content: center; flex-direction: column;
    }
    .progress-overlay.show { display: flex; }
    .progress-box {
        background: white; border-radius: 16px; padding: 40px 48px;
        text-align: center; min-width: 320px; box-shadow: 0 24px 60px rgba(0,0,0,0.3);
    }
</style>

<!-- ═══ PROGRESS OVERLAY ═══ -->
<div class="progress-overlay" id="pdfProgress">
    <div class="progress-box">
        <div style="font-size: 2.5rem; margin-bottom: 16px;">🤖</div>
        <h5 style="color:#1a1c4b; font-weight:800;" id="progressTitle">PDF'ler Analiz Ediliyor</h5>
        <p class="text-muted small" id="progressSub">Gemini AI belgelerinizi okuyor, lütfen bekleyin...</p>
        <div class="progress mt-3" style="height: 10px; border-radius: 10px;">
            <div class="progress-bar progress-bar-striped progress-bar-animated"
                 id="progressBar" style="width: 0%; background: #1a1c4b;"></div>
        </div>
        <p class="text-muted small mt-2" id="progressCount"></p>
    </div>
</div>

<div class="container-fluid py-2">

    {# ── KRİTİK UYARI ── #}
    {% set bu_hafta = sertifikalar | selectattr('expiry_date', 'le', bugun + timedelta(days=7)) | list %}
    {% if bu_hafta | length > 0 %}
    <div class="critical-banner">
        <div class="c-text">
            <i class="fas fa-triangle-exclamation me-2"></i>
            Bu hafta süresi dolacak <strong>{{ bu_hafta | length }}</strong> kritik belge var!
        </div>
        <button class="btn btn-danger btn-sm fw-bold px-4" onclick="filterTable('danger')">
            Hemen İncele
        </button>
    </div>
    {% endif %}

    {# ── SAYFA BAŞLIĞI ── #}
    <div class="page-header">
        <div>
            <h2>
                EG Optimal Dashboard
                {% if current_user.email == 'erhanadea@gmail.com' %}
                <span class="badge ms-2 align-middle"
                      style="background:#c5a059; color:#1a1c4b; font-size:0.45em; letter-spacing:1px;">GLOBAL RADAR</span>
                {% endif %}
            </h2>
            <div class="sub">Dijital Risk Yönetimi ve Mevzuat Uyumluluk Paneli</div>
        </div>

        <div class="d-flex gap-2 flex-wrap align-items-center">

            {# ── PDF TOPLU YÜKLEME ── #}
            <form action="{{ url_for('import_pdf') }}" method="POST" enctype="multipart/form-data"
                  id="pdfForm" class="d-inline">
                <input type="file" name="pdf_files" id="pdf_input" multiple accept=".pdf,.jpg,.jpeg,.png"
                       style="display:none" onchange="submitPdfForm()">
                <button type="button" class="btn fw-bold px-3"
                        style="background:#1a1c4b; color:white; border-radius:10px;"
                        onclick="document.getElementById('pdf_input').click()">
                    <i class="fas fa-folder-open me-1"></i> PDF Toplu Yükle
                </button>
            </form>

            {# ── EXCEL İÇE AKTAR ── #}
            <form action="{{ url_for('import_excel') }}" method="POST" enctype="multipart/form-data" class="d-inline">
                <input type="file" name="excel_file" id="excel_input" style="display:none" onchange="this.form.submit()">
                <button type="button" class="btn fw-bold px-3"
                        style="background:#e8f5e9; color:#2e7d32; border:1px solid #a5d6a7; border-radius:10px;"
                        onclick="document.getElementById('excel_input').click()">
                    <i class="fas fa-file-import me-1"></i> Excel İçe Aktar
                </button>
            </form>

            {# ── YENİ EKLE (sektöre göre) ── #}
            <div class="dropdown">
                <button class="btn fw-bold px-3 dropdown-toggle"
                        style="background:#c5a059; color:#1a1c4b; border:none; border-radius:10px;"
                        data-bs-toggle="dropdown">
                    <i class="fas fa-plus me-1"></i> Yeni Ekle
                </button>
                <ul class="dropdown-menu shadow border-0" style="border-radius:12px; padding:8px;">
                    {% set s = current_user.sektor %}
                    {% if s == 'lojistik' %}
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Arac') }}">
                            <i class="fas fa-truck-fast me-2 text-warning"></i>Araç & Filo</a></li>
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Personel') }}">
                            <i class="fas fa-id-badge me-2 text-info"></i>Personel</a></li>
                    {% elif s == 'gida' %}
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Urun') }}">
                            <i class="fas fa-box-archive me-2 text-primary"></i>Üretim & Ürün</a></li>
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Tesis') }}">
                            <i class="fas fa-building-shield me-2 text-secondary"></i>Tesis & Mekan</a></li>
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Personel') }}">
                            <i class="fas fa-id-badge me-2 text-info"></i>Personel</a></li>
                    {% elif s == 'isg' %}
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Tesis') }}">
                            <i class="fas fa-building-shield me-2 text-secondary"></i>Tesis & Mekan</a></li>
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Personel') }}">
                            <i class="fas fa-id-badge me-2 text-info"></i>Personel</a></li>
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Arac') }}">
                            <i class="fas fa-truck-fast me-2 text-warning"></i>Araç & Filo</a></li>
                    {% else %}
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Urun') }}">
                            <i class="fas fa-box-archive me-2 text-primary"></i>Üretim & Ürün</a></li>
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Arac') }}">
                            <i class="fas fa-truck-fast me-2 text-warning"></i>Araç & Filo</a></li>
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Personel') }}">
                            <i class="fas fa-id-badge me-2 text-info"></i>Personel</a></li>
                        <li><a class="dropdown-item rounded-2 py-2" href="{{ url_for('ekle', cat='Tesis') }}">
                            <i class="fas fa-building-shield me-2 text-secondary"></i>Tesis & Mekan</a></li>
                    {% endif %}
                </ul>
            </div>

            {# ── YENİLE + EXCEL DIŞA ── #}
            <div class="d-flex border rounded-3 bg-white shadow-sm overflow-hidden">
                <a href="{{ url_for('dashboard') }}"
                   class="btn border-0 rounded-0 px-3 fw-bold"
                   style="background:#1a1c4b; color:white;">
                    <i class="fas fa-sync me-1"></i> Yenile
                </a>
                <a href="{{ url_for('export_excel') }}"
                   class="btn btn-light border-0 rounded-0 px-3 border-start" title="Excel Rapor İndir">
                    <i class="fas fa-file-excel text-success fa-lg"></i>
                </a>
            </div>
        </div>
    </div>

    {# ── KPI KARTLARI ── #}
    <div class="row mb-4 g-3">
        <div class="col-md-4" onclick="filterTable('danger')">
            <div class="kpi-card danger">
                <div class="kpi-label">Kritik (Son 30 Gün)</div>
                <div class="kpi-value">
                    {{ sertifikalar | selectattr('expiry_date', 'le', bugun + timedelta(days=30)) | list | length }}
                </div>
            </div>
        </div>
        <div class="col-md-4" onclick="filterTable('warning')">
            <div class="kpi-card warning">
                <div class="kpi-label">Yaklaşan (1–3 Ay)</div>
                <div class="kpi-value">
                    {{ sertifikalar
                        | selectattr('expiry_date', 'gt', bugun + timedelta(days=30))
                        | selectattr('expiry_date', 'le', bugun + timedelta(days=90))
                        | list | length }}
                </div>
            </div>
        </div>
        <div class="col-md-4" onclick="filterTable('all')">
            <div class="kpi-card primary">
                <div class="kpi-label">Toplam Aktif Belge</div>
                <div class="kpi-value">{{ sertifikalar | length }}</div>
            </div>
        </div>
    </div>

    {# ── ANA TABLO ── #}
    <div class="data-card">
        <div class="table-responsive">
            <table class="table table-hover" id="sertifikaTable">
                <thead>
                    <tr>
                        <th class="ps-4" style="width:35%;">Belge / Tanım</th>
                        <th>Bitiş Tarihi</th>
                        <th>Kalan Gün</th>
                        <th class="text-center">Hızlı Aksiyon</th>
                        <th class="text-center">Dijital Arşiv</th>
                        <th class="text-center">İşlem</th>
                    </tr>
                </thead>
                <tbody>
                    {% for s in sertifikalar %}
                    {% if s.expiry_date %}
                    {% set kalan = (s.expiry_date - bugun).days %}
                    {% set status = 'danger' if kalan <= 30 else ('warning' if kalan <= 90 else 'success') %}
                    <tr class="table-row" data-status="{{ status }}">

                        <td class="ps-4">
                            <div class="belge-title">{{ s.title }}</div>
                            <div class="belge-meta">
                                <i class="fas fa-tag me-1"></i>
                                {% if s.category == 'Personel' %}Personel
                                {% elif s.category == 'Arac' %}Araç & Filo
                                {% elif s.category == 'Tesis' %}Tesis & Mekan
                                {% else %}Üretim & Ürün{% endif %}
                                {% if s.firma_adi %} · <i class="fas fa-building me-1"></i>{{ s.firma_adi }}{% endif %}
                                {% if s.note %} · {{ s.note }}{% endif %}
                            </div>
                        </td>

                        <td style="color:#64748b; font-weight:600; font-size:0.88rem;">
                            {{ s.expiry_date.strftime('%d.%m.%Y') }}
                        </td>

                        <td>
                            <span class="badge-days {{ status }}">
                                {% if kalan < 0 %}{{ kalan|abs }} Gün Geçti
                                {% elif kalan == 0 %}BUGÜN!
                                {% else %}{{ kalan }} Gün{% endif %}
                            </span>
                        </td>

                        <td class="text-center">
                            {% if kalan <= 30 %}
                            <div class="d-flex justify-content-center gap-1">
                                {% if s.danisman_no %}
                                <a href="https://wa.me/{{ s.danisman_no }}?text=Merhaba,%0A%0A'{{ s.title }}' belgesinin süresi 30 günün altına düşmüştür. Lütfen gerekli aksiyonu alın.%0ABitiş: {{ s.expiry_date.strftime('%d.%m.%Y') }}%0A%0AEG Optimal"
                                   target="_blank" class="btn-action" title="{% if s.category == 'Personel' %}Amire Hatırlat{% else %}Sorumluya Hatırlat{% endif %}"
                                   style="color:#0891b2;">
                                    <i class="fas fa-user-clock"></i>
                                </a>
                                {% endif %}
                                {% if s.whatsapp_no %}
                                <a href="https://wa.me/{{ s.whatsapp_no }}?text=Sayın ilgili,%0A%0A'{{ s.title }}' belgenizin süresi dolmak üzeredir.%0ABitiş: {{ s.expiry_date.strftime('%d.%m.%Y') }}%0A%0A{{ current_user.company_name or 'EG Optimal' }}"
                                   target="_blank" class="btn-action" title="{% if s.category == 'Personel' %}Personele Hatırlat{% else %}Müşteriye Hatırlat{% endif %}"
                                   style="color:#16a34a;">
                                    <i class="fab fa-whatsapp"></i>
                                </a>
                                {% endif %}
                            </div>
                            {% else %}
                            <span class="text-muted small">—</span>
                            {% endif %}
                        </td>

                        <td class="text-center">
                            {% if s.belge_url %}
                            <a href="{{ cloudinary_belge_url(s.belge_url) }}" target="_blank"
                               class="btn btn-sm fw-bold px-3"
                               style="background:#f0f4ff; color:#1a1c4b; border:1px solid #c7d2fe; border-radius:8px; font-size:0.78rem;">
                                <i class="fas fa-file-pdf me-1 text-danger"></i> Aç
                            </a>
                            {% else %}
                            <form action="{{ url_for('upload_belge', entry_id=s.id, cat=current_cat) }}"
                                  method="POST" enctype="multipart/form-data" class="m-0">
                                <label style="cursor:pointer;" title="Belge Yükle"
                                       class="btn btn-sm px-3"
                                       style="background:#f8fafc; border:1px dashed #cbd5e1; border-radius:8px; font-size:0.78rem; color:#94a3b8;">
                                    <i class="fas fa-cloud-upload-alt me-1"></i> Yükle
                                    <input type="file" name="file" onchange="this.form.submit()" style="display:none;">
                                </label>
                            </form>
                            {% endif %}
                        </td>

                        <td class="text-center">
                            <div class="d-flex justify-content-center gap-1">
                                <div class="dropdown">
                                    <button class="btn-action dropdown-toggle" style="color:#64748b; font-size:0.82rem;"
                                            data-bs-toggle="dropdown">
                                        <i class="fas fa-folder-open"></i>
                                    </button>
                                    <ul class="dropdown-menu dropdown-menu-end shadow border-0" style="border-radius:10px; font-size:0.85rem;">
                                        <li class="dropdown-header text-muted" style="font-size:0.7rem;">Kategoriye Taşı</li>
                                        <li><a class="dropdown-item py-2" href="{{ url_for('kategori_guncelle', id=s.id, yeni_kat='Arac') }}"><i class="fas fa-truck me-2 text-warning"></i>Araç & Filo</a></li>
                                        <li><a class="dropdown-item py-2" href="{{ url_for('kategori_guncelle', id=s.id, yeni_kat='Tesis') }}"><i class="fas fa-industry me-2 text-secondary"></i>Tesis & Mekan</a></li>
                                        <li><a class="dropdown-item py-2" href="{{ url_for('kategori_guncelle', id=s.id, yeni_kat='Urun') }}"><i class="fas fa-box me-2 text-primary"></i>Üretim & Ürün</a></li>
                                        <li><a class="dropdown-item py-2" href="{{ url_for('kategori_guncelle', id=s.id, yeni_kat='Personel') }}"><i class="fas fa-user me-2 text-info"></i>Personel</a></li>
                                    </ul>
                                </div>
                                <a href="{{ url_for('sil', id=s.id, cat=current_cat) }}"
                                   class="btn-action danger-hover" style="color:#cbd5e1;"
                                   onclick="return confirm('Bu belgeyi silmek istediğinize emin misiniz?')">
                                    <i class="fas fa-trash-alt"></i>
                                </a>
                            </div>
                        </td>
                    </tr>
                    {% endif %}
                    {% endfor %}

                    {% if sertifikalar | length == 0 %}
                    <tr>
                        <td colspan="6" class="text-center py-5">
                            <i class="fas fa-inbox fa-3x mb-3 d-block" style="color:#e2e8f0;"></i>
                            <span class="text-muted">Henüz kayıt yok. PDF yükleyerek veya manuel ekleyerek başlayın.</span>
                        </td>
                    </tr>
                    {% endif %}
                </tbody>
            </table>
        </div>
    </div>

</div>

<script>
function filterTable(status) {
    document.querySelectorAll('.table-row').forEach(row => {
        row.style.display =
            (status === 'all' || row.dataset.status === status) ? '' : 'none';
    });
}

function submitPdfForm() {
    const input = document.getElementById('pdf_input');
    if (!input.files.length) return;

    const total = input.files.length;
    const overlay = document.getElementById('pdfProgress');
    const bar = document.getElementById('progressBar');
    const countEl = document.getElementById('progressCount');
    const titleEl = document.getElementById('progressTitle');
    const subEl = document.getElementById('progressSub');

    overlay.classList.add('show');
    titleEl.textContent = total + ' PDF Analiz Ediliyor';
    subEl.textContent = 'Gemini AI belgelerinizi okuyor, lütfen bekleyin...';

    // Sahte ilerleme göster (gerçek işlem sunucuda)
    let pct = 0;
    const interval = setInterval(() => {
        pct = Math.min(pct + Math.random() * 8, 90);
        bar.style.width = pct + '%';
        countEl.textContent = Math.floor(pct / 100 * total) + ' / ' + total + ' belge işlendi';
    }, 600);

    // Formu gönder
    document.getElementById('pdfForm').submit();
}

// Drag & drop (opsiyonel görsel destek)
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));
});
</script>
{% endblock %}



# ============================================================
# ADMİN PANELİ
# ============================================================
@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    try:
        tum_kullanicilar  = User.query.all()
        odeme_yapmayanlar = User.query.filter_by(is_paid=False).all()
        tum_belgeler      = Entry.query.filter_by(is_active=True)\
                                 .order_by(Entry.expiry_date.asc()).all()
        kullanici_belge   = {u.id: Entry.query.filter_by(user_id=u.id, is_active=True).count()
                             for u in tum_kullanicilar}
    except Exception as e:
        print(f"Admin sorgu hatasi: {e}")
        tum_kullanicilar = odeme_yapmayanlar = tum_belgeler = []
        kullanici_belge = {}

    return render_template(
        'admin.html',
        users             = tum_kullanicilar,
        all_entries       = tum_belgeler,
        kullanici_belge   = kullanici_belge,
        odeme_yapmayanlar = odeme_yapmayanlar,
        bugun             = date.today()
    )


@app.route('/update_payment/<int:uid>', methods=['GET', 'POST'])
@login_required
def update_payment(uid):
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    u = User.query.get(uid)
    if u:
        if request.method == 'POST':
            u.company_name = request.form.get('company_name', '')
            u.is_paid      = request.form.get('is_paid') in ['true', 'True', 'Odendi']
            u.admin_note   = request.form.get('admin_note', '')
        else:
            u.is_paid = not u.is_paid
        db.session.commit()
        flash(f"{u.email} güncellendi.", "success")
    return redirect(url_for('admin_panel'))


@app.route('/delete_user/<int:uid>')
@login_required
def delete_user(uid):
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    u = User.query.get(uid)
    if u:
        Entry.query.filter_by(user_id=uid).delete()
        db.session.delete(u)
        db.session.commit()
        flash("Kullanıcı silindi.", "success")
    return redirect(url_for('admin_panel'))


# ============================================================
# OTOMATİK HATIRLATMA (Cron)
# ─────────────────────────────────────────────────────────────
# cron-job.org'da SADECE BU endpoint'i çağırın:
#   https://sertifika-takip.onrender.com/cron/check_reminders
# Sıklık: Her gün sabah 09:00 (Türkiye = UTC+3, yani UTC 06:00)
# ============================================================
@app.route('/cron/check_reminders')
@app.route('/cron/9am_check')
def check_reminders():
    # Güvenlik: Sadece cron-job.org'dan veya doğrudan çağrılabilir
    # İsterseniz bir secret token ekleyebilirsiniz
    try:
        bugun    = date.today()
        kayitlar = Entry.query.filter_by(is_active=True).all()
        gonderr  = 0
        hatalar  = 0

        for e in kayitlar:
            if not e.expiry_date:
                continue
            kalan = (e.expiry_date - bugun).days
            if kalan in [180, 90, 30, 15, 7, 1, 0]:
                user = User.query.get(e.user_id)
                if not user:
                    continue

                # Belge durumuna göre konu
                if kalan == 0:
                    konu = f"🚨 BUGÜN Süresi Doluyor: {e.title}"
                    mesaj_on = "BU BELGE BUGÜN SONA ERIYOR"
                elif kalan <= 7:
                    konu = f"🔴 ACİL - {kalan} Gün Kaldı: {e.title}"
                    mesaj_on = f"Acil! Sadece {kalan} gün kaldı"
                elif kalan <= 30:
                    konu = f"⚠️ {kalan} Gün Kaldı: {e.title}"
                    mesaj_on = f"Dikkat: {kalan} gün kaldı"
                else:
                    konu = f"📋 Hatırlatma: {e.title} ({kalan} Gün)"
                    mesaj_on = f"{kalan} gün kaldı"

                body = (
                    f"Sayın {user.company_name or user.email},\n\n"
                    f"{mesaj_on}!\n\n"
                    f"📄 Belge: {e.title}\n"
                    f"🏢 Firma: {e.firma_adi or '-'}\n"
                    f"📅 Bitiş Tarihi: {e.expiry_date.strftime('%d.%m.%Y')}\n"
                    f"⏳ Kalan Süre: {kalan} gün\n\n"
                    f"Panele erişmek için:\n"
                    f"https://sertifika-takip.onrender.com/dashboard\n\n"
                    f"Saygılarımızla,\nEG Optimal Belge Takip Sistemi"
                )

                basari = send_mail(user.email, konu, body)
                if basari:
                    gonderr += 1
                else:
                    hatalar += 1

        return jsonify({
            "durum": "OK",
            "tarih": str(bugun),
            "gonderilen": gonderr,
            "hata": hatalar,
            "toplam_kontrol": len(kayitlar)
        }), 200

    except Exception as e:
        print(f"Cron hatasi: {e}")
        return jsonify({"durum": "HATA", "mesaj": str(e)}), 500


# ============================================================
# KATEGORİ GÜNCELLE / TAŞI
# ============================================================
@app.route('/kategori_guncelle/<int:id>/<string:yeni_kat>')
@login_required
def kategori_guncelle(id, yeni_kat):
    item = Entry.query.get_or_404(id)
    item.category = yeni_kat
    db.session.commit()
    flash(f'Belge başarıyla {yeni_kat} kategorisine taşındı.', 'success')
    return redirect(url_for('dashboard'))


# ============================================================
# PING — Render'ı uyandırmak için (cron'dan önce çağrılır)
# ============================================================
@app.route('/ping')
def ping():
    return "pong", 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

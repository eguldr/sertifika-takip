import os
import re
import time
import json
import base64
import hashlib
import asyncio
import threading

import cloudinary
import cloudinary.uploader
import requests
import pandas as pd

from google import genai
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
from io import BytesIO
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import text

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

client = genai.Client(api_key=os.environ.get('GEMINI_API_KEY'))

cloudinary.config(
    cloud_name='dh2pefkko',
    api_key='626365126779241',
    api_secret='A1q12Oiih6Gc6PfKdPFextUsm-l',
    secure=True
)

BREVO_API_KEY     = os.environ.get('BREVO_API_KEY', '')
BREVO_SENDER_MAIL = os.environ.get('BREVO_SENDER_MAIL', 'eguldr@gmail.com')
BREVO_SENDER_NAME = 'EG Optimal'

PDF_PROMPT = (
    "Bu belgeyi dikkatle incele ve asagidaki bilgileri cikar. "
    "Sadece belgede ACIKCA yazan bilgileri yaz. Goremediklerini null yaz.\n\n"
    "Yaniti SADECE su JSON formatinda ver, baska hicbir sey yazma:\n"
    "{\n"
    '  "belge_turu": "Belgenin tam adi (orn: Arac Muayenesi, SRC 3 Belgesi, Kasko Sigortasi)",\n'
    '  "kategori": "Sadece: Arac, Personel, Tesis veya Urun",\n'
    '  "ad_soyad": "Belge sahibi kisi adi - SADECE belge sahibi, duzenleyen degil (yoksa null)",\n'
    '  "tc_no": "TC kimlik numarasi (yoksa null)",\n'
    '  "plaka": "Arac plakasi (yoksa null)",\n'
    '  "arac_marka": "Arac markasi (yoksa null)",\n'
    '  "arac_model": "Arac modeli (yoksa null)",\n'
    '  "sase_no": "Sase/VIN numarasi (yoksa null)",\n'
    '  "firma_adi": "Aracin veya belgenin bagli oldugu firma/kurum adi (yoksa null)",\n'
    '  "bitis_tarihi": "GG.AA.YYYY formatinda bitis tarihi (yoksa null)"\n'
    "}"
)


class User(UserMixin, db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(100), unique=True, nullable=False)
    password     = db.Column(db.String(256), nullable=False)
    company_name = db.Column(db.String(100), default='')
    is_confirmed = db.Column(db.Boolean, default=False)
    is_paid      = db.Column(db.Boolean, default=False)
    admin_note   = db.Column(db.Text, default='')
    kvkk_onay    = db.Column(db.Boolean, default=False)
    sektor       = db.Column(db.String(50), default='genel')


class Entry(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, nullable=False)
    category    = db.Column(db.String(50))
    title       = db.Column(db.String(200))
    firma_adi   = db.Column(db.String(100))
    expiry_date = db.Column(db.Date)
    belge_url   = db.Column(db.String(500))
    whatsapp_no = db.Column(db.String(20))
    danisman_no = db.Column(db.String(20))
    note        = db.Column(db.Text)
    is_active   = db.Column(db.Boolean, default=True)
    dosya_hash  = db.Column(db.String(64))
    dosya_adi   = db.Column(db.String(200))


class PersonelRehberi(db.Model):
    """Personel/firma telefon rehberi - PDF eslesme icin"""
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, nullable=False)
    ad_soyad    = db.Column(db.String(150))
    tc_no       = db.Column(db.String(20))
    plaka       = db.Column(db.String(20))
    firma_adi   = db.Column(db.String(150))
    whatsapp_no = db.Column(db.String(20))
    danisman_no = db.Column(db.String(20))
    aciklama    = db.Column(db.String(200))
    is_active   = db.Column(db.Boolean, default=True)


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
                "ALTER TABLE entry ADD COLUMN IF NOT EXISTS dosya_adi VARCHAR(200)",
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


def send_mail(to, subject, body):
    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
            json={
                "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_MAIL},
                "to": [{"email": to}],
                "subject": subject,
                "textContent": body
            },
            timeout=15
        )
        print(f"Brevo: {response.status_code}")
        return response.status_code == 201
    except Exception as e:
        print(f"Mail hatasi: {e}")
        return False


def send_verification_mail(email, token):
    verify_url = url_for('verify_email', token=token, _external=True)
    body = (
        "Merhaba,\n\nEG Optimal'e kayit oldugunuz icin tesekkurler!\n\n"
        f"Hesabinizi aktifleştirmek icin:\n\n{verify_url}\n\n"
        "Bu baglanti 24 saat gecerlidir.\n\nEG Optimal Ekibi"
    )
    return send_mail(email, "EG Optimal - E-posta Dogrulama", body)


def cloudinary_belge_url(url, dosya_adi=None):
    """PDF'leri tarayicida ac, Android icin dogru dosya adiyla indir"""
    if not url:
        return url
    if not url.lower().endswith(".pdf") and 'raw/upload' not in url:
        return url
    # fl_inline: tarayicide ac; fl_attachment: indir
    # Hem acmak hem indirmek icin fl_inline kullan, dosya adini ekle
    if "/fl_inline/" in url or "/fl_attachment/" in url:
        return url
    if dosya_adi:
        # Dosya adini URL-safe yap
        temiz_ad = re.sub(r'[^a-zA-Z0-9._-]', '_', dosya_adi)
        return re.sub(r'(/upload/)', r'\1fl_inline,fl_attachment:' + temiz_ad + '/', url, count=1)
    return re.sub(r'(/upload/)', r'\1fl_inline/', url, count=1)


app.jinja_env.globals['cloudinary_belge_url'] = cloudinary_belge_url


def rehber_eslestir(user_id, veri):
    """PDF verisindeki isim/plaka/firma ile rehberi eslestirir, telefon dondurur"""
    whatsapp = None
    danisman = None
    try:
        plaka    = str(veri.get('plaka') or '').replace('null','').strip().upper()
        ad_soyad = str(veri.get('ad_soyad') or '').replace('null','').strip().upper()
        tc_no    = str(veri.get('tc_no') or '').replace('null','').strip()
        firma    = str(veri.get('firma_adi') or '').replace('null','').strip().upper()
        print(f"REHBER ARAMA: plaka={plaka} ad={ad_soyad} tc={tc_no}")

        kayit = None
        if plaka:
            print(f"PLAKA SORGU: '{plaka}'")
            tum_rehber = PersonelRehberi.query.filter_by(user_id=user_id, is_active=True).all()
            print(f"REHBERDEKI PLAKALAR: {[r.plaka for r in tum_rehber]}")
            kayit = PersonelRehberi.query.filter(
                PersonelRehberi.user_id == user_id,
                PersonelRehberi.is_active == True,
                db.func.upper(PersonelRehberi.plaka) == plaka
            ).first()
        # 1. Plaka ile esles (arac belgeleri)
        if plaka:
            kayit = PersonelRehberi.query.filter(
                PersonelRehberi.user_id == user_id,
                PersonelRehberi.is_active == True,
                db.func.upper(PersonelRehberi.plaka) == plaka
            ).first()

        # 2. TC ile esles
        if not kayit and tc_no and len(tc_no) >= 10:
            kayit = PersonelRehberi.query.filter(
                PersonelRehberi.user_id == user_id,
                PersonelRehberi.is_active == True,
                PersonelRehberi.tc_no == tc_no
            ).first()

        # 3. Ad soyad ile esles
        if not kayit and ad_soyad and len(ad_soyad) > 3:
            kayit = PersonelRehberi.query.filter(
                PersonelRehberi.user_id == user_id,
                PersonelRehberi.is_active == True,
                db.func.upper(PersonelRehberi.ad_soyad).contains(ad_soyad[:8])
            ).first()

        # 4. Firma adi ile esles (ISG/sertifika)
        if not kayit and firma and len(firma) > 3:
            kayit = PersonelRehberi.query.filter(
                PersonelRehberi.user_id == user_id,
                PersonelRehberi.is_active == True,
                db.func.upper(PersonelRehberi.firma_adi).contains(firma[:10])
            ).first()

        if kayit:
            whatsapp = kayit.whatsapp_no
            danisman = kayit.danisman_no
            
            print(f"Rehber eslesti: {kayit.ad_soyad or kayit.plaka} -> wp={kayit.whatsapp_no} dan={kayit.danisman_no}")
    except Exception as e:
        print(f"Rehber eslestirme hatasi: {e}")

    return whatsapp, danisman


def akilli_analiz_motoru(satir):
    txt = " ".join([str(v) for v in satir]).lower()
    if any(k in txt for k in ['src', 'ehliyet', 'psikoteknik', 'sofor', 'personel', 'isg', 'vinc', 'pasaport', 'vize', 'ikamet']):
        return 'Personel'
    if any(k in txt for k in ['plaka', 'muayene', 'kamyon', 'arac', 'kasko', 'emisyon', 'takograf', 'trafik sigorta', 'sase']):
        return 'Arac'
    if any(k in txt for k in ['yangin', 'tesis', 'itfaiye', 'ruhsat', 'cevre', 'asansor', 'otel', 'konaklama']):
        return 'Tesis'
    return 'Urun'


def tarih_parse(bitis_str):
    if not bitis_str or str(bitis_str) == 'null':
        return date.today() + timedelta(days=365)
    for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
        try:
            return datetime.strptime(str(bitis_str), fmt).date()
        except Exception:
            continue
    return date.today() + timedelta(days=365)


# ============================================================
# ASYNC PDF MOTORU - Tier 1 (1000 RPM)
# ============================================================
async def tek_pdf_isle(semaphore, dosya_verisi):
    async with semaphore:
        ad   = dosya_verisi['ad']
        b64  = dosya_verisi['b64']
        mime = dosya_verisi['mime']
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.5-flash",
                contents=[{"parts": [
                    {"inline_data": {"mime_type": mime, "data": b64}},
                    {"text": PDF_PROMPT}
                ]}]
            )
            yanit = response.text.strip().replace('```json', '').replace('```', '').strip()
            try:
                veri = json.loads(yanit)
                return {"ad": ad, "hash": dosya_verisi['hash'],
                        "icerik": dosya_verisi['icerik'], "veri": veri, "hata": None}
            except json.JSONDecodeError:
                return {"ad": ad, "hash": dosya_verisi['hash'],
                        "icerik": dosya_verisi['icerik'], "hata": "json_parse"}
        except Exception as e:
            hata = str(e)
            if '429' in hata or 'EXHAUSTED' in hata:
                await asyncio.sleep(5)
            elif '503' in hata or 'UNAVAILABLE' in hata:
                await asyncio.sleep(10)
            return {"ad": ad, "hash": dosya_verisi['hash'],
                    "icerik": dosya_verisi['icerik'], "hata": hata}


async def toplu_pdf_isle(dosya_listesi, paralel_sayi=20):
    semaphore = asyncio.Semaphore(paralel_sayi)
    gorevler  = [tek_pdf_isle(semaphore, d) for d in dosya_listesi]
    return await asyncio.gather(*gorevler, return_exceptions=True)


# ============================================================
# AUTH
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
            if not u.is_confirmed and u.email != 'erhanadea@gmail.com':
                flash("Lutfen once e-postanizi dogrulayin.", "warning")
                return redirect(url_for('login'))
            login_user(u)
            return redirect(url_for('dashboard'))
        flash("E-posta veya sifre hatali.", "danger")
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
        if request.form.get('robot_kontrol', '').strip() != '5':
            flash("Robot kontrolu basarisiz.", "danger")
            return redirect(url_for('register'))
        if not request.form.get('kvkk_onay'):
            flash("KVKK metnini onaylamaniz gerekmektedir.", "danger")
            return redirect(url_for('register'))
        email = request.form.get('email', '').strip()
        if User.query.filter_by(email=email).first():
            flash("Bu e-posta zaten kayitli.", "warning")
            return redirect(url_for('register'))
        u = User(
            email=email,
            password=generate_password_hash(request.form.get('password', '')),
            company_name=request.form.get('company_name', ''),
            is_confirmed=False, is_paid=False, kvkk_onay=True,
            sektor=request.form.get('sektor', 'genel')
        )
        db.session.add(u)
        db.session.commit()
        token = ts.dumps(email, salt='email-confirm-key')
        if send_verification_mail(email, token):
            flash("Kayit basarili! Dogrulama maili gonderildi.", "success")
        else:
            flash("Kayit basarili ancak dogrulama maili gonderilemedi.", "warning")
        return redirect(url_for('login'))
    return render_template('kayit.html')


@app.route('/verify_email/<token>')
def verify_email(token):
    try:
        email = ts.loads(token, salt='email-confirm-key', max_age=86400)
    except Exception:
        flash("Dogrulama linki gecersiz.", "danger")
        return redirect(url_for('login'))
    user = User.query.filter_by(email=email).first()
    if user:
        user.is_confirmed = True
        db.session.commit()
        flash("E-postaniz dogrulandi! Giris yapabilirsiniz.", "success")
    return redirect(url_for('login'))


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user  = User.query.filter_by(email=email).first()
        if user:
            token = ts.dumps(email, salt='recover-key')
            recover_url = url_for('reset_password', token=token, _external=True)
            send_mail(email, "Sifre Sifirlama - EG Optimal",
                      f"Sifrenizi sifirlamak icin:\n\n{recover_url}\n\n30 dakika gecerlidir.\n\nEG Optimal")
        flash("Sifirlama baglantisi gonderildi.", "info")
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = ts.loads(token, salt='recover-key', max_age=1800)
    except Exception:
        flash("Link gecersiz.", "danger")
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        user = User.query.filter_by(email=email).first()
        if user:
            user.password = generate_password_hash(request.form.get('password', ''))
            db.session.commit()
            flash("Sifreniz guncellendi.", "success")
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
        sorgu = Entry.query.filter(Entry.is_active == True, Entry.user_id == current_user.id)
        if cat and cat != 'all':
            sorgu = sorgu.filter(Entry.category == cat)
        liste = sorgu.order_by(Entry.expiry_date.asc()).all()
    except Exception as e:
        print(f"Dashboard hatasi: {e}")
        liste = []
    return render_template('dashboard.html',
        sertifikalar=liste, bugun=date.today(),
        timedelta=timedelta, current_cat=cat or 'all'
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
        if title == 'LISTEDE YOK / MANUEL YAZ':
            title = request.form.get('manual_title', '').strip()
        exp_str = request.form.get('expiry_date', '')
        try:
            expiry = datetime.strptime(exp_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            flash('Gecerli bir tarih giriniz.', 'danger')
            return render_template('ekle.html', cat=cat)
        try:
            db.session.add(Entry(
                user_id=current_user.id, category=cat, title=title,
                firma_adi=request.form.get('firma_adi', '').strip(),
                whatsapp_no=request.form.get('whatsapp_no', '').strip(),
                danisman_no=request.form.get('danisman_no', '').strip(),
                note=request.form.get('note', '').strip(),
                expiry_date=expiry, is_active=True
            ))
            db.session.commit()
            flash(f'{title} basariyla takibe alindi!', 'success')
            return redirect(url_for('dashboard', cat=cat))
        except Exception as e:
            db.session.rollback()
            flash(f'Kayit hatasi: {str(e)}', 'danger')
    return render_template('ekle.html', cat=cat)


# ============================================================
# SIL
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
            flash("Kayit silindi.", "success")
        else:
            flash("Yetki hatasi.", "danger")
    except Exception as ex:
        flash(f"Silme hatasi: {ex}", "danger")
    return redirect(url_for('dashboard', cat=cat))


# ============================================================
# CLOUDINARY BELGE YUKLEME
# ============================================================
@app.route('/upload_belge/<int:entry_id>', methods=['POST'])
@login_required
def upload_belge(entry_id):
    f   = request.files.get('file')
    cat = request.args.get('cat', 'all')
    if f:
        try:
            dosya_adi_temiz = re.sub(r'[^a-zA-Z0-9._-]', '_', f.filename)
            res = cloudinary.uploader.unsigned_upload(
                f, upload_preset='erhan_preset', resource_type='raw'
            )
            e = Entry.query.get(entry_id)
            if e and (e.user_id == current_user.id or current_user.email == 'erhanadea@gmail.com'):
                raw_url = res.get('secure_url')
                if not raw_url:
                    raise Exception("URL alinamadi")
                e.belge_url = cloudinary_belge_url(raw_url, dosya_adi_temiz)
                e.dosya_adi = f.filename
                db.session.commit()
                flash("Belge yuklendi.", "success")
            else:
                flash("Yetki hatasi.", "danger")
        except Exception as ex:
            flash(f"Yukleme hatasi: {ex}", "danger")
    else:
        flash("Dosya secin.", "warning")
    return redirect(url_for('dashboard', cat=cat))


# ============================================================
# EXCEL ICE AKTAR
# ============================================================
@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if not f:
        flash("Dosya secilmedi.", "warning")
        return redirect(url_for('dashboard'))
    try:
        Entry.query.filter_by(user_id=current_user.id).update({'is_active': False})
        db.session.commit()
        df = pd.read_excel(f)
        df.columns = [str(c).strip() for c in df.columns]

        def find_col(kw):
            for col in df.columns:
                if any(k in col.lower() for k in kw):
                    return col
            return None

        title_col = find_col(['belge', 'plaka', 'isim', 'ad', 'tanim', 'title'])
        firma_col = find_col(['firma', 'kurum', 'sirket', 'company'])
        tarih_col = find_col(['bitis', 'tarih', 'expiry', 'gecerlilik'])

        eklenen = 0
        for _, r in df.iterrows():
            cat    = akilli_analiz_motoru(list(r.values))
            title  = str(r[title_col]).strip() if title_col and pd.notna(r.get(title_col)) else str(r.iloc[0])
            firma  = str(r[firma_col]).strip() if firma_col and pd.notna(r.get(firma_col)) else ''
            expiry = date.today() + timedelta(days=365)
            if tarih_col and pd.notna(r.get(tarih_col)):
                try:
                    expiry = pd.to_datetime(r[tarih_col], dayfirst=True).date()
                except Exception:
                    pass
            db.session.add(Entry(user_id=current_user.id, category=cat, title=title,
                                 firma_adi=firma, expiry_date=expiry, is_active=True))
            eklenen += 1
        db.session.commit()
        flash(f"Excel yuklendi. {eklenen} kayit eklendi.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Excel hatasi: {str(e)}", "danger")
    return redirect(url_for('dashboard'))


# ============================================================
# BACKGROUND THREAD - JOB TAKIP SISTEMI
# ============================================================
# { job_id: { 'durum': 'isleniyor'|'tamamlandi'|'hata',
#             'toplam': N, 'tamamlanan': N,
#             'eklenen': N, 'hatali': N, 'atlanan': N,
#             'user_id': X } }
pdf_jobs = {}
pdf_jobs_lock = threading.Lock()


def arka_plan_isle(job_id, islenecekler, user_id, atlanan):
    """Background thread: Gemini'ye gonder, DB'ye kaydet."""
    with app.app_context():
        try:
            # Async motoru thread icinde calistir
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            sonuclar = loop.run_until_complete(
                toplu_pdf_isle(islenecekler, paralel_sayi=10)
            )
            loop.close()

            eklenen     = 0
            hatali      = 0
            hata_listesi = []

            for i, sonuc in enumerate(sonuclar):
                # Progress guncelle
                with pdf_jobs_lock:
                    pdf_jobs[job_id]['tamamlanan'] = i + 1

                if isinstance(sonuc, Exception) or sonuc.get('hata'):
                    hatali += 1
                    hata_listesi.append(sonuc.get('ad', 'Bilinmeyen dosya'))
                    continue

                veri   = sonuc.get('veri', {})
                icerik = sonuc.get('icerik', b'')
                d_hash = sonuc.get('hash', '')
                ad     = sonuc.get('ad', '')

                kat = veri.get('kategori', 'Urun')
                if kat not in ['Arac', 'Personel', 'Tesis', 'Urun']:
                    kat = akilli_analiz_motoru([veri.get('belge_turu', '')])

                # Guven skoru
                guven = 0
                if veri.get('belge_turu') and str(veri.get('belge_turu')) != 'null': guven += 25
                if veri.get('bitis_tarihi') and str(veri.get('bitis_tarihi')) != 'null': guven += 35
                if kat in ['Arac', 'Personel', 'Tesis', 'Urun']: guven += 20
                if veri.get('firma_adi') and str(veri.get('firma_adi')) != 'null': guven += 10
                if veri.get('ad_soyad') or veri.get('plaka'): guven += 10
                if guven < 60:
                    print(f"DUSUK GUVEN ({guven}%): {ad}")
                    veri['belge_turu'] = f"[KONTROL ET] {veri.get('belge_turu') or ad}"

                notlar = []
                for k, prefix in [('ad_soyad',''), ('tc_no','TC: '), ('plaka','Plaka: '),
                                   ('arac_marka',''), ('arac_model',''), ('sase_no','Sase: ')]:
                    v = veri.get(k)
                    if v and str(v) != 'null':
                        notlar.append(f"{prefix}{v}")

                belge_url = None
                dosya_adi_temiz = re.sub(r'[^a-zA-Z0-9._-]', '_', ad)
                try:
                    res = cloudinary.uploader.unsigned_upload(
                        BytesIO(icerik), upload_preset='erhan_preset',
                        resource_type='raw', public_id=f"belge_{d_hash[:8]}"
                    )
                    raw_url = res.get('secure_url', '')
                    belge_url = cloudinary_belge_url(raw_url, dosya_adi_temiz) if raw_url else None
                except Exception as ce:
                    print(f"Cloudinary hatasi ({ad}): {ce}")

                firma = str(veri.get('firma_adi') or '').replace('null', '').strip()

                # Rehber eslestirme - telefon numarasini otomatik ata
                r_whatsapp, r_danisman = rehber_eslestir(int(user_id), veri)

                try:
                    db.session.add(Entry(
                        user_id=user_id, category=kat,
                        title=veri.get('belge_turu') or ad,
                        firma_adi=firma,
                        expiry_date=tarih_parse(veri.get('bitis_tarihi')),
                        note=' | '.join(notlar) if notlar else ad,
                        belge_url=belge_url, dosya_hash=d_hash,
                        dosya_adi=ad, is_active=True,
                        whatsapp_no=r_whatsapp,
                        danisman_no=r_danisman
                    ))
                    db.session.commit()
                    eklenen += 1
                except Exception as dbe:
                    db.session.rollback()
                    print(f"DB hatasi ({ad}): {dbe}")
                    hatali += 1

            with pdf_jobs_lock:
                pdf_jobs[job_id].update({
                    'durum': 'tamamlandi',
                    'eklenen': eklenen,
                    'hatali': hatali,
                    'hata_listesi': hata_listesi,
                    'atlanan': atlanan,
                    'tamamlanan': len(islenecekler)
                })
            print(f"Job {job_id} tamamlandi: {eklenen} eklendi, {hatali} hatali")

        except Exception as e:
            print(f"Arka plan hatasi (job {job_id}): {e}")
            with pdf_jobs_lock:
                pdf_jobs[job_id]['durum'] = 'hata'


# ============================================================
# PDF TOPLU OKUMA - BACKGROUND THREAD
# ============================================================
@app.route('/import_pdf', methods=['POST'])
@login_required
def import_pdf():
    dosyalar = request.files.getlist('pdf_files')
    if not dosyalar or all(f.filename == '' for f in dosyalar):
        flash("En az bir dosya secin.", "warning")
        return redirect(url_for('dashboard'))

    islenecekler = []
    atlanan = 0

    for dosya in dosyalar:
        if not dosya or dosya.filename == '':
            continue
        icerik = dosya.read()
        if not icerik:
            continue
        d_hash = hashlib.md5(icerik).hexdigest()
        if Entry.query.filter_by(user_id=current_user.id, dosya_hash=d_hash, is_active=True).first():
            atlanan += 1
            continue
        fname = dosya.filename.lower()
        mime  = 'image/png' if fname.endswith('.png') else ('image/jpeg' if fname.endswith(('.jpg', '.jpeg')) else 'application/pdf')
        islenecekler.append({
            'ad': dosya.filename, 'icerik': icerik,
            'b64': base64.standard_b64encode(icerik).decode(),
            'mime': mime, 'hash': d_hash
        })

    if not islenecekler:
        flash(f"Tum dosyalar zaten sistemde. ({atlanan} atlandi)", "info")
        return redirect(url_for('dashboard'))

    # Job olustur
    import uuid
    job_id = str(uuid.uuid4())[:8]
    with pdf_jobs_lock:
        pdf_jobs[job_id] = {
            'durum': 'isleniyor',
            'toplam': len(islenecekler),
            'tamamlanan': 0,
            'eklenen': 0,
            'hatali': 0,
            'atlanan': atlanan,
            'user_id': current_user.id
        }

    # Arka plan thread baslat
    t = threading.Thread(
        target=arka_plan_isle,
        args=(job_id, islenecekler, current_user.id, atlanan),
        daemon=True
    )
    t.start()

    print(f"Job {job_id} basladi: {len(islenecekler)} PDF arka planda isleniyor")
    flash(f"{len(islenecekler)} belge alindi, arka planda isleniyor. "
          f"Birkas dakika sonra sayfayi yenileyin.", "info")
    return redirect(url_for('dashboard', job_id=job_id))


@app.route('/job_durum/<job_id>')
@login_required
def job_durum(job_id):
    """Progress API - dashboard polling icin"""
    with pdf_jobs_lock:
        job = pdf_jobs.get(job_id)
    if not job:
        return jsonify({'durum': 'bulunamadi'})
    if job.get('user_id') != current_user.id:
        return jsonify({'durum': 'yetkisiz'})
    return jsonify(job)


# ============================================================
# EXCEL DISA AKTAR
# ============================================================
@app.route('/export_excel')
@login_required
def export_excel():
    try:
        entries = Entry.query.filter_by(is_active=True).all() if current_user.email == 'erhanadea@gmail.com' \
                  else Entry.query.filter_by(user_id=current_user.id, is_active=True).all()
        data = [{"Kategori": e.category, "Firma": e.firma_adi, "Belge Adi": e.title,
                 "Not": e.note, "Bitis Tarihi": e.expiry_date.strftime('%d.%m.%Y') if e.expiry_date else "",
                 "Belge URL": e.belge_url or ""} for e in entries]
        df     = pd.DataFrame(data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sertifikalar')
        output.seek(0)
        return send_file(output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True, download_name="EG_Optimal_Rapor.xlsx")
    except Exception as e:
        flash(f"Disa aktarim hatasi: {e}", "danger")
        return redirect(url_for('dashboard'))


# ============================================================
# ADMIN
# ============================================================
@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    try:
        tum_kullanicilar  = User.query.all()
        odeme_yapmayanlar = User.query.filter_by(is_paid=False).all()
        tum_belgeler      = Entry.query.filter_by(is_active=True).order_by(Entry.expiry_date.asc()).all()
        kullanici_belge   = {u.id: Entry.query.filter_by(user_id=u.id, is_active=True).count() for u in tum_kullanicilar}
    except Exception as e:
        print(f"Admin hatasi: {e}")
        tum_kullanicilar = odeme_yapmayanlar = tum_belgeler = []
        kullanici_belge = {}
    return render_template('admin.html',
        users=tum_kullanicilar, all_entries=tum_belgeler,
        kullanici_belge=kullanici_belge, odeme_yapmayanlar=odeme_yapmayanlar,
        bugun=date.today()
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
            u.sektor       = request.form.get('sektor', 'genel')
            print(f"SEKTOR GUNCELLE: {u.email} -> {u.sektor}")
        else:
            u.is_paid = not u.is_paid
        db.session.commit()
        flash(f"{u.email} guncellendi.", "success")
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
        flash("Kullanici silindi.", "success")
    return redirect(url_for('admin_panel'))


# ============================================================
# CRON
# Job 1: https://sertifika-takip.onrender.com/ping         08:55
# Job 2: https://sertifika-takip.onrender.com/cron/check_reminders  09:00
# ============================================================
@app.route('/ping')
def ping():
    return "pong", 200


@app.route('/cron/check_reminders')
@app.route('/cron/9am_check')
def check_reminders():
    try:
        bugun    = date.today()
        kayitlar = Entry.query.filter_by(is_active=True).all()
        gonderr  = 0
        hatalar  = 0
        for e in kayitlar:
            if not e.expiry_date:
                continue
            kalan = (e.expiry_date - bugun).days
            if kalan not in [180, 90, 30, 15, 7, 1, 0]:
                continue
            user = User.query.get(e.user_id)
            if not user:
                continue
            if kalan == 0:
                konu = f"BUGUN Suresi Doluyor: {e.title}"
            elif kalan <= 7:
                konu = f"ACIL {kalan} Gun Kaldi: {e.title}"
            elif kalan <= 30:
                konu = f"UYARI {kalan} Gun Kaldi: {e.title}"
            else:
                konu = f"Hatirlatma: {e.title} ({kalan} Gun)"
            body = (
                f"Sayin {user.company_name or user.email},\n\n"
                f"Belge: {e.title}\nFirma/Arac: {e.firma_adi or '-'}\n"
                f"Bitis: {e.expiry_date.strftime('%d.%m.%Y')}\nKalan: {kalan} gun\n\n"
                f"Panel: https://sertifika-takip.onrender.com/dashboard\n\nEG Optimal"
            )
            if send_mail(user.email, konu, body):
                gonderr += 1
            else:
                hatalar += 1
        return jsonify({"durum": "OK", "tarih": str(bugun),
                        "gonderilen": gonderr, "hata": hatalar, "toplam": len(kayitlar)}), 200
    except Exception as e:
        return jsonify({"durum": "HATA", "mesaj": str(e)}), 500



# ============================================================
# PERSONEL / FIRMA REHBERI
# ============================================================
@app.route('/rehber')
@login_required
def rehber():
    kayitlar = PersonelRehberi.query.filter_by(
        user_id=current_user.id, is_active=True
    ).order_by(PersonelRehberi.ad_soyad).all()
    return render_template('rehber.html', kayitlar=kayitlar)


@app.route('/rehber/ekle', methods=['POST'])
@login_required
def rehber_ekle():
    try:
        db.session.add(PersonelRehberi(
            user_id     = current_user.id,
            ad_soyad    = request.form.get('ad_soyad','').strip() or None,
            tc_no       = request.form.get('tc_no','').strip() or None,
            plaka       = request.form.get('plaka','').strip().upper() or None,
            firma_adi   = request.form.get('firma_adi','').strip() or None,
            whatsapp_no = request.form.get('whatsapp_no','').strip() or None,
            danisman_no = request.form.get('danisman_no','').strip() or None,
            aciklama    = request.form.get('aciklama','').strip() or None,
            is_active   = True
        ))
        db.session.commit()
        flash("Rehber kaydi eklendi.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Hata: {e}", "danger")
    return redirect(url_for('rehber'))


@app.route('/rehber/sil/<int:rid>')
@login_required
def rehber_sil(rid):
    r = PersonelRehberi.query.get_or_404(rid)
    if r.user_id == current_user.id:
        r.is_active = False
        db.session.commit()
        flash("Kayit silindi.", "success")
    return redirect(url_for('rehber'))


@app.route('/rehber/excel', methods=['POST'])
@login_required
def rehber_excel_yukle():
    """Excel ile toplu rehber yukleme"""
    f = request.files.get('rehber_excel')
    if not f:
        flash("Dosya secilmedi.", "warning")
        return redirect(url_for('rehber'))
    try:
        df = pd.read_excel(f)
        df.columns = [str(c).strip().lower() for c in df.columns]

        def col(keys):
            for c in df.columns:
                if any(k in c for k in keys):
                    return c
            return None

        ad_col       = col(['ad','isim','name','personel'])
        tc_col       = col(['tc','kimlik'])
        plaka_col    = col(['plaka','arac'])
        firma_col    = col(['firma','kurum','musteri','sirket'])
        wp_col       = col(['whatsapp','telefon','tel','gsm','personel_no','sorumlu'])
        dan_col      = col(['amir', 'yonetici', 'danisman', 'isg', 'uzman', 'filo'])
        acik_col     = col(['aciklama','not'])

        def val(row, c):
            if c and pd.notna(row.get(c)):
                v = str(row[c]).strip()
                return v if v and v.lower() != 'nan' else None
            return None

        eklenen = 0
        for _, row in df.iterrows():
            db.session.add(PersonelRehberi(
                user_id     = current_user.id,
                ad_soyad    = val(row, ad_col),
                tc_no       = val(row, tc_col),
                plaka       = val(row, plaka_col).upper() if val(row, plaka_col) else None,
                firma_adi   = val(row, firma_col),
                whatsapp_no = val(row, wp_col),
                danisman_no = val(row, dan_col),
                aciklama    = val(row, acik_col),
                is_active   = True
            ))
            eklenen += 1
        db.session.commit()
        flash(f"{eklenen} rehber kaydi yuklendi.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Excel hatasi: {e}", "danger")
    return redirect(url_for('rehber'))


@app.route('/rehber/sifirla')
@login_required
def rehber_sifirla():
    PersonelRehberi.query.filter_by(user_id=current_user.id).update({'is_active': False})
    db.session.commit()
    flash("Tum rehber kayitlari silindi.", "info")
    return redirect(url_for('rehber'))

# ============================================================
# TOPLU SIL
# ============================================================
@app.route('/toplu_sil', methods=['POST'])
@login_required
def toplu_sil():
    try:
        data = request.get_json()
        ids  = [int(i) for i in data.get('ids', [])]
        if not ids:
            return jsonify({'ok': False, 'hata': 'Secili belge yok'})
        silinen = 0
        for entry_id in ids:
            e = Entry.query.get(entry_id)
            if e and (e.user_id == current_user.id or current_user.email == 'erhanadea@gmail.com'):
                e.is_active = False
                silinen += 1
        db.session.commit()
        return jsonify({'ok': True, 'silinen': silinen})
    except Exception as ex:
        db.session.rollback()
        return jsonify({'ok': False, 'hata': str(ex)})

# ============================================================
# BELGE AC - PDF PROXY
# ============================================================
@app.route('/belge_ac/<int:entry_id>')
@login_required
def belge_ac(entry_id):
    e = Entry.query.get_or_404(entry_id)
    if e.user_id != current_user.id and current_user.email != 'erhanadea@gmail.com':
        return "Yetki hatasi", 403
    if not e.belge_url:
        return "Belge bulunamadi", 404
    try:
        temiz_url = re.sub(r'/fl_[^/]+/', '/', e.belge_url)
        temiz_url = re.sub(r'https:\/+', 'https://', temiz_url)
        r = requests.get(temiz_url, timeout=30)
        if r.status_code != 200:
            return f"Cloudinary hatasi: {r.status_code}", 500
        dosya_adi = (e.dosya_adi or 'belge.pdf').encode('ascii', 'ignore').decode()
        return send_file(
            BytesIO(r.content),
            mimetype='application/pdf',
            as_attachment=False,
            download_name=dosya_adi
        )
    except Exception as ex:
        return f"Hata: {str(ex)}", 500
# ============================================================
# KATEGORI GUNCELLE
# ============================================================
@app.route('/kategori_guncelle/<int:id>/<string:yeni_kat>')
@login_required
def kategori_guncelle(id, yeni_kat):
    item = Entry.query.get_or_404(id)
    item.category = yeni_kat
    db.session.commit()
    flash(f'Belge {yeni_kat} kategorisine tasindi.', 'success')
    return redirect(url_for('dashboard'))


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

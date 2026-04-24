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
    SECRET_KEY=os.environ.get('SECRET_KEY', 'eg_optimal_ultra_master_final_v2200_2026'),
    SECURITY_PASSWORD_SALT='eg_super_salt_secure_99_pro',
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME=os.environ.get('MAIL_USERNAME', 'erhanadea@gmail.com'),
    MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD', 'bwdxhwamvoggqdko'),
    MAIL_DEFAULT_SENDER=os.environ.get('MAIL_USERNAME', 'erhanadea@gmail.com')
)
 
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
 
db            = SQLAlchemy(app)
mail          = Mail(app)
ts            = URLSafeTimedSerializer(app.config['SECRET_KEY'])
login_manager = LoginManager(app)
login_manager.login_view = 'login'
 
cloudinary.config(
    cloud_name='dh2pefkk',
    api_key='414697559795627',
    api_secret='0q2xexoiKr25EeuI6CmFF8CXf2c'
)
 
 
# ============================================================
# VERİTABANI MODELLERİ
# ============================================================
class User(UserMixin, db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(100), unique=True, nullable=False)
    password     = db.Column(db.String(256), nullable=False)
    company_name = db.Column(db.String(100), default='')
    is_confirmed = db.Column(db.Boolean, default=True)
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
    danisman_no = db.Column(db.String(20))
    note        = db.Column(db.Text)
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
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_confirmed BOOLEAN DEFAULT TRUE',
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
def send_mail(to, subject, body):
    try:
        msg = Message(subject, recipients=[to])
        msg.body = body
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Mail hatasi: {e}")
        return False
 
 
def cloudinary_belge_url(url):
    """
    Cloudinary'den yüklenen PDF/belge URL'ini görüntülenebilir hale getirir.
    /upload/ → /upload/fl_attachment/ dönüşümü yapar.
    """
    if not url:
        return url
    # Zaten fl_attachment varsa dokunma
    if 'fl_attachment' in url:
        return url
    return url.replace('/upload/', '/upload/fl_attachment/', 1)
 
 
# Jinja2 template'lerinde kullanılabilmesi için global olarak tanıt
app.jinja_env.globals['cloudinary_belge_url'] = cloudinary_belge_url
 
 
def akilli_analiz_motoru(satir):
    """Excel satırından branş tespiti — isim kalıbı dahil."""
    txt = " ".join([str(v) for v in satir]).lower()
 
    personel_kw = ['src', 'ehliyet', 'operator', 'operatör', 'personel', 'sofor',
                   'sürücü', 'forklift', 'muhendis', 'teknisyen', 'isci', 'calisan',
                   'stajyer', 'mudur', 'uzman', 'güvenlik', 'bekci']
    isim_var = bool(re.search(
        r'[A-ZÇĞİÖŞÜ][a-zçğışöşü]+\s+[A-ZÇĞİÖŞÜ][a-zçğışöşü]+',
        " ".join([str(v) for v in satir])
    ))
    if any(k in txt for k in personel_kw) or isim_var:
        return 'Personel'
 
    if any(k in txt for k in ['plaka', 'muayene', 'trafik', 'scania', 'arac', 'araç',
                                'kamyon', 'tir', 'ford', 'mercedes', 'volvo', 'truck']):
        return 'Arac'
 
    if any(k in txt for k in ['yangin', 'yangın', 'tesis', 'bina', 'isg', 'periyodik',
                                'kapasite', 'depo', 'fabrika', 'kazan', 'asansor']):
        return 'Tesis'
 
    if any(k in txt for k in ['iso', 'kalite', 'haccp', 'ce belgesi', 'tse',
                                'uretim', 'üretim', 'gıda', 'helal', 'organik']):
        return 'Urun'
 
    return 'Genel'
 
 
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
            login_user(u)
            return redirect(url_for('dashboard'))
        flash("E-posta veya şifre hatalı.", "danger")
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
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')
 
        if User.query.filter_by(email=email).first():
            flash("Bu e-posta zaten kayıtlı.", "warning")
            return redirect(url_for('register'))
 
        u = User(
            email        = email,
            password     = generate_password_hash(password),
            company_name = request.form.get('company_name', ''),
            is_confirmed = True,
            is_paid      = False
        )
        db.session.add(u)
        db.session.commit()
        flash("Kayıt başarılı! Giriş yapabilirsiniz.", "success")
        return redirect(url_for('login'))
 
    return render_template('kayit.html')
 
 
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user  = User.query.filter_by(email=email).first()
        if user:
            token       = ts.dumps(email, salt='recover-key')
            recover_url = url_for('reset_password', token=token, _external=True)
            send_mail(email, "Şifre Sıfırlama - EG Optimal",
                      f"Şifrenizi sıfırlamak için:\n\n{recover_url}\n\n30 dakika geçerlidir.")
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
        # Her kullanıcı (admin dahil) yalnızca kendi belgelerini görür.
        # Admin tüm kullanıcıları admin_panel'den takip eder.
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
 
 
# Eski /sertifikalar/<cat> URL'ini yönlendir (geriye dönük uyumluluk)
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
            res = cloudinary.uploader.upload(f, resource_type="auto")
            e   = Entry.query.get(entry_id)
            if e and (e.user_id == current_user.id or current_user.email == 'erhanadea@gmail.com'):
                raw_url = res.get('secure_url', '')
                # PDF'lerin tarayıcıda açılabilmesi için fl_attachment ekle
                e.belge_url = cloudinary_belge_url(raw_url)
                db.session.commit()
                flash("Belge başarıyla yüklendi.", "success")
            else:
                flash("Yetki hatası.", "danger")
        except Exception as ex:
            flash(f"Yükleme hatası: {ex}", "danger")
    else:
        flash("Lütfen bir dosya seçin.", "warning")
    return redirect(url_for('dashboard', cat=cat))
 
 
# ============================================================
# EXCEL İÇE AKTAR
# ============================================================
@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if not f:
        flash("Dosya seçilmedi.", "warning")
        return redirect(url_for('dashboard'))
    try:
        # Mevcut kayıtları pasife çek
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
            cat = akilli_analiz_motoru(satirlar)
            
            if cat == 'Genel':
                pass 

            title = str(r[title_col]).strip() if title_col and pd.notna(r.get(title_col)) else str(r.iloc[0])
            firma = str(r[firma_col]).strip() if firma_col and pd.notna(r.get(firma_col)) else ''
            expiry = date.today() + timedelta(days=365)
            if tarih_col and pd.notna(r.get(tarih_col)):
                try:
                    expiry = pd.to_datetime(r[tarih_col], dayfirst=True).date()
                except:
                    pass

            db.session.add(Entry(
                user_id=current_user.id,
                category=cat,
                title=title,
                firma_adi=firma,
                expiry_date=expiry,
                is_active=True
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
        # Global Radar: tüm aktif belgeler (tüm kullanıcılar)
        tum_belgeler      = Entry.query.filter_by(is_active=True)\
                                 .order_by(Entry.expiry_date.asc()).all()
        kullanici_belge   = {u.id: Entry.query.filter_by(user_id=u.id, is_active=True).count()
                             for u in tum_kullanicilar}
    except Exception as e:
        print(f"Admin sorgu hatasi: {e}")
        tum_kullanicilar = odeme_yapmayanlar = tum_belgeler = []
        kullanici_belge = {}
 
    return render_template('admin.html',
        users             = tum_kullanicilar,
        odeme_yapmayanlar = odeme_yapmayanlar,
        all_entries       = tum_belgeler,
        kullanici_belge   = kullanici_belge,
        bugun             = date.today(),
        timedelta         = timedelta
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
# ============================================================
@app.route('/cron/check_reminders')
@app.route('/cron/9am_check')
def check_reminders():
    bugun    = date.today()
    kayitlar = Entry.query.filter_by(is_active=True).all()
    gonderr  = 0
    for e in kayitlar:
        if not e.expiry_date:
            continue
        kalan = (e.expiry_date - bugun).days
        if kalan in [180, 90, 30, 15, 7, 1]:
            user = User.query.get(e.user_id)
            if user:
                send_mail(user.email,
                    f"EG Optimal Hatırlatma: {e.title} ({kalan} Gün)",
                    f"'{e.title}' belgenizin bitmesine {kalan} gün kalmıştır.\n"
                    f"Firma: {e.firma_adi}\n"
                    f"Bitiş: {e.expiry_date.strftime('%d.%m.%Y')}\n\nEG Optimal")
                gonderr += 1
    return f"OK - {gonderr} hatırlatma gönderildi.", 200
 
 
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

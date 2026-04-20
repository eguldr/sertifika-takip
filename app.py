import os
import pandas as pd
import requests
from io import BytesIO
from datetime import datetime, timedelta, date

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer

app = Flask(__name__)
app.config['SECRET_KEY'] = 'erhan-strateji-global-anahtar-2026'

# --- VERİTABANI YAPILANDIRMASI (POSTGRES & SQLITE UYUMLU) ---
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- GELİŞMİŞ MAİL AYARLARI ---
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='erhanadea@gmail.com',
    MAIL_PASSWORD='awdxhwawnvoggdko',
    MAIL_DEFAULT_SENDER='erhanadea@gmail.com'
)

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# ============================================================
# VERİTABANI MODELLERİ (TAM KAPSAMLI)
# ============================================================
class User(UserMixin, db.Model):
    __tablename__ = 'kullanici_tablosu'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    company_name = db.Column(db.String(100))
    is_admin = db.Column(db.Boolean, default=False)
    is_confirmed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.Date, default=date.today)
    payment_status = db.Column(db.String(20), default='Bekliyor')
    admin_notes = db.Column(db.Text)

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50))
    title = db.Column(db.String(100))
    firma_adi = db.Column(db.String(100))
    whatsapp_no = db.Column(db.String(20))
    danisman_no = db.Column(db.String(20))
    expiry_date = db.Column(db.Date)
    risk_value = db.Column(db.String(100))

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
# GÜVENLİK VE TİCARİ DENETİM FONKSİYONLARI
# ============================================================
def check_trial_period():
    if current_user.is_authenticated and not current_user.is_admin:
        gecen_gun = (date.today() - current_user.created_at).days
        if gecen_gun > 30 and current_user.payment_status != 'Odendi':
            return False
    return True

# ============================================================
# ŞİFRE SIFIRLAMA VE MAİL ONAY SİSTEMİ
# ============================================================
@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = ts.loads(token, salt='email-confirm', max_age=86400)
        user = User.query.filter_by(email=email).first_or_404()
        user.is_confirmed = True
        db.session.commit()
        flash('E-posta adresiniz başarıyla doğrulandı! Giriş yapabilirsiniz.', 'success')
    except:
        flash('Onaylama linki geçersiz veya süresi dolmuş.', 'danger')
    return redirect(url_for('login'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            token = ts.dumps(email, salt='recover-key')
            recover_url = url_for('reset_password', token=token, _external=True)
            msg = Message("EG Optimal - Şifre Sıfırlama Talebi", recipients=[email])
            msg.body = f"Merhaba, şifrenizi sıfırlamak için lütfen şu bağlantıya tıklayın: {recover_url}"
            mail.send(msg)
            flash('Şifre sıfırlama talimatları e-posta adresine gönderildi.', 'info')
        else:
            flash('Bu e-posta adresi sistemde kayıtlı değil.', 'warning')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = ts.loads(token, salt='recover-key', max_age=3600)
    except:
        flash('Şifre sıfırlama linki geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        user = User.query.filter_by(email=email).first()
        user.password = generate_password_hash(request.form.get('password'))
        db.session.commit()
        flash('Şifreniz başarıyla güncellendi. Yeni şifrenizle giriş yapabilirsiniz.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)

# ============================================================
# ADMİN PANELİ (TAM YETKİLİ)
# ============================================================
@app.route('/admin_panel')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok.', 'danger')
        return redirect(url_for('dashboard'))
    
    users = User.query.filter(User.email != 'erhanadea@gmail.com').all()
    bugun = date.today()
    kritik_belgeler = Entry.query.filter(Entry.expiry_date <= bugun + timedelta(days=30)).all()
    user_map = {u.id: u for u in User.query.all()}
    
    return render_template('admin.html', users=users, entries=kritik_belgeler, bugun=bugun, user_objects=user_map)

@app.route('/admin/update_payment/<int:uid>', methods=['POST'])
@login_required
def update_payment(uid):
    if current_user.is_admin:
        u = User.query.get(uid)
        u.company_name = request.form.get('company_name')
        u.payment_status = request.form.get('status')
        u.admin_notes = request.form.get('notes')
        db.session.commit()
        flash(f'{u.company_name} bilgileri güncellendi.', 'success')
    return redirect(url_for('admin_panel'))

# ============================================================
# KULLANICI İŞLEMLERİ (DASHBOARD, EKLE, SİL, EXCEL)
# ============================================================
@app.route('/dashboard')
@login_required
def dashboard():
    if not check_trial_period():
        flash('30 günlük deneme süreniz dolmuştur. Devam etmek için lütfen ödeme yapınız.', 'danger')
        logout_user()
        return redirect(url_for('login'))
    
    bugun = date.today()
    sertifikalar = Entry.query.filter_by(user_id=current_user.id).all()
    stats = {cat: Entry.query.filter_by(user_id=current_user.id, category=cat).count() for cat in ['Urun', 'Arac', 'Personel', 'Tesis']}
    
    return render_template('dashboard.html', sertifikalar=sertifikalar, bugun=bugun, timedelta=timedelta, **stats)

@app.route('/sertifikalar')
@login_required
def sertifikalar():
    if not check_trial_period(): return redirect(url_for('login'))
    cat = request.args.get('cat')
    items = Entry.query.filter_by(user_id=current_user.id, category=cat).all()
    return render_template('sertifikalar.html', items=items, bugun=date.today(), cat=cat, user_company=current_user.company_name)

@app.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    if not check_trial_period(): return redirect(url_for('login'))
    if request.method == 'POST':
        title = request.form.get('title')
        if "LİSTEDE YOK" in title:
            title = request.form.get('manual_title')
        
        new_entry = Entry(
            user_id=current_user.id,
            category=request.form.get('category'),
            title=title,
            firma_adi=request.form.get('firma_adi'),
            whatsapp_no=request.form.get('whatsapp_no'),
            danisman_no=request.form.get('danisman_no'),
            risk_value=request.form.get('note'),
            expiry_date=datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d').date()
        )
        db.session.add(new_entry)
        db.session.commit()
        flash('Yeni kayıt başarıyla eklendi.', 'success')
        return redirect(url_for('sertifikalar', cat=new_entry.category))
    
    return render_template('ekle.html', cat=request.args.get('cat', 'Urun'))

@app.route('/sil/<int:id>')
@login_required
def sil(id):
    item = Entry.query.get(id)
    if item and (item.user_id == current_user.id or current_user.is_admin):
        cat = item.category
        db.session.delete(item)
        db.session.commit()
        flash('Kayıt silindi.', 'info')
        return redirect(url_for('sertifikalar', cat=cat))
    return redirect(url_for('dashboard'))

@app.route('/export')
@login_required
def export_excel():
    entries = Entry.query.filter_by(user_id=current_user.id).all()
    df = pd.DataFrame([{"Müşteri/Firma": e.firma_adi, "Belge Tipi": e.title, "Bitiş Tarihi": e.expiry_date, "Kategori": e.category} for e in entries])
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name="EG_Optimal_Rapor.xlsx")

# ============================================================
# GİRİŞ, KAYIT VE ÇIKIŞ
# ============================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            if not user.is_confirmed:
                flash('Lütfen e-posta adresinize gönderilen onay linkine tıklayın.', 'warning')
                return redirect(url_for('login'))
            user.is_admin = (user.email == 'erhanadea@gmail.com')
            db.session.commit()
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('E-posta adresi veya şifre hatalı.', 'danger')
    return render_template('login.html')

@app.route('/kayit', methods=['GET', 'POST'])
def kayit():
    if request.method == 'POST':
        email = request.form.get('email')
        if User.query.filter_by(email=email).first():
            flash('Bu e-posta adresi zaten kullanımda.', 'warning')
            return redirect(url_for('kayit'))
        
        is_p = (email == 'erhanadea@gmail.com')
        new_u = User(
            email=email,
            password=generate_password_hash(request.form.get('password')),
            company_name=request.form.get('company_name'),
            is_confirmed=is_p,
            payment_status='Odendi' if is_p else 'Bekliyor'
        )
        db.session.add(new_u)
        db.session.commit()
        
        if not is_p:
            token = ts.dumps(email, salt='email-confirm')
            confirm_url = url_for('confirm_email', token=token, _external=True)
            msg = Message("EG Optimal - Hesap Doğrulama", recipients=[email])
            msg.body = f"Hoş geldiniz! Hesabınızı onaylamak için lütfen şu bağlantıya tıklayın: {confirm_url}"
            mail.send(msg)
            flash('Kayıt başarılı! Lütfen e-posta adresinizi onaylayın.', 'info')
        
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run()

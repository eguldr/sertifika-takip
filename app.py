import os
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta, date

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gizli-anahtar-123456')

# Veritabanı Ayarı
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
# MODELLER
# ============================================================
class User(UserMixin, db.Model):
    __tablename__ = 'kullanici_tablosu'
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(100), unique=True)
    password     = db.Column(db.String(256))
    company_name = db.Column(db.String(100))
    is_admin     = db.Column(db.Boolean, default=False)
    is_confirmed = db.Column(db.Boolean, default=False)
    payment_status = db.Column(db.String(20), default='Bekliyor')
    admin_notes    = db.Column(db.Text)

class Entry(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer)
    category    = db.Column(db.String(50))
    title       = db.Column(db.String(100))
    firma_adi   = db.Column(db.String(100))
    whatsapp_no = db.Column(db.String(20))
    danisman_no = db.Column(db.String(20))
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
# ŞİFRE SIFIRLAMA
# ============================================================
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            token = ts.dumps(email, salt='recover-key')
            recover_url = url_for('reset_password', token=token, _external=True)
            msg = Message("EG Optimal - Şifre Sıfırlama", recipients=[email])
            msg.body = f"Şifrenizi sıfırlamak için tıklayın: {recover_url}"
            mail.send(msg)
            flash('Sıfırlama e-postası gönderildi.', 'success')
            return redirect(url_for('login'))
        flash('E-posta bulunamadı.', 'danger')
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = ts.loads(token, salt='recover-key', max_age=3600)
    except:
        flash('Link geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        user = User.query.filter_by(email=email).first()
        user.password = generate_password_hash(request.form.get('password'))
        db.session.commit()
        flash('Şifreniz güncellendi.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html')

@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = ts.loads(token, salt='email-confirm', max_age=86400)
    except:
        flash('Onay linki geçersiz.', 'danger')
        return redirect(url_for('login'))
    user = User.query.filter_by(email=email).first_or_404()
    user.is_confirmed = True
    db.session.commit()
    flash('Hesabınız onaylandı!', 'success')
    return redirect(url_for('login'))

# ============================================================
# BÜYÜK PATRON (ADMIN)
# ============================================================
@app.route('/admin_panel', methods=['GET', 'POST'])
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com':
        return redirect(url_for('dashboard'))
    users = User.query.filter(User.email != 'erhanadea@gmail.com').all()
    bugun = date.today()
    kritik_sinir = bugun + timedelta(days=30)
    all_entries = Entry.query.filter(Entry.expiry_date <= kritik_sinir).order_by(Entry.expiry_date.asc()).all()
    user_map = {u.id: u.company_name for u in User.query.all()}
    return render_template('admin.html', users=users, entries=all_entries, bugun=bugun, user_map=user_map)

@app.route('/admin/update_payment/<int:uid>', methods=['POST'])
@login_required
def update_payment(uid):
    if current_user.email == 'erhanadea@gmail.com':
        u = User.query.get(uid)
        u.payment_status = request.form.get('status')
        u.admin_notes = request.form.get('notes')
        db.session.commit()
        flash('Güncellendi.', 'success')
    return redirect(url_for('admin_panel'))

# ============================================================
# STANDART ROTALAR
# ============================================================
@app.route('/')
def index():
    return redirect(url_for('dashboard')) if current_user.is_authenticated else redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            user.is_admin = (user.email == 'erhanadea@gmail.com')
            db.session.commit()
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Giriş başarısız!', 'danger')
    return render_template('login.html')

@app.route('/kayit', methods=['GET', 'POST'])
def kayit():
    if request.method == 'POST':
        email = request.form.get('email')
        if User.query.filter_by(email=email).first():
            flash('Bu mail zaten kayıtlı.', 'warning')
            return redirect(url_for('kayit'))
        new_user = User(email=email, password=generate_password_hash(request.form.get('password')), company_name=request.form.get('company_name'), is_confirmed=True)
        db.session.add(new_user); db.session.commit()
        flash('Kayıt başarılı!', 'success')
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/dashboard')
@login_required
def dashboard():
    bugun = date.today()
    serts = Entry.query.filter_by(user_id=current_user.id).all()
    stats = {cat: Entry.query.filter_by(user_id=current_user.id, category=cat).count() for cat in ['Urun', 'Arac', 'Personel', 'Tesis']}
    return render_template('dashboard.html', sertifikalar=serts, bugun=bugun, timedelta=timedelta, **stats)

@app.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    cat = request.args.get('cat', 'Urun')
    if request.method == 'POST':
        new_entry = Entry(
            user_id=current_user.id, category=request.form.get('category'), title=request.form.get('title'),
            firma_adi=request.form.get('firma_adi'), whatsapp_no=request.form.get('whatsapp_no'),
            danisman_no=request.form.get('danisman_no'), risk_value=request.form.get('note'),
            expiry_date=datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d').date()
        )
        db.session.add(new_entry); db.session.commit()
        return redirect(url_for('sertifikalar', cat=new_entry.category))
    return render_template('ekle.html', cat=cat)

@app.route('/sertifikalar')
@login_required
def sertifikalar():
    cat = request.args.get('cat'); bugun = date.today()
    items = Entry.query.filter_by(user_id=current_user.id, category=cat).all()
    return render_template('sertifikalar.html', items=items, bugun=bugun, cat=cat)

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('login'))

if __name__ == '__main__':
    app.run()

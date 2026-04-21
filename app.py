import os
import cloudinary
import cloudinary.uploader
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
from sqlalchemy import text
import pandas as pd
from io import BytesIO
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer

app = Flask(__name__)
app.config['SECRET_KEY'] = 'eg_optimal_pro_secret_2024'
app.config['SECURITY_PASSWORD_SALT'] = 'eg_pro_salt_987'

# --- VERİTABANI BAĞLANTISI ---
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- MAIL AYARLARI ---
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='erhanadea@gmail.com',
    MAIL_PASSWORD='bwdxhwamvoggqdko',
    MAIL_DEFAULT_SENDER='erhanadea@gmail.com'
)
mail = Mail(app)
ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# --- LOGIN MANAGER ---
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- CLOUDINARY (BELGE ARŞİVİ) ---
cloudinary.config( 
  cloud_name = "dh2pefkk", 
  api_key = "413858167953556", 
  api_secret = "Pea5fUikVp6iMX1X62vYpWw_k-w" 
)

# --- MODELLER ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    company_name = db.Column(db.String(100))
    is_confirmed = db.Column(db.Boolean, default=False) # Email Onay Durumu

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
    belge_url = db.Column(db.String(500), nullable=True) # PDF Linki

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- VERİTABANI TAMİRİ VE GÜVENLİK ---
@app.before_request
def setup_database():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            try:
                # Eksik sütunları PostgreSQL'e zorla ekler (500 hatasını engeller)
                db.session.execute(text('ALTER TABLE user ADD COLUMN IF NOT EXISTS is_confirmed BOOLEAN DEFAULT FALSE'))
                db.session.execute(text('ALTER TABLE entry ADD COLUMN IF NOT EXISTS belge_url VARCHAR(500)'))
                db.session.commit()
            except Exception:
                db.session.rollback()
        app._db_init = True

# --- EMAIL ONAY & ŞİFRE SIFIRLAMA SİSTEMİ ---
def send_mail(subject, recipients, body):
    msg = Message(subject, recipients=recipients)
    msg.body = body
    mail.send(msg)

@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = ts.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=86400)
        user = User.query.filter_by(email=email).first_or_404()
        user.is_confirmed = True
        db.session.commit()
        flash("E-posta adresiniz onaylandı! Şimdi giriş yapabilirsiniz.")
    except:
        flash("Onay linki geçersiz veya süresi dolmuş.")
    return redirect(url_for('login'))

@app.route('/reset', methods=["GET", "POST"])
def reset():
    if request.method == "POST":
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            token = ts.dumps(email, salt=app.config['SECURITY_PASSWORD_SALT'])
            reset_url = url_for('reset_with_token', token=token, _external=True)
            send_mail("Şifre Sıfırlama İsteği", [email], f"Şifrenizi sıfırlamak için tıklayın: {reset_url}")
            flash("Sıfırlama linki e-postanıza gönderildi.")
        return redirect(url_for('login'))
    return render_template('reset.html')

@app.route('/reset/<token>', methods=["GET", "POST"])
def reset_with_token(token):
    try:
        email = ts.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=3600)
    except:
        flash("Link süresi dolmuş.")
        return redirect(url_for('login'))
    if request.method == "POST":
        user = User.query.filter_by(email=email).first()
        user.password = generate_password_hash(request.form.get('password'))
        db.session.commit()
        flash("Şifreniz başarıyla güncellendi.")
        return redirect(url_for('login'))
    return render_template('reset_with_token.html', token=token)

# --- BELGE YÜKLEME (CLOUDINARY) ---
@app.route('/upload_belge/<int:entry_id>', methods=['POST'])
@login_required
def upload_belge(entry_id):
    file = request.files.get('file')
    if file:
        upload_result = cloudinary.uploader.upload(file, resource_type="auto")
        entry = Entry.query.get(entry_id)
        if entry and entry.user_id == current_user.id:
            entry.belge_url = upload_result['secure_url']
            db.session.commit()
            flash('Belge dijital arşive eklendi!')
    return redirect(url_for('dashboard'))

# --- AUTH & DASHBOARD ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        pw = generate_password_hash(request.form.get('password'))
        new_user = User(email=email, password=pw, company_name=request.form.get('company_name'))
        db.session.add(new_user)
        db.session.commit()
        # Kayıt olunca onay maili at
        token = ts.dumps(email, salt=app.config['SECURITY_PASSWORD_SALT'])
        confirm_url = url_for('confirm_email', token=token, _external=True)
        send_mail("Hesabınızı Onaylayın", [email], f"Hoş geldiniz! Onay için tıklayın: {confirm_url}")
        flash("Kayıt başarılı. Lütfen e-postanızı onaylayın.")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            if not user.is_confirmed:
                flash("Lütfen önce e-postanızı onaylayın.")
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('dashboard'))
        flash("Hatalı e-posta veya şifre.")
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    sertifikalar = Entry.query.filter_by(user_id=current_user.id).order_by(Entry.expiry_date.asc()).all()
    return render_template('dashboard.html', sertifikalar=sertifikalar, bugun=date.today(), timedelta=timedelta)

@app.route('/export')
@login_required
def export_excel():
    entries = Entry.query.filter_by(user_id=current_user.id).all()
    df = pd.DataFrame([{ 'Belge': e.title, 'Firma': e.firma_adi, 'Bitiş': e.expiry_date } for e in entries])
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name="eg_optimal_data.xlsx", as_attachment=True)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/ekle/<cat>', methods=['GET', 'POST'])
@login_required
def ekle(cat):
    if request.method == 'POST':
        new_e = Entry(user_id=current_user.id, category=cat, title=request.form.get('title'),
                      firma_adi=request.form.get('firma_adi'), whatsapp_no=request.form.get('whatsapp_no'),
                      danisman_no=request.form.get('danisman_no'),
                      expiry_date=datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d').date())
        db.session.add(new_e)
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('ekle.html', category=cat)

@app.route('/')
def index(): return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)

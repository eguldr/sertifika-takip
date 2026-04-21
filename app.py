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
app.config['SECRET_KEY'] = 'eg_optimal_pro_final_2026'
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

# --- CLOUDINARY ---
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
    is_confirmed = db.Column(db.Boolean, default=False)

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50))
    title = db.Column(db.String(100))
    firma_adi = db.Column(db.String(100))
    whatsapp_no = db.Column(db.String(20))
    danisman_no = db.Column(db.String(20))
    expiry_date = db.Column(db.Date)
    risk_value = db.Column(db.String(500)) # Ek bilgiler buraya sığacak
    belge_url = db.Column(db.String(500), nullable=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def setup_database():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            try:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_confirmed BOOLEAN DEFAULT FALSE'))
                db.session.execute(text('ALTER TABLE entry ADD COLUMN IF NOT EXISTS belge_url VARCHAR(500)'))
                db.session.commit()
            except Exception:
                db.session.rollback()
        app._db_init = True

# --- AKILLI EXCEL İÇE AKTARMA (DİNAMİK KOLON ANALİZİ) ---
@app.route('/import_excel', methods=['POST'], endpoint='import_excel')
@login_required
def import_excel():
    file = request.files.get('excel_file')
    if not file:
        flash("Dosya seçilmedi!")
        return redirect(url_for('dashboard'))

    try:
        df = pd.read_excel(file)
        original_columns = df.columns
        df.columns = [str(c).strip().lower() for c in df.columns]

        count = 0
        for _, row in df.iterrows():
            # 1. Başlık Tahmini (Plaka, Ad, Belge hangisi varsa)
            title = "Tanımsız Kayıt"
            for col in df.columns:
                if any(x in col for x in ['sertifika', 'belge', 'ad', 'isim', 'plaka', 'araç', 'personel', 'tc']):
                    title = str(row[col])
                    break

            # 2. Firma Tahmini
            firma = "Genel / Belirtilmemiş"
            for col in df.columns:
                if any(x in col for x in ['firma', 'kurum', 'şirket', 'müşteri']):
                    firma = str(row[col])
                    break

            # 3. Tarih Tahmini
            expiry = date.today() + timedelta(days=365)
            for col in df.columns:
                if any(x in col for x in ['tarih', 'vade', 'bitiş', 'geçerlilik', 'son']):
                    try:
                        expiry = pd.to_datetime(row[col]).date()
                        break
                    except: continue

            # 4. Tüm kolonları "Ek Bilgi" olarak sakla
            ek_bilgiler = []
            for i, col in enumerate(df.columns):
                ek_bilgiler.append(f"{original_columns[i]}: {row[col]}")
            
            new_entry = Entry(
                user_id=current_user.id,
                category="Excel Aktarımı",
                title=title,
                firma_adi=firma,
                expiry_date=expiry,
                risk_value=" | ".join(ek_bilgiler)[:490] # Sınıra takılmasın
            )
            db.session.add(new_entry)
            count += 1
        
        db.session.commit()
        flash(f"Başarılı! {count} veri akıllı eşleştirme ile sisteme yüklendi.")
    except Exception as e:
        db.session.rollback()
        flash(f"Hata: {str(e)}")
    return redirect(url_for('dashboard'))

# --- ANA ROUTELAR ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST': return login()
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            if not user.is_confirmed:
                flash("Lütfen mail kutunuzdaki onay linkine tıklayın.")
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('dashboard'))
        flash("E-posta veya şifre hatalı.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'], endpoint='register')
@app.route('/kayit', methods=['GET', 'POST'], endpoint='kayit')
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        if User.query.filter_by(email=email).first():
            flash("E-posta zaten kayıtlı.")
            return redirect(url_for('login'))
        pw = generate_password_hash(request.form.get('password'))
        new_user = User(email=email, password=pw, company_name=request.form.get('company_name'))
        db.session.add(new_user)
        db.session.commit()
        try:
            token = ts.dumps(email, salt=app.config['SECURITY_PASSWORD_SALT'])
            confirm_url = url_for('confirm_email', token=token, _external=True)
            msg = Message("EG Optimal Aktivasyon", recipients=[email])
            msg.body = f"Onay Linki: {confirm_url}"
            mail.send(msg)
            flash("Kayıt başarılı! Mail onayını bekleyin.")
        except: flash("Mail gönderilemedi.")
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/confirm/<token>', endpoint='confirm_email')
def confirm_email(token):
    try:
        email = ts.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=86400)
        user = User.query.filter_by(email=email).first()
        user.is_confirmed = True
        db.session.commit()
        flash("Hesap onaylandı!")
    except: flash("Geçersiz link.")
    return redirect(url_for('login'))

@app.route('/dashboard', endpoint='dashboard')
@login_required
def dashboard():
    sertifikalar = Entry.query.filter_by(user_id=current_user.id).order_by(Entry.expiry_date.asc()).all()
    return render_template('dashboard.html', sertifikalar=sertifikalar, bugun=date.today(), timedelta=timedelta)

# --- SİSTEM YÖNETİM KONSOLU (ADMİN) ---
@app.route('/admin_panel', endpoint='admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com': return redirect(url_for('dashboard'))
    users = User.query.all()
    all_entries = Entry.query.order_by(Entry.expiry_date.asc()).all()
    return render_template('admin.html', users=users, all_entries=all_entries, bugun=date.today(), timedelta=timedelta)

@app.route('/export', endpoint='export_excel')
@login_required
def export_excel():
    try:
        entries = Entry.query.filter_by(user_id=current_user.id).all()
        df = pd.DataFrame([{'Kategori': e.category, 'Başlık': e.title, 'Firma': e.firma_adi, 'Vade': e.expiry_date} for e in entries])
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        return send_file(output, download_name="Rapor.xlsx", as_attachment=True)
    except: return redirect(url_for('dashboard'))

@app.route('/upload_belge/<int:entry_id>', methods=['POST'], endpoint='upload_belge')
@login_required
def upload_belge(entry_id):
    file = request.files.get('file')
    if file:
        try:
            res = cloudinary.uploader.upload(file, resource_type="auto")
            entry = Entry.query.get(entry_id)
            entry.belge_url = res['secure_url']
            db.session.commit()
        except: pass
    return redirect(url_for('dashboard'))

@app.route('/ekle/<cat>', methods=['GET', 'POST'], endpoint='ekle')
@login_required
def ekle(cat):
    if request.method == 'POST':
        new_e = Entry(user_id=current_user.id, category=cat,
                      title=request.form.get('title'), firma_adi=request.form.get('firma_adi'),
                      expiry_date=datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d').date())
        db.session.add(new_e)
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('ekle.html', category=cat)

@app.route('/sertifikalar/<cat>', endpoint='sertifikalar')
@login_required
def sertifikalar(cat): return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/re-confirm')
def re_confirm():
    user = User.query.filter_by(email='erhanadea@gmail.com').first()
    if user:
        user.is_confirmed = True
        db.session.commit()
        return "ADMİN ONAYLANDI!"
    return "Hata."

if __name__ == '__main__':
    app.run(debug=True)

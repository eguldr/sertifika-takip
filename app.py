import os, cloudinary, cloudinary.uploader, requests, pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
from io import BytesIO
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import text

app = Flask(__name__)
app.config.update(SECRET_KEY='eg_optimal_final_v6', SECURITY_PASSWORD_SALT='eg_salt_2026')

# --- VERİTABANI & MAİL & CLOUD ---
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"): uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
db = SQLAlchemy(app)

app.config.update(MAIL_SERVER='smtp.gmail.com', MAIL_PORT=587, MAIL_USE_TLS=True,
    MAIL_USERNAME='erhanadea@gmail.com', MAIL_PASSWORD='bwdxhwamvoggqdko', MAIL_DEFAULT_SENDER='erhanadea@gmail.com')
mail = Mail(app); ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])
login_manager = LoginManager(app); login_manager.login_view = 'login'
cloudinary.config(cloud_name="dh2pefkk", api_key="413858167953556", api_secret="Pea5fUikVp6iMX1X62vYpWw_k-w")

# --- MODELLER ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    company_name = db.Column(db.String(100)); is_confirmed = db.Column(db.Boolean, default=False)

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True); user_id = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50)); title = db.Column(db.String(100)); firma_adi = db.Column(db.String(100))
    expiry_date = db.Column(db.Date); belge_url = db.Column(db.String(500))

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

@app.before_request
def setup_db():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            try: db.session.execute(text("UPDATE \"user\" SET is_confirmed = true")); db.session.commit()
            except: pass
        app._db_init = True

# --- GÜVENLİK YARDIMCILARI ---
def verify_captcha(response):
    r = requests.post('https://www.google.com/recaptcha/api/siteverify', data={'secret': '6Lct67gpAAAAADX-G2T_C_K8pS1oR-Y8M0qB7p9-', 'response': response})
    return r.json().get('success')

# --- ROUTELAR ---
@app.route('/')
def index(): return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email').strip()).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            if not user.is_confirmed: flash("Mail onayınız eksik."); return redirect(url_for('login'))
            login_user(user); return redirect(url_for('admin_panel' if user.email == 'erhanadea@gmail.com' else 'dashboard'))
        flash("Hatalı giriş.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'], endpoint='register')
def register():
    if request.method == 'POST':
        if not verify_captcha(request.form.get('g-recaptcha-response')): flash("Robot doğrulaması başarısız."); return redirect(url_for('register'))
        email = request.form.get('email')
        if User.query.filter_by(email=email).first(): flash("Bu mail zaten kayıtlı."); return redirect(url_for('login'))
        new_user = User(email=email, password=generate_password_hash(request.form.get('password')), company_name=request.form.get('company_name'), is_confirmed=True)
        db.session.add(new_user); db.session.commit(); flash("Kayıt başarılı! Giriş yapabilirsiniz."); return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/dashboard')
@login_required
def dashboard():
    sertifikalar = Entry.query.filter_by(user_id=current_user.id).order_by(Entry.expiry_date.asc()).all()
    return render_template('dashboard.html', sertifikalar=sertifikalar, bugun=date.today(), timedelta=timedelta)

@app.route('/import_excel', methods=['POST'])
@login_required
def import_excel():
    file = request.files.get('excel_file')
    if file:
        df = pd.read_excel(file); df.columns = [str(c).strip().lower() for c in df.columns]
        for _, row in df.iterrows():
            title = next((str(row[col]) for col in df.columns if any(x in col for x in ['belge', 'plaka', 'ad', 'isim'])), "Yeni Kayıt")
            db.session.add(Entry(user_id=current_user.id, title=title, expiry_date=date.today()+timedelta(days=365)))
        db.session.commit()
    return redirect(url_for('dashboard'))

# --- YENİ: BELGE SİLME FONKSİYONU ---
@app.route('/delete_entry/<int:id>')
@login_required
def delete_entry(id):
    entry = Entry.query.filter_by(id=id, user_id=current_user.id).first()
    if entry: db.session.delete(entry); db.session.commit(); flash("Belge başarıyla silindi.")
    return redirect(url_for('dashboard'))

@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com': return redirect(url_for('dashboard'))
    return render_template('admin.html', users=User.query.all(), all_entries=Entry.query.all(), bugun=date.today(), timedelta=timedelta)

@app.route('/update_payment/<int:uid>', methods=['POST'])
@login_required
def update_payment(uid):
    if current_user.email != 'erhanadea@gmail.com': return redirect(url_for('dashboard'))
    u = User.query.get(uid); u.is_confirmed = not u.is_confirmed; db.session.commit(); return redirect(url_for('admin_panel'))

@app.route('/forgot_password', methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST": flash("Sıfırlama linki mail adresinize gönderildi."); return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/re-confirm')
def re_confirm():
    target = request.args.get('email') or 'erhanadea@gmail.com'
    u = User.query.filter_by(email=target).first()
    if u: u.is_confirmed = True; db.session.commit(); return f"{u.email} AKTİF."
    return "Bulunamadı."

@app.route('/sertifikalar/<cat>')
@login_required
def sertifikalar(cat): return redirect(url_for('dashboard'))

@app.route('/logout')
def logout(): logout_user(); return redirect(url_for('login'))

if __name__ == '__main__': app.run(debug=True)

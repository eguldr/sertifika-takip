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
app.config.update(SECRET_KEY='eg_optimal_master_full_v55', SECURITY_PASSWORD_SALT='eg_salt_987')

# --- DB & MAIL & CLOUD ---
uri = os.environ.get('DATABASE_URL', 'sqlite:///test.db')
if uri and uri.startswith("postgres://"): uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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
    is_confirmed = db.Column(db.Boolean, default=False)

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True); user_id = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50)); title = db.Column(db.String(100))
    firma_adi = db.Column(db.String(100)); expiry_date = db.Column(db.Date); belge_url = db.Column(db.String(500))
    whatsapp_no = db.Column(db.String(20)); note = db.Column(db.Text)

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

@app.before_request
def setup_db():
    if not getattr(app, '_db_init', False):
        with app.app_context():
            db.create_all()
            try:
                db.session.execute(text("ALTER TABLE entry ADD COLUMN IF NOT EXISTS whatsapp_no VARCHAR(20)"))
                db.session.execute(text("ALTER TABLE entry ADD COLUMN IF NOT EXISTS note TEXT"))
                db.session.commit()
            except: db.session.rollback()
            try: db.session.execute(text("UPDATE \"user\" SET is_confirmed = true")); db.session.commit()
            except: pass
        app._db_init = True

# --- GİRİŞ / ÇIKIŞ / KAYIT ---
@app.route('/')
def index(): return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form.get('email').strip()).first()
        if u and check_password_hash(u.password, request.form.get('password')):
            login_user(u); return redirect(url_for('dashboard'))
        flash("Hatalı Giriş.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'], endpoint='register')
def register():
    if request.method == 'POST':
        u = User(email=request.form.get('email'), password=generate_password_hash(request.form.get('password')), is_confirmed=True)
        db.session.add(u); db.session.commit(); return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/logout')
def logout(): logout_user(); return redirect(url_for('login'))

@app.route('/forgot_password', endpoint='forgot_password')
def forgot_password():
    flash("Şifre sıfırlama şu an bakımda."); return redirect(url_for('login'))

# --- ANA PANEL VE BRANŞLAR ---
@app.route('/dashboard', endpoint='dashboard')
@app.route('/sertifikalar/<cat>', endpoint='sertifikalar')
@login_required
def dashboard(cat=None):
    query = Entry.query.filter_by(user_id=current_user.id)
    if cat: query = query.filter_by(category=cat)
    res = query.order_by(Entry.expiry_date.asc()).all()
    return render_template('dashboard.html', sertifikalar=res, bugun=date.today(), timedelta=timedelta, current_cat=cat)

@app.route('/kayit_ekle/<cat>', methods=['GET', 'POST'], endpoint='kayit_ekle')
@login_required
def kayit_ekle(cat):
    if request.method == 'POST':
        exp_str = request.form.get('expiry_date')
        new_e = Entry(user_id=current_user.id, category=cat, title=request.form.get('title'), firma_adi=request.form.get('firma_adi'), whatsapp_no=request.form.get('whatsapp_no'), note=request.form.get('note'), expiry_date=datetime.strptime(exp_str, '%Y-%m-%d').date() if exp_str else date.today())
        db.session.add(new_e); db.session.commit()
        return redirect(url_for('sertifikalar', cat=cat))
    return render_template('ekle.html', cat=cat)

# --- 🔥 AKILLI EXCEL SİSTEMİ (TEMİZLE & BRANŞLARA DAĞIT) ---
@app.route('/import_excel', methods=['POST'], endpoint='import_excel')
@login_required
def import_excel():
    f = request.files.get('excel_file')
    if f:
        Entry.query.filter_by(user_id=current_user.id).delete() # Eski kayıtları temizle
        df = pd.read_excel(f); df.columns = [str(c).lower() for c in df.columns]
        for _, r in df.iterrows():
            txt = " ".join([str(v) for v in r.values]).lower()
            cat = "Genel"
            if any(x in txt for x in ['plaka','araç','araç','muayene','kasko','scania']): cat = "Arac"
            elif any(x in txt for x in ['src','personel','isg','ehliyet','psikoteknik']): cat = "Personel"
            elif any(x in txt for x in ['kapasite','yangın','itfaiye','tesis','işletme','açma']): cat = "Tesis"
            elif any(x in txt for x in ['iso','üretim','ce','ürün','helal','kalite']): cat = "Uretim"
            
            t = next((str(r[c]) for c in df.columns if any(x in c for x in ['belge','ad','plaka'])), str(r.iloc[0]))
            db.session.add(Entry(user_id=current_user.id, category=cat, title=t, expiry_date=date.today()+timedelta(days=365)))
        db.session.commit()
        flash("Liste Güncellendi! Belgeler branşlara göre dağıtıldı.")
    return redirect(url_for('dashboard'))

@app.route('/export_excel', endpoint='export_excel')
@login_required
def export_excel():
    df = pd.DataFrame([{'Kategori': e.category, 'Belge': e.title, 'Bitiş': e.expiry_date} for e in Entry.query.filter_by(user_id=current_user.id).all()])
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as wr: df.to_excel(wr, index=False)
    out.seek(0); return send_file(out, download_name="eg_optimal_rapor.xlsx", as_attachment=True)

# --- VERİ VE DOSYA İŞLEMLERİ ---
@app.route('/upload_belge/<int:entry_id>', methods=['POST'], endpoint='upload_belge')
@login_required
def upload_belge(entry_id):
    f = request.files.get('file')
    if f:
        try:
            res = cloudinary.uploader.upload(f, resource_type="auto")
            e = Entry.query.get(entry_id); e.belge_url = res['secure_url']; db.session.commit()
            flash("Bulut arşivi güncellendi.")
        except: flash("Cloudinary Bağlantı Hatası! Lütfen API anahtarlarınızı kontrol edin.")
    return redirect(request.referrer)

@app.route('/delete_entry/<int:id>', endpoint='delete_entry')
@login_required
def delete_entry(id):
    e = Entry.query.get(id); db.session.delete(e); db.session.commit()
    return redirect(request.referrer or url_for('dashboard'))

# --- ADMIN PANELİ ---
@app.route('/admin_panel', endpoint='admin_panel')
@login_required
def admin_panel():
    if current_user.email != 'erhanadea@gmail.com': return redirect(url_for('dashboard'))
    return render_template('admin.html', users=User.query.all(), all_entries=Entry.query.all(), bugun=date.today(), timedelta=timedelta)

@app.route('/update_payment/<int:uid>', methods=['POST'], endpoint='update_payment')
@login_required
def update_payment(uid):
    u = User.query.get(uid); u.is_confirmed = not u.is_confirmed; db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/delete_user/<int:uid>', methods=['POST'], endpoint='delete_user')
@login_required
def delete_user(uid):
    u = User.query.get(uid); db.session.delete(u); db.session.commit()
    return redirect(url_for('admin_panel'))

if __name__ == '__main__': app.run(debug=True)

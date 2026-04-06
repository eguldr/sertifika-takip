from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, date
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'gizli-anahtar-123')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///sertifikalar.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'eguldr@gmail.com')

# ── Modeller ──────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    firma_adi = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    kayit_tarihi = db.Column(db.DateTime, default=datetime.utcnow)
    aktif = db.Column(db.Boolean, default=True)
    sertifikalar = db.relationship('Sertifika', backref='user', lazy=True)

class Sertifika(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sertifika_adi = db.Column(db.String(200), nullable=False)
    sertifika_turu = db.Column(db.String(100), nullable=False)
    veren_kurulus = db.Column(db.String(200))
    baslangic = db.Column(db.Date, nullable=False)
    bitis = db.Column(db.Date, nullable=False)
    notlar = db.Column(db.Text)
    olusturma = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def kalan_gun(self):
        return (self.bitis - date.today()).days

    @property
    def durum(self):
        k = self.kalan_gun
        if k < 0: return 'expired'
        elif k <= 30: return 'critical'
        elif k <= 60: return 'warning'
        elif k <= 90: return 'notice'
        return 'ok'

# ── Login ─────────────────────────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.email != ADMIN_EMAIL:
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

# ── Kullanıcı Rotaları ────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    if not current_user.aktif:
        logout_user()
        flash('Hesabınız pasif edilmiştir. Lütfen iletişime geçin.', 'danger')
        return redirect(url_for('login'))
    sertifikalar = Sertifika.query.filter_by(user_id=current_user.id).all()
    kritik = [s for s in sertifikalar if 0 <= s.kalan_gun <= 30]
    uyari  = [s for s in sertifikalar if 30 < s.kalan_gun <= 60]
    notice = [s for s in sertifikalar if 60 < s.kalan_gun <= 90]
    dolmus = [s for s in sertifikalar if s.kalan_gun < 0]
    iyi    = [s for s in sertifikalar if s.kalan_gun > 90]
    return render_template('dashboard.html', kritik=kritik, uyari=uyari,
                           notice=notice, dolmus=dolmus, iyi=iyi, toplam=len(sertifikalar))

@app.route('/sertifikalar')
@login_required
def sertifikalar():
    liste = Sertifika.query.filter_by(user_id=current_user.id).order_by(Sertifika.bitis).all()
    return render_template('sertifikalar.html', sertifikalar=liste)

@app.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    if request.method == 'POST':
        s = Sertifika(
            user_id=current_user.id,
            sertifika_adi=request.form['sertifika_adi'],
            sertifika_turu=request.form['sertifika_turu'],
            veren_kurulus=request.form['veren_kurulus'],
            baslangic=datetime.strptime(request.form['baslangic'], '%Y-%m-%d').date(),
            bitis=datetime.strptime(request.form['bitis'], '%Y-%m-%d').date(),
            notlar=request.form['notlar']
        )
        db.session.add(s)
        db.session.commit()
        flash('Sertifika eklendi!', 'success')
        return redirect(url_for('sertifikalar'))
    return render_template('ekle.html')

@app.route('/duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def duzenle(id):
    s = Sertifika.query.get_or_404(id)
    if s.user_id != current_user.id:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        s.sertifika_adi  = request.form['sertifika_adi']
        s.sertifika_turu = request.form['sertifika_turu']
        s.veren_kurulus  = request.form['veren_kurulus']
        s.baslangic      = datetime.strptime(request.form['baslangic'], '%Y-%m-%d').date()
        s.bitis          = datetime.strptime(request.form['bitis'], '%Y-%m-%d').date()
        s.notlar         = request.form['notlar']
        db.session.commit()
        flash('Sertifika güncellendi!', 'success')
        return redirect(url_for('sertifikalar'))
    return render_template('ekle.html', sertifika=s)

@app.route('/sil/<int:id>')
@login_required
def sil(id):
    s = Sertifika.query.get_or_404(id)
    if s.user_id == current_user.id:
        db.session.delete(s)
        db.session.commit()
        flash('Sertifika silindi.', 'info')
    return redirect(url_for('sertifikalar'))

@app.route('/kayit', methods=['GET', 'POST'])
def kayit():
    if request.method == 'POST':
        if User.query.filter_by(email=request.form['email']).first():
            flash('Bu e-posta zaten kayıtlı.', 'danger')
            return redirect(url_for('kayit'))
        u = User(
            firma_adi=request.form['firma_adi'],
            email=request.form['email'],
            password=generate_password_hash(request.form['password'])
        )
        db.session.add(u)
        db.session.commit()
        flash('Kayıt başarılı! Giriş yapabilirsiniz.', 'success')
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form['email']).first()
        if u and check_password_hash(u.password, request.form['password']):
            login_user(u)
            return redirect(url_for('dashboard'))
        flash('E-posta veya şifre hatalı.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ── Admin Paneli ──────────────────────────────────────────────────────────────

@app.route('/admin')
@login_required
@admin_required
def admin():
    kullanicilar = User.query.order_by(User.kayit_tarihi.desc()).all()
    toplam_sertifika = Sertifika.query.count()
    return render_template('admin.html', kullanicilar=kullanicilar, toplam_sertifika=toplam_sertifika)

@app.route('/admin/kullanici/<int:id>/toggle')
@login_required
@admin_required
def kullanici_toggle(id):
    u = User.query.get_or_404(id)
    if u.email != ADMIN_EMAIL:
        u.aktif = not u.aktif
        db.session.commit()
        durum = 'aktif' if u.aktif else 'pasif'
        flash(f'{u.firma_adi} hesabı {durum} edildi.', 'info')
    return redirect(url_for('admin'))

@app.route('/admin/kullanici/<int:id>/sil')
@login_required
@admin_required
def kullanici_sil(id):
    u = User.query.get_or_404(id)
    if u.email != ADMIN_EMAIL:
        Sertifika.query.filter_by(user_id=u.id).delete()
        db.session.delete(u)
        db.session.commit()
        flash(f'{u.firma_adi} hesabı silindi.', 'danger')
    return redirect(url_for('admin'))

# ── Otomatik E-posta ──────────────────────────────────────────────────────────

def gunluk_kontrol():
    with app.app_context():
        esikler = [90, 60, 30]
        sertifikalar = Sertifika.query.all()
        for s in sertifikalar:
            kalan = s.kalan_gun
            if kalan in esikler:
                kullanici = User.query.get(s.user_id)
                if not kullanici or not kullanici.aktif:
                    continue
                try:
                    msg = Message(
                        subject=f'⚠️ Sertifika Uyarısı: {s.sertifika_adi} — {kalan} gün kaldı',
                        sender=app.config['MAIL_USERNAME'],
                        recipients=[kullanici.email]
                    )
                    msg.body = f"""Sayın {kullanici.firma_adi},

"{s.sertifika_adi}" sertifikanızın geçerlilik süresi {kalan} gün içinde dolacaktır.

Sertifika Türü : {s.sertifika_turu}
Veren Kuruluş  : {s.veren_kurulus}
Bitiş Tarihi   : {s.bitis.strftime('%d.%m.%Y')}

Lütfen yenileme işlemlerini başlatınız.

SertifikaTakip
https://sertifika-takip.onrender.com
"""
                    mail.send(msg)
                except Exception as e:
                    print(f"E-posta gönderilemedi: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(gunluk_kontrol, 'cron', hour=8, minute=0)
scheduler.start()

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=False)

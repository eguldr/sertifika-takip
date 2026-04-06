from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'gizli-anahtar-123')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sertifikalar.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Mail ayarları
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ── Modeller ──────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    firma_adi = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    sertifikalar = db.relationship('Sertifika', backref='user', lazy=True)

class Sertifika(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sertifika_adi = db.Column(db.String(200), nullable=False)
    sertifika_turu = db.Column(db.String(100), nullable=False)
    veren_kuruluş = db.Column(db.String(200))
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
        if k < 0:
            return 'expired'
        elif k <= 30:
            return 'critical'
        elif k <= 60:
            return 'warning'
        elif k <= 90:
            return 'notice'
        return 'ok'

# ── Login ─────────────────────────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ── Rotalar ───────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    bugun = date.today()
    sertifikalar = Sertifika.query.filter_by(user_id=current_user.id).all()

    kritik = [s for s in sertifikalar if 0 <= s.kalan_gun <= 30]
    uyari  = [s for s in sertifikalar if 30 < s.kalan_gun <= 60]
    notice = [s for s in sertifikalar if 60 < s.kalan_gun <= 90]
    dolmus = [s for s in sertifikalar if s.kalan_gun < 0]
    iyi    = [s for s in sertifikalar if s.kalan_gun > 90]

    return render_template('dashboard.html',
        kritik=kritik, uyari=uyari, notice=notice,
        dolmus=dolmus, iyi=iyi, toplam=len(sertifikalar))

@app.route('/sertifikalar')
@login_required
def sertifikalar():
    liste = Sertifika.query.filter_by(user_id=current_user.id)\
                           .order_by(Sertifika.bitis).all()
    return render_template('sertifikalar.html', sertifikalar=liste)

@app.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    if request.method == 'POST':
        s = Sertifika(
            user_id       = current_user.id,
            sertifika_adi = request.form['sertifika_adi'],
            sertifika_turu= request.form['sertifika_turu'],
            veren_kuruluş = request.form['veren_kurulus'],
            baslangic     = datetime.strptime(request.form['baslangic'], '%Y-%m-%d').date(),
            bitis         = datetime.strptime(request.form['bitis'], '%Y-%m-%d').date(),
            notlar        = request.form['notlar']
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
        s.veren_kuruluş  = request.form['veren_kurulus']
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
            firma_adi = request.form['firma_adi'],
            email     = request.form['email'],
            password  = generate_password_hash(request.form['password'])
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

# ── Otomatik E-posta ──────────────────────────────────────────────────────────

def gunluk_kontrol():
    with app.app_context():
        bugun = date.today()
        esikler = [90, 60, 30]
        sertifikalar = Sertifika.query.all()
        for s in sertifikalar:
            kalan = s.kalan_gun
            if kalan in esikler:
                kullanici = User.query.get(s.user_id)
                try:
                    msg = Message(
                        subject=f'⚠️ Sertifika Uyarısı: {s.sertifika_adi} — {kalan} gün kaldı',
                        sender=app.config['MAIL_USERNAME'],
                        recipients=[kullanici.email]
                    )
                    msg.body = f"""
Sayın {kullanici.firma_adi},

"{s.sertifika_adi}" sertifikanızın geçerlilik süresi {kalan} gün içinde dolacaktır.

Sertifika Türü : {s.sertifika_turu}
Veren Kuruluş  : {s.veren_kuruluş}
Bitiş Tarihi   : {s.bitis.strftime('%d.%m.%Y')}

Lütfen yenileme işlemlerini başlatınız.

Sertifika Takip Sistemi
                    """
                    mail.send(msg)
                except Exception as e:
                    print(f"E-posta gönderilemedi: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(gunluk_kontrol, 'cron', hour=8, minute=0)
scheduler.start()

# ── Başlat ────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=False)

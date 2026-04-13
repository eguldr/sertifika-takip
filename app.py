import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta, date
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gizli-anahtar-123')

# Veritabanı bağlantı ayarı
uri = os.environ.get('DATABASE_URL')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri or 'sqlite:///sertifika.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# Veritabanı Modelleri
class User(UserMixin, db.Model):
    __tablename__ = 'kullanici_tablosu'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(256))
    company_name = db.Column(db.String(100))
    is_admin = db.Column(db.Boolean, default=False)

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    category = db.Column(db.String(50))
    title = db.Column(db.String(100))
    start_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    risk_value = db.Column(db.String(100))
    whatsapp_notif = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Rotalar (Routes) ---

@app.route('/')
@app.route('/')
def index():
    from flask import make_response, render_template
    # Tarayıcıya 'bu bir metin değil, HTML sayfasıdır' diyoruz
    resp = make_response(render_template('login.html'))
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('E-posta veya şifre hatalı!')
    return render_template('login.html')

@app.route('/kayit', methods=['GET', 'POST'])
def kayit():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        company = request.form.get('company_name')
        if User.query.filter_by(email=email).first():
            flash('Bu e-posta zaten kayıtlı!')
            return redirect(url_for('kayit'))
        new_user = User(
            email=email,
            password=generate_password_hash(password),
            company_name=company,
            is_admin=True
        )
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/dashboard')
@login_required
def dashboard():
    bugun = date.today()
    gun_30 = bugun + timedelta(days=30)
    gun_60 = bugun + timedelta(days=60)
    gun_90 = bugun + timedelta(days=90)
    
    tum_kayitlar = Entry.query.filter_by(user_id=current_user.id).all()
    
    counts = {
        'urun': Entry.query.filter_by(user_id=current_user.id, category='Urun').count(),
        'arac': Entry.query.filter_by(user_id=current_user.id, category='Arac').count(),
        'pers': Entry.query.filter_by(user_id=current_user.id, category='Personel').count(),
        'tesis': Entry.query.filter_by(user_id=current_user.id, category='Tesis').count()
    }
    
    suresi_dolan = [e for e in tum_kayitlar if e.expiry_date and e.expiry_date < bugun]
    kritik_30 = [e for e in tum_kayitlar if e.expiry_date and bugun <= e.expiry_date <= gun_30]
    uyari_60 = [e for e in tum_kayitlar if e.expiry_date and gun_30 < e.expiry_date <= gun_60]
    bilgi_90 = [e for e in tum_kayitlar if e.expiry_date and gun_60 < e.expiry_date <= gun_90]
    
    kat_isim = {'Urun': 'Üretim & Ürün', 'Arac': 'Araç & Filo', 'Personel': 'Personel & SRC', 'Tesis': 'Tesis & Mekan'}
    
    return render_template('dashboard.html', 
                           user=current_user, **counts,
                           suresi_dolan=suresi_dolan, kritik_30=kritik_30, 
                           uyari_60=uyari_60, bilgi_90=bilgi_90, 
                           kat_isim=kat_isim, bugun=bugun)

@app.route('/sertifikalar')
@login_required
def sertifikalar():
    category = request.args.get('cat')
    bugun = date.today()
    items = Entry.query.filter_by(user_id=current_user.id, category=category).all()
    for item in items:
        if item.expiry_date:
            diff = (item.expiry_date - bugun).days
            if diff < 0:
                item.durum, item.durum_text = 'danger', 'Süresi Doldu'
            elif diff <= 30:
                item.durum, item.durum_text = 'danger', f'{diff} gün kaldı'
            elif diff <= 60:
                item.durum, item.durum_text = 'warning', f'{diff} gün kaldı'
            else:
                item.durum, item.durum_text = 'success', f'{diff} gün kaldı'
        else:
            item.durum, item.durum_text = 'secondary', 'Tarih yok'
    return render_template('sertifikalar.html', items=items, category=category, bugun=bugun)

@app.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    if request.method == 'POST':
        expiry_str = request.form.get('expiry_date')
        expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d').date() if expiry_str else None
        new_entry = Entry(
            user_id=current_user.id,
            category=request.form.get('category'),
            title=request.form.get('title'),
            expiry_date=expiry_date,
            risk_value=request.form.get('risk_value', '')
        )
        db.session.add(new_entry)
        db.session.commit()
        return redirect(url_for('sertifikalar', cat=new_entry.category))
    return render_template('ekle.html')

@app.route('/sil/<int:id>')
@login_required
def sil(id):
    item = Entry.query.get(id)
    if item and item.user_id == current_user.id:
        cat = item.category
        db.session.delete(item)
        db.session.commit()
        return redirect(url_for('sertifikalar', cat=cat))
    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))
@app.route('/admin/')
@login_required
def admin():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    users = User.query.all()
    return render_template('admin.html', users=users)

# Tabloları oluşturma
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run()

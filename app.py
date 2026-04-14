import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta, date
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gizli-anahtar-123456')

uri = os.environ.get('DATABASE_URL')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

class User(UserMixin, db.Model):
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
    firma_adi = db.Column(db.String(100))
    whatsapp_no = db.Column(db.String(20)) # YENİ: WhatsApp Numarası
    expiry_date = db.Column(db.Date)
    risk_value = db.Column(db.String(100))

class HatirlatmaLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer)
    firma_adi = db.Column(db.String(100))
    belge_adi = db.Column(db.String(100))
    tarih = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def tablo_kur():
    db.create_all()

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Hata!')
    return render_template('login.html')

@app.route('/kayit', methods=['GET', 'POST'])
def kayit():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        new_user = User(email=email, password=generate_password_hash(password), is_admin=True)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('kayit.html')

@app.route('/dashboard')
@login_required
def dashboard():
    bugun = date.today()
    tum = Entry.query.filter_by(user_id=current_user.id).all()
    urun = Entry.query.filter_by(user_id=current_user.id, category='Urun').count()
    arac = Entry.query.filter_by(user_id=current_user.id, category='Arac').count()
    pers = Entry.query.filter_by(user_id=current_user.id, category='Personel').count()
    tesis = Entry.query.filter_by(user_id=current_user.id, category='Tesis').count()
    
    suresi_dolan = [e for e in tum if e.expiry_date and e.expiry_date < bugun]
    kritik_30 = [e for e in tum if e.expiry_date and bugun <= e.expiry_date <= bugun + timedelta(days=30)]
    
    kat_isim = {'Urun':'Ürün','Arac':'Araç','Personel':'Personel','Tesis':'Tesis'}
    return render_template('dashboard.html', urun=urun, arac=arac, pers=pers, tesis=tesis, suresi_dolan=suresi_dolan, kritik_30=kritik_30, bugun=bugun, kat_isim=kat_isim)

@app.route('/sertifikalar')
@login_required
def sertifikalar():
    cat = request.args.get('cat')
    items = Entry.query.filter_by(user_id=current_user.id, category=cat).all()
    bugun = date.today()
    for item in items:
        if item.expiry_date:
            item.kalan_gun = (item.expiry_date - bugun).days
            if item.kalan_gun < 0: item.durum = 'danger'
            elif item.kalan_gun <= 30: item.durum = 'danger'
            elif item.kalan_gun <= 60: item.durum = 'warning'
            else: item.durum = 'success'
        else:
            item.kalan_gun = None
            item.durum = 'secondary'
    return render_template('sertifikalar.html', items=items, bugun=bugun, cat=cat)

@app.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    if request.method == 'POST':
        exp_str = request.form.get('expiry_date')
        new_entry = Entry(
            user_id=current_user.id,
            category=request.form.get('category'),
            title=request.form.get('title'),
            firma_adi=request.form.get('firma_adi'),
            whatsapp_no=request.form.get('whatsapp_no'), # WhatsApp No eklendi
            risk_value=request.form.get('risk_value'),
            expiry_date=datetime.strptime(exp_str, '%Y-%m-%d').date() if exp_str else None
        )
        db.session.add(new_entry)
        db.session.commit()
        return redirect(url_for('sertifikalar', cat=new_entry.category))
    return render_template('ekle.html')

@app.route('/log_ekle/<int:id>')
@login_required
def log_ekle(id):
    item = Entry.query.get(id)
    if item:
        yeni_log = HatirlatmaLog(entry_id=item.id, firma_adi=item.firma_adi, belge_adi=item.title)
        db.session.add(yeni_log)
        db.session.commit()
    return "OK"

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    logs = HatirlatmaLog.query.order_by(HatirlatmaLog.tarih.desc()).limit(20).all()
    users = User.query.all()
    return render_template('admin.html', logs=logs, users=users)

@app.route('/sil/<int:id>')
@login_required
def sil(id):
    item = Entry.query.get(id)
    if item:
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

if __name__ == '__main__':
    app.run()

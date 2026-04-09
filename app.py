import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gizli-anahtar')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
db = SQLAlchemy(app)

# 4 ANA MODÜL İÇİN VERİTABANI MODELİ
class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    category = db.Column(db.String(50)) # Urun, Arac, Personel, Tesis
    title = db.Column(db.String(100))
    expiry_date = db.Column(db.Date)
    risk_value = db.Column(db.String(100)) # "150.000 TL" gibi
    whatsapp_notif = db.Column(db.Boolean, default=False)

# ... (Login ve Mail Ayarları Buraya Gelecek) ...

@app.route('/dashboard')
@login_required
def dashboard():
    # 4 kategori için ayrı ayrı sayıları hesaplayıp dashboard'a gönderiyoruz
    urun_count = Entry.query.filter_by(user_id=current_user.id, category='Urun').count()
    arac_count = Entry.query.filter_by(user_id=current_user.id, category='Arac').count()
    pers_count = Entry.query.filter_by(user_id=current_user.id, category='Personel').count()
    tesis_count = Entry.query.filter_by(user_id=current_user.id, category='Tesis').count()
    return render_template('dashboard.html', urun=urun_count, arac=arac_count, pers=pers_count, tesis=tesis_count)

# ... (Kayıt ve Ekleme Fonksiyonları) ...

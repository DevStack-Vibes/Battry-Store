import os
from datetime import datetime

class Config:
    SECRET_KEY = 'your-secret-key-here-change-in-production'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///database.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SHOP_NAME = "Haideri Battery Store"
    SHOP_ADDRESS = "NoorKot Road, Sakhargarh"
    SALESMAN_NAME = "Musawar Apal"
    PHONE_NUMBER = "03005016501"
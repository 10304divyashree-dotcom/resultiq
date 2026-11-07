import os
from app import create_app
from models import db

config_name = os.environ.get('FLASK_CONFIG', 'production')
app = create_app(config_name)

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run()


import os
import sys
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_ROOT, ".env"))

sys.path.insert(0, os.path.join(_ROOT, "api_meta"))
sys.path.insert(0, os.path.join(_ROOT, "api_sotilma"))

from flask import Flask
from webhook import webhook_bp

app = Flask(__name__)
app.register_blueprint(webhook_bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7000, debug=False, threaded=True)

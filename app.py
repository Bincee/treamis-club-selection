from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Render deployment successful — ready to upload firebase_key.json!"

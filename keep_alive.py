import os
from threading import Thread

from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return "Saphir est en ligne."


def run():
    port = int(os.environ.get("PORT", 8080))
    # serveur WSGI de production (waitress) au lieu du serveur de développement Flask,
    # que la doc Flask déconseille en production ; repli sur app.run si waitress manque.
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port)
    except ImportError:
        app.run(host="0.0.0.0", port=port)


def keep_alive():
    Thread(target=run, daemon=True).start()

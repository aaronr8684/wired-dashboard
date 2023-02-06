import configparser
import logging
from flask import Flask, jsonify, render_template, request, make_response

config = configparser.ConfigParser()
config.read('env/config.ini')

app = Flask(__name__)

@app.route("/")
def home():
    response = make_response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-store, must-revalidate" # HTTP 1.1.
    return response

if __name__ == '__main__':
    app.run(debug=True)

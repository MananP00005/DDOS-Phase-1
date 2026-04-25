from flask import Flask, jsonify, render_template, abort, redirect
import time
import os
import threading

app = Flask(__name__)

active_requests = 0
total_requests  = 0
lock = threading.Lock()

PAGES = ['programs', 'about', 'admissions', 'research']

@app.route('/')
@app.route('/index.html')
def index():
    global total_requests
    with lock:
        total_requests += 1
    return render_template('index.html')

@app.route('/pages/<page_name>.html')
def pages(page_name):
    global total_requests
    with lock:
        total_requests += 1
    if page_name not in PAGES:
        abort(404)
    return render_template(f'pages/{page_name}.html')

@app.route('/heavy')
def heavy():
    global active_requests, total_requests
    with lock:
        active_requests += 1
        total_requests  += 1
    try:
        result = 0
        for i in range(500000):
            result += i * i
        time.sleep(0.5)
        return jsonify({
            "status": "ok",
            "result": result,
            "message": "Request processed"
        })
    finally:
        with lock:
            active_requests -= 1

@app.route('/api/data')
def api_data():
    global total_requests
    with lock:
        total_requests += 1
    time.sleep(0.1)
    return jsonify({
        "students": 42000,
        "programs": 180,
        "status":   "operational"
    })

@app.route('/status')
def status():
    return jsonify({
        "active_requests": active_requests,
        "total_requests":  total_requests,
        "workers":         3,
        "status":          "running"
    })

@app.route('/ping')
def ping():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)

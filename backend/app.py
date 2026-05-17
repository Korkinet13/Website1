from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
import os
import uuid
import time
import threading
from datetime import date

import subprocess



app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

DOWNLOAD_FOLDER = "/tmp/downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# -------------------------
# MEMORY STORAGE
# -------------------------
user_downloads = {}  # {ip: {date: count}}

@app.route("/usage", methods=["GET"])
def usage():

    user = request.remote_addr
    today = str(date.today())

    if user not in user_downloads:
        user_downloads[user] = {}

    used = user_downloads[user].get(today, 0)

    return jsonify({
        "used": used,
        "limit": 10
    })
# -------------------------
# CLEANUP THREAD (15 min)
# -------------------------
def cleanup_files():
    while True:
        time.sleep(900)  # 15 minutes

        now = time.time()

        for file in os.listdir(DOWNLOAD_FOLDER):
            path = os.path.join(DOWNLOAD_FOLDER, file)

            if os.path.isfile(path):
                # delete everything older than 15 min
                if now - os.path.getctime(path) > 900:
                    try:
                        os.remove(path)
                        print("Deleted:", file)
                    except:
                        pass


#threading.Thread(target=cleanup_files, daemon=True).start()


# -------------------------
# HELPERS
# -------------------------
def get_user():
    return request.remote_addr


def check_limit(user):
    today = str(date.today())

    if user not in user_downloads:
        user_downloads[user] = {}

    if user_downloads[user].get(today, 0) >= 10:
        return False

    return True


def check_duration(info):
    return info.get("duration", 0) <= 15 * 60


# -------------------------
# DOWNLOAD ROUTE
# -------------------------
@app.route("/download", methods=["GET"])
def download():

    url = request.args.get("url")
    format_type = request.args.get("format", "mp4")
    quality = request.args.get("quality", "best")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    user = get_user()

    # -------------------------
    # LIMIT CHECK (10/day)
    # -------------------------
    if not check_limit(user):
        return jsonify({"error": "Daily limit reached (10 downloads)"}), 429

    # -------------------------
    # GET VIDEO INFO (NO DOWNLOAD YET)
    # -------------------------
    try:
        with YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError:
        return jsonify({"error": "Invalid or unavailable video"}), 400

    # -------------------------
    # DURATION CHECK (15 min)
    # -------------------------
    if not check_duration(info):
        return jsonify({"error": "Video too long (max 15 minutes)"}), 400

    file_id = str(uuid.uuid4())
    outtmpl = f"{DOWNLOAD_FOLDER}/{file_id}.%(ext)s"

    # -------------------------
    # MP3 MODE
    # -------------------------
    if format_type == "mp3":

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }],
        }

    # -------------------------
    # MP4 MODE
    # -------------------------
    else:

        h = int(quality) if quality != "best" else None

        fmt = (
            f"bestvideo[height<={h}]+bestaudio[ext=m4a]/best"
            if h else
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
        )

        ydl_opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
        }

    # -------------------------
    # DOWNLOAD
    # -------------------------
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    filename = None
    for f in os.listdir(DOWNLOAD_FOLDER):
        if f.startswith(file_id):
            filename = os.path.join(DOWNLOAD_FOLDER, f)
            break
            
    if format_type == "mp3":
        filename = filename.rsplit(".", 1)[0] + ".mp3"
    today = str(date.today())
    user_downloads[user][today] = user_downloads[user].get(today, 0) + 1
    return send_file(filename, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

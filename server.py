\
# server.py
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from pathlib import Path
import threading, uuid, datetime, json, os, csv

app = Flask(__name__)
CORS(app)

LOCK = threading.Lock()

CONFIG_FILE = Path("config.json")

STATE = {
    "vehicles": [],
    "logs": [],
    "storage_path": None
}

CSV_FILENAME = "logs.csv"
JSON_FILENAME = "logs.json"

def now_iso_local():
    return datetime.datetime.now().replace(microsecond=0).isoformat(sep=' ')

def ensure_storage_path(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def csv_path():
    return Path(STATE["storage_path"]) / CSV_FILENAME

def json_path():
    return Path(STATE["storage_path"]) / JSON_FILENAME

def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"storage_path": str(STATE["storage_path"]) if STATE["storage_path"] else None}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Failed to save config:", e)

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                p = cfg.get("storage_path")
                if p:
                    STATE["storage_path"] = str(p)
        except Exception as e:
            print("Failed to load config:", e)

def save_to_disk():
    with LOCK:
        if not STATE["storage_path"]:
            return
        p = Path(STATE["storage_path"])
        ensure_storage_path(p)
        # JSON
        with open(json_path(), "w", encoding="utf-8") as f:
            json.dump(STATE["logs"], f, ensure_ascii=False, indent=2)
        # CSV
        headers = ["id","vehicle","direction","route","departAt","returnAt","status"]
        with open(csv_path(), "w", encoding="utf-8", newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)
            for r in STATE["logs"]:
                writer.writerow([
                    r.get("id",""),
                    r.get("vehicle",""),
                    r.get("direction",""),
                    r.get("route",""),
                    r.get("departAt",""),
                    r.get("returnAt",""),
                    r.get("status","")
                ])

@app.route("/api/vehicles", methods=["GET"])
def get_vehicles():
    return jsonify(STATE["vehicles"])

@app.route("/api/vehicles", methods=["POST"])
def add_vehicle():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error":"empty name"}), 400
    if name in STATE["vehicles"]:
        return jsonify({"error":"exists"}), 400
    STATE["vehicles"].append(name)
    save_to_disk()
    return jsonify({"ok":True, "name":name})

@app.route("/api/dispatch", methods=["POST"])
def dispatch():
    data = request.get_json(force=True)
    vehicle = (data.get("vehicle") or "").strip()
    direction = (data.get("direction") or "").strip()
    route = (data.get("route") or "").strip()
    if not vehicle or not direction:
        return jsonify({"error":"vehicle and direction required"}), 400
    rec = {
        "id": str(uuid.uuid4()),
        "vehicle": vehicle,
        "direction": direction,
        "route": route,
        "departAt": now_iso_local(),
        "returnAt": None,
        "status": "В рейсе"
    }
    STATE["logs"].append(rec)
    save_to_disk()
    return jsonify(rec)

@app.route("/api/return", methods=["POST"])
def mark_return():
    data = request.get_json(force=True)
    rid = data.get("id")
    if not rid:
        return jsonify({"error":"id required"}), 400
    found = None
    for r in STATE["logs"]:
        if r.get("id") == rid:
            found = r
            break
    if not found:
        return jsonify({"error":"not found"}), 404
    if found.get("status") != "В рейсе":
        return jsonify({"error":"already closed"}), 400
    found["returnAt"] = now_iso_local()
    found["status"] = "В гараже"
    save_to_disk()
    return jsonify(found)

@app.route("/api/logs", methods=["GET"])
def get_logs():
    return jsonify(STATE["logs"])

@app.route("/api/set_path", methods=["POST"])
def set_path():
    data = request.get_json(force=True)
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error":"path required"}), 400
    p = Path(path)
    try:
        p = p.resolve()
    except Exception as e:
        return jsonify({"error":"invalid path", "detail": str(e)}), 400
    if not p.is_absolute():
        return jsonify({"error":"path must be absolute"}), 400
    try:
        ensure_storage_path(p)
    except Exception as e:
        return jsonify({"error":"cannot create path", "detail": str(e)}), 500
    STATE["storage_path"] = str(p)
    save_config()
    save_to_disk()
    return jsonify({"ok":True, "path": str(p)})

@app.route("/api/export_csv", methods=["GET"])
def export_csv():
    if not STATE["storage_path"]:
        return jsonify({"error":"storage path not set"}), 400
    p = csv_path()
    if not p.exists():
        save_to_disk()
    try:
        return send_file(str(p), as_attachment=True, download_name=p.name)
    except Exception as e:
        return jsonify({"error":"can't send file", "detail": str(e)}), 500

@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({
        "ok": True,
        "storage_path": STATE["storage_path"],
        "vehicles_count": len(STATE["vehicles"]),
        "logs_count": len(STATE["logs"])
    })

@app.route("/api/reset", methods=["POST"])
def reset_all():
    with LOCK:
        sp = STATE.get("storage_path")
        try:
            if sp:
                p_csv = Path(sp) / CSV_FILENAME
                p_json = Path(sp) / JSON_FILENAME
                if p_csv.exists():
                    p_csv.unlink()
                if p_json.exists():
                    p_json.unlink()
            STATE["logs"].clear()
            STATE["vehicles"].clear()
            if CONFIG_FILE.exists():
                try:
                    CONFIG_FILE.unlink()
                except Exception:
                    pass
            STATE["storage_path"] = None
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error":"reset failed", "detail": str(e)}), 500

if __name__ == "__main__":
    load_config = lambda: None
    # try to load config file
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
                p = cfg.get("storage_path")
                if p:
                    STATE["storage_path"] = str(p)
    except Exception:
        pass

    if not STATE.get("storage_path"):
        try:
            input_path = input("Введите абсолютный путь для сохранения CSV/JSON (например D:\\\\logs\\\\tracker) and press Enter: ").strip()
        except Exception:
            input_path = None
        if input_path:
            try:
                p = Path(input_path).resolve()
                ensure_storage_path(p)
                STATE["storage_path"] = str(p)
                save_config()
            except Exception as e:
                print("Не удалось создать указанный путь:", e)
                STATE["storage_path"] = str(Path("C:/fleet-tracker-data").resolve())
                ensure_storage_path(Path(STATE["storage_path"]))
        else:
            STATE["storage_path"] = str(Path("C:/fleet-tracker-data").resolve())
            ensure_storage_path(Path(STATE["storage_path"]))

    # try to load existing logs.json if present
    try:
        jpath = Path(STATE["storage_path"]) / JSON_FILENAME
        if jpath.exists():
            with open(jpath, "r", encoding="utf-8") as f:
                STATE["logs"] = json.load(f)
    except Exception:
        pass

    app.run(host="0.0.0.0", port=5000, debug=True)

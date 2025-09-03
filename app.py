import os
import json
from collections import Counter
from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, send_file
)

app = Flask(__name__)
app.secret_key = "your_secret_key"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

CURRENT_DATA_PATH = os.path.join(UPLOAD_FOLDER, "current_data.json")
UNIT_SCOPE_PATH = os.path.join(UPLOAD_FOLDER, "unit_scope.json")
MAPPING_FILE = os.path.join(BASE_DIR, "donvi_mapping.json")
ALLOWED_EXTENSIONS = {"json"}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def load_mapping() -> dict:
    if not os.path.exists(MAPPING_FILE):
        return {}
    with open(MAPPING_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_unit_scope() -> str:
    if not os.path.exists(UNIT_SCOPE_PATH):
        return ""
    try:
        with open(UNIT_SCOPE_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("unit_scope", "")
    except Exception:
        return ""

def save_unit_scope(unit_scope: str) -> None:
    with open(UNIT_SCOPE_PATH, "w", encoding="utf-8") as f:
        json.dump({"unit_scope": unit_scope}, f)

def filter_mapping_by_scope(mapping: dict, scope: str) -> dict:
    if not scope:
        return mapping
    return {k: v for k, v in mapping.items() if k.startswith(scope[:14])}

def load_data() -> list:
    if not os.path.exists(CURRENT_DATA_PATH):
        return []
    with open(CURRENT_DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
        if isinstance(raw, dict) and "data" in raw:
            return raw["data"]
        return raw if isinstance(raw, list) else []

def save_data(data: list) -> None:
    with open(CURRENT_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump({"data": data}, f, ensure_ascii=False, indent=2)

def get_soldier_id(d: dict) -> str:
    # ép chuỗi và bỏ xuống dòng, khoảng trắng
    sid = d.get("So_HSQ_BS") or d.get("So_CMSQ_CMQNCN_CMCCQP") or ""
    return str(sid).strip()


def get_soldier_name(d: dict) -> str:
    return d.get("personal_info", {}).get("ho_chu_dem_ten", "")

def sort_by_mapping(data: list, mapping: dict) -> list:
    mapping_order = list(mapping.keys())
    def order_key(item: dict) -> int:
        code = item.get("don_vi", "")
        try:
            return mapping_order.index(code)
        except ValueError:
            return len(mapping_order)
    return sorted(data, key=order_key)

def enrich_and_filter(data: list, mapping: dict) -> list:
    filtered = []
    for d in data:
        code = d.get("don_vi", "")
        if code not in mapping:
            continue
        dd = dict(d)
        soldier_id = get_soldier_id(d)
        # loại bỏ \n, khoảng trắng thừa
        dd["id"] = str(soldier_id).strip()
        dd["don_vi_name"] = mapping.get(code, code)
        filtered.append(dd)
    return filtered


@app.route("/", methods=["GET"])
def index():
    mapping_all = load_mapping()
    unit_scope = load_unit_scope()
    mapping = filter_mapping_by_scope(mapping_all, unit_scope)

    data_raw = load_data()
    data = enrich_and_filter(data_raw, mapping)

    filter_unit = request.args.get("don_vi", "").strip()
    if filter_unit:
        data = [d for d in data if d.get("don_vi") == filter_unit]

    data = sort_by_mapping(data, mapping)

    all_filtered = enrich_and_filter(data_raw, mapping)
    counts = Counter(d.get("don_vi") for d in all_filtered if d.get("don_vi"))
    stats = [
        {"code": code, "name": mapping.get(code, code), "count": counts.get(code, 0)}
        for code in mapping.keys()
    ]

    return render_template(
        "index.html",
        data=data,
        mapping=mapping,
        total=len(data),
        stats=stats,
        filter_unit=filter_unit,
        unit_scope=unit_scope
    )

@app.route("/upload", methods=["POST"])
def upload():
    unit_scope = request.form.get("unit_scope", "").strip()
    if not unit_scope:
        return "Vui lòng chọn đơn vị gốc trước khi tải lên", 400
    save_unit_scope(unit_scope)

    file = request.files.get("data_file")
    if not file or file.filename == "":
        return "Vui lòng chọn file .json", 400
    if not allowed_file(file.filename):
        return "Chỉ chấp nhận file JSON", 400

    try:
        payload = json.load(file)
    except Exception:
        return "File JSON không hợp lệ", 400

    if isinstance(payload, dict) and "data" in payload:
        data = payload["data"]
    elif isinstance(payload, list):
        data = payload
    else:
        return "Cấu trúc JSON không hợp lệ", 400

    save_data(data)
    return redirect(url_for("index"))

@app.route("/search")
def search():
    query = (request.args.get("q") or "").strip().lower()
    unit_filter = (request.args.get("don_vi") or "").strip()

    mapping_all = load_mapping()
    unit_scope = load_unit_scope()
    mapping = filter_mapping_by_scope(mapping_all, unit_scope)
    data_raw = load_data()

    results = []
    for d in enrich_and_filter(data_raw, mapping):
        if unit_filter and d.get("don_vi") != unit_filter:
            continue
        if query and query not in get_soldier_name(d).lower():
            continue
        results.append({
            "id": get_soldier_id(d),
            "ho_chu_dem_ten": get_soldier_name(d),
            "don_vi": d.get("don_vi") or "",
            "don_vi_name": mapping.get(d.get("don_vi", ""), d.get("don_vi", ""))
        })

    results = sort_by_mapping(results, mapping)
    return jsonify(results)

@app.route("/update", methods=["POST"])
def update():
    soldier_id = (request.form.get("id") or "").strip()
    new_don_vi = request.form.get("don_vi") or ""
    filter_unit = request.form.get("filter_unit") or ""

    mapping_all = load_mapping()
    unit_scope = load_unit_scope()
    mapping = filter_mapping_by_scope(mapping_all, unit_scope)

    if new_don_vi and new_don_vi not in mapping:
        return redirect(url_for("index", don_vi=filter_unit))

    data = load_data()
    updated = False
    for d in data:
        # ép lại id gốc để so sánh
        if get_soldier_id(d) == soldier_id:
            d["don_vi"] = new_don_vi
            updated = True
            break

    if updated:
        save_data(data)
    return redirect(url_for("index", don_vi=filter_unit))


@app.route("/bulk_update", methods=["POST"])
def bulk_update():
    ids = request.form.getlist("ids")
    new_don_vi = request.form.get("don_vi") or ""
    filter_unit = request.form.get("filter_unit") or ""

    mapping_all = load_mapping()
    unit_scope = load_unit_scope()
    mapping = filter_mapping_by_scope(mapping_all, unit_scope)

    if new_don_vi and new_don_vi not in mapping:
        return redirect(url_for("index", don_vi=filter_unit))

    data = load_data()
    id_set = set(ids)
    for d in data:
        if get_soldier_id(d) in id_set:
            d["don_vi"] = new_don_vi
    save_data(data)
    return redirect(url_for("index", don_vi=filter_unit))

@app.route("/delete", methods=["POST"])
def delete():
    soldier_id = request.form.get("id") or ""
    filter_unit = request.form.get("filter_unit") or ""
    data = load_data()
    new_data = [d for d in data if get_soldier_id(d) != soldier_id]
    save_data(new_data)
    return redirect(url_for("index", don_vi=filter_unit))

@app.route("/download")
def download():
    if not os.path.exists(CURRENT_DATA_PATH):
        return "Chưa có dữ liệu để tải", 400
    return send_file(
        CURRENT_DATA_PATH,
        as_attachment=True,
        download_name="data_processed.json",
        mimetype="application/json"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5005)), debug=True)

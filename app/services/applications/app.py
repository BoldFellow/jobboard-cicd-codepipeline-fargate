import os
import uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort
from jobboard_common.ddb import put_item, get_item, scan_items, query_by_gsi

app = Flask(__name__)
APPLICATIONS_TABLE = os.environ["APPLICATIONS_TABLE"]


@app.route("/", methods=["GET"])
def index():
    return jsonify({"service": "applications-api", "status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "applications-api"}), 200


@app.route("/applications", methods=["POST"])
def create_application():
    body = request.get_json(force=True)
    if not body.get("job_id") or not body.get("applicant_name") or not body.get("applicant_email"):
        abort(400)
    item = {
        "application_id": str(uuid.uuid4()),
        "job_id": body["job_id"],
        "applicant_name": body["applicant_name"],
        "applicant_email": body["applicant_email"],
        "resume_summary": body.get("resume_summary", ""),
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "status": "submitted",
    }
    put_item(APPLICATIONS_TABLE, item)
    return jsonify(item), 201


@app.route("/applications", methods=["GET"])
def list_applications():
    job_id = request.args.get("job_id")
    if job_id:
        items = query_by_gsi(APPLICATIONS_TABLE, "job_id-index", "job_id", job_id)
    else:
        items = scan_items(APPLICATIONS_TABLE)
    return jsonify(items), 200


@app.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    item = get_item(APPLICATIONS_TABLE, {"application_id": application_id})
    if not item:
        abort(404)
    return jsonify(item), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081)

import os
import uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort
from jobboard_common.ddb import put_item, get_item, delete_item, scan_items

app = Flask(__name__)
JOBS_TABLE = os.environ["JOBS_TABLE"]


@app.route("/", methods=["GET"])
def index():
    return jsonify({"service": "jobs-api", "status": "ok", "version": "v2"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "jobs-api"}), 200


@app.route("/jobs", methods=["POST"])
def create_job():
    body = request.get_json(force=True)
    if not body.get("title"):
        abort(400)
    item = {
        "job_id": str(uuid.uuid4()),
        "title": body["title"],
        "company": body.get("company", ""),
        "description": body.get("description", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "open",
    }
    put_item(JOBS_TABLE, item)
    return jsonify(item), 201


@app.route("/jobs", methods=["GET"])
def list_jobs():
    raise RuntimeError("simulated database connection failure")
    return jsonify(scan_items(JOBS_TABLE)), 200


@app.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    item = get_item(JOBS_TABLE, {"job_id": job_id})
    if not item:
        abort(404)
    return jsonify(item), 200


@app.route("/jobs/<job_id>", methods=["PUT"])
def update_job(job_id):
    body = request.get_json(force=True)
    item = get_item(JOBS_TABLE, {"job_id": job_id})
    if not item:
        abort(404)
    item.update({k: v for k, v in body.items() if k != "job_id"})
    put_item(JOBS_TABLE, item)
    return jsonify(item), 200


@app.route("/jobs/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    if not get_item(JOBS_TABLE, {"job_id": job_id}):
        abort(404)
    delete_item(JOBS_TABLE, {"job_id": job_id})
    return "", 204


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

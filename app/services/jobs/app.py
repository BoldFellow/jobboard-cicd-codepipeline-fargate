import os
import uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort, render_template_string
from jobboard_common.ddb import put_item, get_item, delete_item, scan_items

app = Flask(__name__)
JOBS_TABLE = os.environ["JOBS_TABLE"]

JOBS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Job Board</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
  <nav class="navbar navbar-dark bg-primary mb-4">
    <div class="container">
      <span class="navbar-brand fw-bold">Job Board</span>
    </div>
  </nav>
  <div class="container">
    <h4 class="mb-3">Open Positions</h4>
    <div class="row">
      {% for job in jobs %}
      <div class="col-md-4 mb-4">
        <div class="card h-100">
          <div class="card-body">
            <h5 class="card-title">{{ job.get('title', '') }}</h5>
            <h6 class="card-subtitle mb-2 text-muted">{{ job.get('company', '') }}</h6>
            <p class="card-text text-muted mb-0">{{ job.get('location', 'On-site') }}</p>
            <span class="badge bg-success">{{ job.get('salary', 'Competitive') }}</span>
          </div>
          <div class="card-footer text-muted">
            <small>Posted: {{ job.get('created_at', '')[:10] }}</small>
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
    {% if not jobs %}
    <p class="text-muted">No open positions. Check back soon.</p>
    {% endif %}
  </div>
</body>
</html>"""


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
    items = scan_items(JOBS_TABLE)
    if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'text/html':
        return render_template_string(JOBS_HTML, jobs=items), 200, {'Cache-Control': 'no-store'}
    return jsonify(items), 200


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

import os
import uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort, render_template_string
from jobboard_common.ddb import put_item, get_item, scan_items, query_by_gsi

app = Flask(__name__)
APPLICATIONS_TABLE = os.environ["APPLICATIONS_TABLE"]

APPS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Applications</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
  <nav class="navbar navbar-dark bg-success mb-4">
    <div class="container">
      <span class="navbar-brand fw-bold">Job Applications</span>
    </div>
  </nav>
  <div class="container">
    <h4 class="mb-3">Applications</h4>
    <div class="row">
      {% for appl in apps %}
      <div class="col-md-4 mb-4">
        <div class="card h-100">
          <div class="card-body">
            <h5 class="card-title">{{ appl.get('applicant_name', '') }}</h5>
            <h6 class="card-subtitle mb-2 text-muted">{{ appl.get('applicant_email', '') }}</h6>
            <p class="card-text text-muted mb-0">Job ID: {{ appl.get('job_id', '')[:8] }}...</p>
          </div>
          <div class="card-footer text-muted">
            <small>Applied: {{ appl.get('applied_at', '')[:10] }}</small>
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
    {% if not apps %}
    <p class="text-muted">No applications yet.</p>
    {% endif %}
  </div>
</body>
</html>"""


@app.route("/", methods=["GET"])
def index():
    return jsonify({"service": "applications-api", "status": "ok", "version": "v2"}), 200


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
    if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'text/html':
        return render_template_string(APPS_HTML, apps=items), 200, {'Cache-Control': 'no-store'}
    return jsonify(items), 200


@app.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    item = get_item(APPLICATIONS_TABLE, {"application_id": application_id})
    if not item:
        abort(404)
    return jsonify(item), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081)

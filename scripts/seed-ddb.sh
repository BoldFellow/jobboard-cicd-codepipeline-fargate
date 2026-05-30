#!/bin/bash
# Seeds sample jobs and applications via the ALB endpoint.
# Usage: ./scripts/seed-ddb.sh <alb-dns-name>
set -euo pipefail

ALB=${1:-}
if [ -z "$ALB" ]; then
  echo "Usage: $0 <alb-dns-name>"
  exit 1
fi

BASE="http://$ALB"

echo "==> Creating sample jobs..."
JOB1=$(curl -sf -X POST "$BASE/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Senior SRE","company":"Acme Corp","description":"Manage production ECS clusters."}')
JOB2=$(curl -sf -X POST "$BASE/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Platform Engineer","company":"Beta LLC","description":"Build internal developer platform on AWS."}')

JOB1_ID=$(echo "$JOB1" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "  Created job: $JOB1_ID"

echo "==> Creating sample application for job $JOB1_ID..."
curl -sf -X POST "$BASE/applications" \
  -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"$JOB1_ID\",\"applicant_name\":\"Alice Smith\",\"applicant_email\":\"alice@example.com\",\"resume_summary\":\"5 years SRE at FAANG.\"}" > /dev/null

echo "==> Done."
echo ""
echo "Verify:"
echo "  curl $BASE/jobs"
echo "  curl $BASE/applications?job_id=$JOB1_ID"

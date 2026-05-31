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
  -d '{"title":"Senior SRE","company":"Acme Corp","description":"Manage production ECS clusters.","location":"Remote","salary":"$140k-$180k"}')
JOB2=$(curl -sf -X POST "$BASE/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Platform Engineer","company":"Beta LLC","description":"Build internal developer platform on AWS.","location":"New York, NY","salary":"$130k-$160k"}')

JOB1_ID=$(echo "$JOB1" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
JOB2_ID=$(echo "$JOB2" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "  Created job: $JOB1_ID"
echo "  Created job: $JOB2_ID"

echo "==> Creating sample applications..."
curl -sf -X POST "$BASE/applications" \
  -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"$JOB1_ID\",\"applicant_name\":\"Alice Smith\",\"applicant_email\":\"alice@example.com\",\"resume_summary\":\"5 years SRE at FAANG.\"}" > /dev/null

curl -sf -X POST "$BASE/applications" \
  -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"$JOB2_ID\",\"applicant_name\":\"Bob Jones\",\"applicant_email\":\"bob@example.com\",\"resume_summary\":\"3 years platform engineering at a Series B startup.\"}" > /dev/null

echo "==> Done."
echo ""
echo "Verify:"
echo "  curl $BASE/jobs"
echo "  curl $BASE/applications"
echo "  Browser: http://$ALB  (redirects to /jobs)"

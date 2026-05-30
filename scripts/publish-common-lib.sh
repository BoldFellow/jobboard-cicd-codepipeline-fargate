#!/bin/bash
# Publishes the jobboard_common wheel to CodeArtifact.
# Run once before the first pipeline execution.
#
# Usage:
#   ./scripts/publish-common-lib.sh [domain] [repo]
# Defaults to domain=jobboard-cicd, repo=jobboard-internal
set -euo pipefail

DOMAIN=${1:-jobboard-cicd}
REPO=${2:-jobboard-internal}
REGION=${AWS_DEFAULT_REGION:-us-east-1}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$SCRIPT_DIR/../app/lib/jobboard_common"
OUT_DIR="/tmp/jobboard-common-dist"

echo "==> Building jobboard-common wheel..."
rm -rf "$OUT_DIR"
pip install --quiet build twine
python -m build --wheel --outdir "$OUT_DIR" "$LIB_DIR"

echo "==> Logging twine into CodeArtifact domain=$DOMAIN repo=$REPO region=$REGION..."
aws codeartifact login --tool twine --domain "$DOMAIN" --repository "$REPO" --region "$REGION"

echo "==> Publishing wheel..."
twine upload --repository codeartifact "$OUT_DIR"/*.whl

echo "==> Done. Installed versions:"
aws codeartifact list-package-versions \
  --domain "$DOMAIN" \
  --repository "$REPO" \
  --package jobboard-common \
  --format pypi \
  --query 'versions[*].{version:version,status:status}' \
  --output table \
  --region "$REGION"

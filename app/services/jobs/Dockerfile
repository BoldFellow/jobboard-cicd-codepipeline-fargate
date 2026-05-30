FROM python:3.12-slim
# PIP_INDEX_URL is injected at build time by CodeBuild with CodeArtifact credentials.
# It resolves jobboard-common from the private repo and other packages via the upstream
# pypi.org proxy. In production, use Docker BuildKit --secret to avoid storing the token
# in image history.
ARG PIP_INDEX_URL=https://pypi.org/simple/
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt
COPY app.py .
EXPOSE 8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "--workers", "2", "--timeout", "30", "app:app"]

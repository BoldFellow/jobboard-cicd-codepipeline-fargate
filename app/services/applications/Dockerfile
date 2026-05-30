FROM python:3.12-slim
ARG PIP_INDEX_URL=https://pypi.org/simple/
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt
COPY app.py .
EXPOSE 8081
CMD ["gunicorn", "-b", "0.0.0.0:8081", "--workers", "2", "--timeout", "30", "app:app"]

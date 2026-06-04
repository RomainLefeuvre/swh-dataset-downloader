FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY downloader/ ./downloader/

# Output lands here; mount a host directory to persist it
VOLUME ["/app/output"]

ENTRYPOINT ["python", "-m", "downloader"]
CMD ["--help"]

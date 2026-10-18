FROM python:3.13-slim

WORKDIR /app

# Install curl, netcat for readiness checks, and ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    netcat-openbsd \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download AlloyDB Auth Proxy for Linux amd64
RUN curl -fsSL -o /usr/local/bin/alloydb-auth-proxy \
    https://storage.googleapis.com/alloydb-auth-proxy/v1.14.0/alloydb-auth-proxy.linux.amd64 \
    && chmod +x /usr/local/bin/alloydb-auth-proxy

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application directories and files
COPY app/ app/
COPY db/ db/
COPY scripts/ scripts/
RUN mkdir -p media_uploads
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV PORT=8080
ENV PYTHONUNBUFFERED=1
EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]

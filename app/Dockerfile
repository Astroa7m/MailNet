FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Run as a non-root user (security review F9); the mcp image already does this.
# /app is owned by appuser so the app can still write there if it needs to.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

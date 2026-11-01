FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 IHME_HOST=0.0.0.0 IHME_DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 ihme \
    && mkdir /app/data && chown ihme:ihme /app/data
COPY --chown=ihme:ihme app ./app
COPY --chown=ihme:ihme extension ./extension
COPY --chown=ihme:ihme main.py .
USER ihme
VOLUME ["/app/data"]
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/api/auth/status', timeout=4)"
CMD ["python", "main.py"]

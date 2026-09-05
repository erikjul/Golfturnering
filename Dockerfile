FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GOLF_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY golf ./golf
RUN useradd -r -u 10002 golf && mkdir -p /data && chown golf:golf /data
USER golf
VOLUME ["/data"]
EXPOSE 8010
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8010/sundhed').status==200 else 1)"
CMD ["python", "-m", "uvicorn", "golf.server:app", "--host", "0.0.0.0", "--port", "8010", "--proxy-headers", "--forwarded-allow-ips", "*"]

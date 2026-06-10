# erp-agent API（FastAPI + LangGraph supervisor）容器。
# 注意：前端是另一個 image（frontend/Dockerfile）；ppt-agent 是獨立服務（../agents/ppt-agent）。
# 這個 image 只跑後端 API，並可重用來跑 DB seed Job（同一份程式碼）。
FROM python:3.12-slim
WORKDIR /app

# curl 給容器內探針/除錯用；psycopg[binary] 不需 libpq-dev。
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 非 root；產出目錄會被 PVC 掛在 /app/generated（api 的 /files 由此服務）。
RUN useradd -u 1000 -m appuser \
    && mkdir -p /app/generated /app/uploads \
    && chown -R 1000:1000 /app/generated /app/uploads
USER 1000:1000

EXPOSE 8000
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]

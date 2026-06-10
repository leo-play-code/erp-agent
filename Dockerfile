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

# 非 root（uid 1000）。app 執行期會在 /app 下寫多個目錄：generated（產物，S3 模式不寫）、
# uploads（RAG 原始檔）、sql_imports（excel 匯入暫存）、rag_index（知識庫索引）、
# sql_library/schema_imports.json（匯入的 schema）。/app 只有程式碼+資料、無 venv（套件在
# /usr/local），整個 chown 給 1000 最穩、不會漏目錄；rootfs 未開唯讀，可寫。
RUN useradd -u 1000 -m appuser \
    && mkdir -p /app/generated /app/uploads /app/sql_imports /app/rag_index \
    && chown -R 1000:1000 /app
USER 1000:1000

EXPOSE 8000
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]

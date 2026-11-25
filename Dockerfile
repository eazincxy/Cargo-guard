FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl 用于容器健康检查
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-observability.txt ./
ARG INSTALL_OBSERVABILITY=false
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_OBSERVABILITY" = "true" ]; then \
        pip install --no-cache-dir -r requirements-observability.txt; \
    fi

COPY . .

# 构建期初始化订单库，保证镜像开箱可用（data.db 不入镜像）
RUN python -c "import app; from app.db import seed_demo_orders; seed_demo_orders()"

EXPOSE 8501 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8501}/_stcore/health" \
        || curl -fsS http://localhost:8000/health || exit 1

# 云平台（Render 等）通过 PORT 环境变量指定端口；本地默认 8501
CMD ["sh", "-c", "streamlit run streamlit_app.py --server.address=0.0.0.0 --server.port=${PORT:-8501} --server.headless=true --browser.gatherUsageStats=false"]

#!/bin/bash
# 先启 nginx，再启 Streamlit
set -e

# 从环境变量解析平台注入的数据库连接串
# Railway 会自动注入 DATABASE_URL（Postgres）
# 如果有就设为 Streamlit Cloud 兼容格式供 db.py 使用
echo "[start] env check: DATABASE_URL=${DATABASE_URL:-(not set)}"

# 启 nginx
nginx
echo "[start] nginx started on :80"

# 启 Streamlit（后台）
cd /app
streamlit run app.py \
  --server.port=8501 \
  --server.address=127.0.0.1 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false \
  --browser.gatherUsageStats false &
STREAMLIT_PID=$!
echo "[start] streamlit started pid=$STREAMLIT_PID"

# 等待子进程
wait $STREAMLIT_PID

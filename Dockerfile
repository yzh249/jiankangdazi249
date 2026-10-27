FROM python:3.11-slim

# 系统依赖：nginx
RUN apt-get update && apt-get install -y --no-install-recommends nginx ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /var/www/html

# 应用目录
WORKDIR /app

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 项目代码
COPY . .

# nginx 配置
COPY nginx.conf /etc/nginx/sites-available/default

# Streamlit 环境变量（从平台 Secrets 注入）
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=127.0.0.1

EXPOSE 80

# 启停脚本
COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]

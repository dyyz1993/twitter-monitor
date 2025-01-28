# 使用多架构基础镜像
FROM --platform=$TARGETPLATFORM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码和配置文件
COPY src/ /app/src/
COPY run.py .
COPY push_queue.py .
COPY .env .

# 创建数据卷目录
RUN mkdir -p /app/archives /app/logs /app/logs/push

# 声明数据卷
VOLUME ["/app/archives", "/app/logs"]

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai
ENV LOG_DIR=/app/logs
ENV ARCHIVE_DIR=/app/archives

# 运行程序
CMD ["python", "run.py"] 
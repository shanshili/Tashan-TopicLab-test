FROM python:3.11-slim

RUN useradd -m -u 1000 appuser

WORKDIR /app

# 配置 pip 使用阿里云镜像源，加速依赖下载并减少超时
RUN mkdir -p /home/appuser/.pip && \
    echo "[global]" > /home/appuser/.pip/pip.conf && \
    echo "index-url = https://mirrors.aliyun.com/pypi/simple/" >> /home/appuser/.pip/pip.conf && \
    echo "trusted-host = mirrors.aliyun.com" >> /home/appuser/.pip/pip.conf && \
    echo "timeout = 300" >> /home/appuser/.pip/pip.conf && \
    echo "retries = 10" >> /home/appuser/.pip/pip.conf

COPY pyproject.toml .
COPY app ./app
COPY main.py .
RUN pip install --no-cache-dir -e .

COPY . .
RUN chown -R appuser:appuser /app /home/appuser/.pip

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

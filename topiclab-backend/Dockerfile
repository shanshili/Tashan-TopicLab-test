FROM python:3.11-slim

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY pyproject.toml .
COPY app ./app
COPY main.py .
RUN pip install --no-cache-dir -e .

COPY . .
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

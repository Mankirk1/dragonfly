FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY taskbot ./taskbot
RUN useradd --create-home bot
USER bot
CMD ["python", "-m", "taskbot"]

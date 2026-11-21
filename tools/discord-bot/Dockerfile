FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock
COPY taskbot ./taskbot
RUN useradd --create-home bot
USER bot
CMD ["python", "-m", "taskbot"]

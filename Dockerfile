FROM python:3.11-alpine

RUN apk add --no-cache tzdata

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV TOKEN_DIR=/data/tokens
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]

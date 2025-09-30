FROM python:3.11-slim

# PyTorch 
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch==2.1.2 --index-url https://download.pytorch.org/whl/cpu

WORKDIR /app
COPY train_embeddings.py /app/
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["python", "/app/train_embeddings.py"]

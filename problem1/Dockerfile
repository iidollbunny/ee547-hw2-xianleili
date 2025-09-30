FROM python:3.11-slim

WORKDIR /app

# Copy app code and data
COPY arxiv_server.py /app/
COPY sample_data/ /app/sample_data/

# Expose default port
EXPOSE 8080

# Default command; run.py accepts a port argument
ENTRYPOINT ["python", "/app/arxiv_server.py"]
CMD ["8080"]

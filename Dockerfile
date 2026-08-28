# mcp-benchmark-hygiene — container image for hosted/Smithery deployment
FROM python:3.11-slim
WORKDIR /app
COPY mcp_server.py /app/mcp_server.py
RUN pip install --no-cache-dir "mcp>=1.0"
EXPOSE 8000
CMD ["python3", "/app/mcp_server.py"]

FROM python:3.9-slim
WORKDIR /app
RUN pip install --no-cache-dir aiohttp
COPY backend_server.py .
EXPOSE 8080
ENV SERVER_ID=Default
ENV PORT=8080
CMD ["python3", "backend_server.py"]
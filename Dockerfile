# One container serves the API and the built React site.

FROM node:22-slim AS client
WORKDIR /client
COPY client/package.json client/package-lock.json ./
RUN npm ci
COPY client/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=client /client/dist client/dist
# Fresh link preview image on every deploy (each daily forecast commit redeploys).
RUN python backend/og_image.py
RUN useradd --create-home app
USER app
EXPOSE 8000
# Hosting platforms set PORT; default to 8000 locally.
CMD uvicorn api:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}

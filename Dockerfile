# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /frontend

COPY frontend/package.json ./
RUN npm install --silent

COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python application ───────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy React build output alongside the existing static files.
# At Phase 5 cutover this COPY destination changes to /app/static/
# and static/index.html is removed. Until then both coexist.
COPY --from=frontend-build /frontend/dist /app/static-react

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

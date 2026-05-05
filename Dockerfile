FROM node:22-bookworm-slim AS web-build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY src/web ./src/web
COPY tsconfig.json ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY --from=web-build /app/dist ./dist
RUN mkdir -p /app/data
EXPOSE 3000
CMD ["python", "-m", "app.run"]

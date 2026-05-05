FROM node:22-bookworm-slim AS web-build
WORKDIR /app
ARG NPM_REGISTRY=https://registry.npmmirror.com
COPY package*.json ./
RUN npm ci --registry=${NPM_REGISTRY}
COPY src/web ./src/web
COPY tsconfig.json ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
COPY requirements.txt ./
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt
COPY app ./app
COPY config.example.json ./config.example.json
COPY --from=web-build /app/dist ./dist
RUN mkdir -p /app/data
EXPOSE 3000
CMD ["python", "-m", "app.run"]

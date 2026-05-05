# VPS 部署

推荐使用 Docker Compose。

## 1. 安装依赖

Ubuntu / Debian 示例：

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

## 2. 获取代码

```bash
git clone <your-repo-url> /opt/163claw
cd /opt/163claw
```

## 3. 配置

```bash
cp .env.example .env
nano .env
nano claw_accounts.json
```

确认 `.env` 里的：

```env
PORT=3000
ADMIN_PASSWORD=strong-password
CLAW_ACCOUNTS_JSON=./claw_accounts.json
DATABASE_PATH=./data/app.db
STATIC_DIR=./dist/web
```

`claw_accounts.json` 只放主账号，不要上传真实 Cookie、Token。

## 4. 启动

```bash
docker compose up -d --build
docker compose logs -f
```

访问：

```text
http://服务器IP:PORT
```

## 5. 更新

```bash
git pull
docker compose up -d --build
```

## 6. 非 Docker 方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm ci
npm run build
python -m app.run
```

可用 systemd 常驻：

```ini
[Unit]
Description=Claw Email Web Manager
After=network.target

[Service]
WorkingDirectory=/opt/163claw
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/163claw/.venv/bin/python -m app.run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

保存到 `/etc/systemd/system/163claw.service` 后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now 163claw
sudo journalctl -u 163claw -f
```

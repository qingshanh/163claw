# VPS 部署说明

推荐使用 Docker Compose，最省事，也不会污染系统 Python/Node 环境。

## 1. 准备服务器

Ubuntu/Debian 示例：

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

## 2. 上传项目

任选其一：

```bash
git clone <你的仓库地址> /opt/163claw
cd /opt/163claw
```

或用 `scp/rsync` 上传当前目录到 `/opt/163claw`。

## 3. 配置环境变量

```bash
cp .env.example .env
nano .env
```

至少确认这些项：

```env
PORT=3600
ADMIN_PASSWORD=换成强密码
CLAW_ACCOUNTS_JSON=./claw_accounts.json
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=你的机器人Token
TELEGRAM_CHAT_ID=你的ChatID
TELEGRAM_API_BASE=https://api.telegram.org
DATABASE_PATH=./data/app.db
STATIC_DIR=./dist/web
ENABLE_WS_LISTENERS=true
```

如需 Telegram 反代，`TELEGRAM_API_BASE` 填反代根地址，例如 `https://tg.example.com`。

## 4. 配置 Claw 主账号

编辑 `claw_accounts.json`，只放主账号，不需要手写子邮箱：

```json
{
  "accounts": [
    {
      "name": "account-1",
      "user": "xxx@claw.163.com",
      "registeredEmail": "xxx@163.com",
      "apiKey": "ck_live_xxx",
      "dashboardCookie": "CLAW_SESS=xxx",
      "workspaceId": "xxx",
      "parentMailboxId": "xxx",
      "rootPrefix": "xxx",
      "domain": "claw.163.com"
    }
  ]
}
```

## 5. 启动

```bash
docker compose up -d --build
docker compose logs -f
```

访问：

```text
http://服务器IP:PORT
```

如果使用云厂商安全组，需要放行 `PORT` 对应端口。

## 6. 更新

```bash
cd /opt/163claw
git pull
docker compose up -d --build
```

## 7. 非 Docker 部署

服务器需安装 Python 3.10+ 和 Node 20.19+：

```bash
cd /opt/163claw
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm ci
npm run build
python -m app.run
```

后台常驻可用 systemd：

```ini
[Unit]
Description=163claw mail panel
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

保存为 `/etc/systemd/system/163claw.service` 后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now 163claw
sudo journalctl -u 163claw -f
```

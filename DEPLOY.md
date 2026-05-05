# VPS 部署

推荐直接用 Docker。

## 1. 安装依赖

Ubuntu / Debian 示例：

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

## 2. 拉取代码

```bash
git clone <your-repo-url> /opt/163claw
cd /opt/163claw
```

## 3. 准备配置

```bash
cp config.example.json config.json
nano config.json
```

`config.json` 不会被打进镜像，Docker Compose 会在运行时把它挂载进去，面板保存配置也会写回这份文件。

重点检查：

- `app.adminPassword`
- `app.port`
- `accounts[*].apiKey`
- `accounts[*].dashboardCookie`
- `accounts[*].workspaceId`
- `accounts[*].parentMailboxId`
- `accounts[*].rootPrefix`
- `telegram.botToken`
- `telegram.chatId`

## 4. 启动

```bash
docker compose up -d --build
docker compose logs -f
```

访问：

```text
http://服务器IP:3000
```

## 5. 更新

```bash
git pull
docker compose up -d --build
```

## 6. 非 Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm ci
npm run build
python -m app.run
```

## 7. 注意

- `config.json`、`.env`、`data/` 不要提交到 GitHub
- 只保留 `config.example.json` 作为模板

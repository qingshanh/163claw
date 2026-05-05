# Claw Email Web Manager

Claw 邮箱管理面板，后端 Python，前端 React。

## 功能

- 多主账号管理
- 主账号下的子邮箱同步、创建、删除
- 收件箱实时监听
- 邮件发送、回复、附件下载
- Telegram 新邮件通知
- 统一 `config.json` 配置

## 配置文件

复制 `config.example.json` 为 `config.json`，再填写自己的值。

- `app`：运行参数、端口、数据库路径、静态目录
- `telegram`：全局 Telegram 推送配置
- `accounts`：主账号列表，每个主账号下可管理多个子邮箱

面板里的“统一配置文件”也会直接读写 `config.json`。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
npm install
npm run build
python -m app.run
```

默认访问：

```text
http://localhost:3000
```

## Docker

```powershell
copy config.example.json config.json
docker compose up -d --build
```

说明：

- `config.json` 挂载到容器内 `/app/config.json`，面板保存配置会写回这个文件
- 数据库存放在 `./data`
- 如果你修改了 `app.port`，也要同步调整 `docker-compose.yml` 的端口映射

## 说明

- `config.json` 和 `data/` 不要提交到 GitHub
- 账号里的 `apiKey`、`dashboardCookie`、`telegramBotToken` 都是敏感信息

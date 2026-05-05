# Claw Email Web Manager

Claw 邮箱管理面板，Python 后端 + React 前端。

## 功能

- 多主账号管理
- 子邮箱创建、同步、删除
- 收件箱实时监听
- 邮件收发、回复、附件下载
- Telegram 新邮件通知
- `.env` + `claw_accounts.json` 双配置模式

## 配置文件

- `.env.example`：环境变量模板
- `.env`：本地真实环境变量，不要提交
- `claw_accounts.json`：主账号配置，不要提交

## 本地运行

```powershell
copy .env.example .env
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
npm install
npm run build
npm start
```

默认访问：

```text
http://localhost:3000
```

## 常用环境变量

```env
PORT=3000
ADMIN_PASSWORD=change-me
CLAW_ACCOUNTS_JSON=./claw_accounts.json
DATABASE_PATH=./data/app.db
STATIC_DIR=./dist/web
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_API_BASE=https://api.telegram.org
ENABLE_WS_LISTENERS=true
```

## `claw_accounts.json` 说明

只保留主账号，不要把真实账号、Cookie、Token 上传到仓库。

```json
{
  "accounts": [
    {
      "name": "my-main-account",
      "user": "your_root@claw.163.com",
      "registeredEmail": "your_mail@example.com",
      "apiKey": "ck_live_xxx",
      "dashboardCookie": "CLAW_SESS=xxx",
      "workspaceId": "workspace_id",
      "parentMailboxId": "parent_mailbox_id",
      "rootPrefix": "your_root",
      "domain": "claw.163.com"
    }
  ]
}
```

## 构建

```powershell
npm run typecheck
npm run build
```

## 说明

- `apiKey`：邮件 API Key
- `dashboardCookie`：Dashboard 登录 Cookie
- `workspaceId`：工作区 ID
- `parentMailboxId`：主邮箱 ID
- `rootPrefix`：主邮箱前缀
- `TELEGRAM_API_BASE`：Telegram Bot API 地址，可填反代

## 注意

不要提交 `.env`、`claw_accounts.json`、`data/`。

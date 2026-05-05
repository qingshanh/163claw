# Claw Email Web Manager

> 当前版本已迁移为 Python 后端：FastAPI + SQLite + React/Vite 静态前端。旧的 TypeScript 后端源码仍保留在 `src/server` 作为参考，但运行与 Docker 部署入口已经改为 `app/main.py`。

## Python 版新增能力

- 多账户管理：`/api/accounts` 可添加多个独立 Claw 主账号配置，每个账号维护自己的 API Key、Dashboard Cookie、workspace、主邮箱和通知设置。邮箱表通过 `account_id` 区分归属，支持同时监听多个账号下的多个邮箱。
- Telegram 通知：每个账号可以开启 Telegram 通知并配置 `telegram_bot_token`、`telegram_chat_id`、`telegram_api_base`。`telegram_api_base` 可填反代地址，例如 `https://tg-proxy.example.com`，收到新邮件后会自动通过机器人推送摘要。
- 简化部署：Docker 镜像运行时只需要 Python，前端在构建阶段用 Node 打包成静态文件，容器启动命令为 `uvicorn app.main:app --host 0.0.0.0 --port 3000`。
- 更稳的运行策略：监听器有退避重连、启动时自动恢复 active 邮箱监听、邮件本地持久化、附件按需流式下载、管理 API 继续用 `X-Admin-Password` 或 `?token=` 鉴权。

## 快速部署

```powershell
copy .env.example .env
# 修改 .env 中的 ADMIN_PASSWORD；可选填写 TELEGRAM_* 默认通知配置
docker compose up -d --build
curl http://localhost:3000/health
```

本地开发：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
npm install
npm run build
npm start
# http://localhost:3000
```

前端仍可单独开发：`npm run dev:web`。Python 后端开发可用 `npm run dev`，等价于 `uvicorn app.main:app --reload`。

## 多账户 API

```http
GET  /api/accounts
POST /api/accounts
PATCH /api/accounts/:id
DELETE /api/accounts/:id
```

创建账号示例：

```json
{
  "name": "account-a",
  "api_key": "ck_live_xxx",
  "dashboard_cookie": "CLAW_SESS=xxx",
  "workspace_id": "XnVvZknr",
  "parent_mailbox_id": "3L85M1qk",
  "root_prefix": "vercel",
  "domain": "claw.163.com",
  "telegram_enabled": true,
  "telegram_bot_token": "123456:ABC",
  "telegram_chat_id": "123456789",
  "telegram_api_base": "https://api.telegram.org"
}
```

同步指定账号邮箱：

```http
GET /api/mailboxes?sync=true&account_id=1
```

创建邮箱时可指定账号：

```json
{ "suffix": "demo1", "account_id": 1 }
```

如果不传 `account_id`，会使用第一个 active 账号，兼容原单账户前端。

## Claw 配置字段怎么拿

Claw 能力分两层，先分清楚会少绕很多路：

- 只收信、发信、回复、监听已有邮箱：需要 `apiKey` 和要管理的邮箱地址列表即可，也就是当前 `claw_accounts.json` 这种配置。
- 要真正创建/删除 Claw 子邮箱：还必须有 `dashboardCookie`、`workspaceId`、`parentMailboxId`、`rootPrefix`、`domain`。这些来自 Claw 网页控制台的内部接口，不是公开稳定 API。

字段说明：

- `apiKey`：Claw 邮件 API Key，通常以 `ck_live_` 开头。用于收信、发信、回复、附件、WebSocket 监听。获取方式：Claw Dashboard 的 API Keys 页面复制，或在本应用侧边栏用邮箱验证码绑定，后端会自动取默认 API Key。
- `dashboardCookie`：登录 `https://claw.163.com` 后浏览器请求头里的 Cookie。只用于创建、删除、同步邮箱树。获取方式：打开浏览器开发者工具 Network，刷新 Claw Dashboard，点任意 `mailserv-claw-dashboard/api/v1/...` 请求，复制 Request Headers 里的 `Cookie` 整行值。
- `workspaceId`：Claw 工作区 ID。获取方式：同样在 Network 找 `GET /mailserv-claw-dashboard/api/v1/workspaces`，响应里 `result.workspaces[].id`，一般取 `status=active` 的那个。
- `parentMailboxId`：主邮箱，也就是根邮箱的 ID。获取方式：请求 `GET /mailserv-claw-dashboard/api/v1/mailboxes?workspaceId=<workspaceId>`，响应里通常是 `result.mailbox.id`。
- `rootPrefix`：主邮箱 `@` 前面的部分，例如 `lanceagent@claw.163.com` 的 `rootPrefix` 是 `lanceagent`。创建子邮箱时会生成 `lanceagent.<suffix>@claw.163.com`。
- `domain`：邮箱域名，通常是 `claw.163.com`。

创建子邮箱所需最小配置：

```json
{
  "name": "huihlance",
  "user": "lanceagent@claw.163.com",
  "apiKey": "ck_live_xxx",
  "dashboardCookie": "CLAW_SESS=xxx; ...",
  "workspaceId": "XnVvZknr",
  "parentMailboxId": "3L85M1qk",
  "rootPrefix": "lanceagent",
  "domain": "claw.163.com"
}
```

现在如果已经配置 `dashboardCookie`、`workspaceId`、`parentMailboxId`，程序会从 Claw Dashboard 的邮箱树接口自动同步主邮箱和子邮箱，不需要在 JSON 里再写 `users`、`includeSubs`、`subPattern`。`users` 仅作为没有 Dashboard Cookie 时的手工兜底列表。

当前代码为了不让面板直接炸掉，在没有 `dashboardCookie` 时允许添加“本地管理邮箱”：它会进入监听/收发管理，但不会真的去 Claw Dashboard 创建远端子邮箱。要让远端也创建成功，请补齐上面这些 Dashboard 字段。

## Telegram 配置

`.env` 可提供全局默认值：

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=123456:ABC
TELEGRAM_CHAT_ID=123456789
TELEGRAM_API_BASE=https://api.telegram.org
```

账号级配置优先于 `.env`。如果使用反代，只要反代保持 Telegram Bot API 路径格式即可：后端会请求 `{TELEGRAM_API_BASE}/bot{TOKEN}/sendMessage`。

---

以下为原项目说明，保留供功能对照。

基于 `claw.163.com` 的 **子邮箱批量管理 / 实时收发** 一体化前后端。
通过 Web UI 验证码登录 Claw，自动派生 Dashboard Cookie 与 API Key，为每个子邮箱维持长连接监听，新邮件实时入库并经 SSE 推送给前端，可在线发件、回复、删除（远端 + 本地双删）、下载附件。

仓库结构：

```text
src/
  server/                Fastify 5 后端（SQLite + Claw SDK + Dashboard 内部接口）
    config.ts            环境变量解析（zod）
    db.ts                better-sqlite3 schema 与 DAO
    runtime-config.ts    运行时凭据（优先读 SQLite，再回退 .env）
    claw-dashboard.ts    Claw Dashboard 内部 HTTP 接口封装
    claw-mail.ts         @clawemail/node-sdk 客户端池 + 发件/回信/删信/列表
    listener-manager.ts  每邮箱 WS 长连接 + 指数退避重连
    sse.ts               SSE 广播总线
    routes/              auth / mailboxes / mails / send / events
    index.ts             Fastify 启动 + 静态托管前端
  web/                   Vite 7 + React 19 单页应用
    src/App.tsx          主壳：登录/路由/连接卡/工具栏
    src/api.ts           前端调用层（统一 X-Admin-Password / ?token=）
    src/i18n.tsx         中英双语 + 暗亮主题
    src/components/      InboxView / MailboxesView / ComposeDrawer / ListenersDrawer / ListenersView
    src/hooks.ts         可拖拽栏宽（localStorage 持久化）
```

## 1. 功能矩阵

| 模块 | 能力 | 实现位置 |
|---|---|---|
| Claw 绑定 | 邮箱 + 验证码两步登录；自动取 `auth/me` / `workspaces` / `mailboxes` / `api-keys`；写入 SQLite | `routes/claw-auth.ts`、`runtime-config.ts` |
| 邮箱管理 | 创建（前缀 `^[a-z0-9]{1,32}$`）、列表、`?sync=true` 与远端做差量同步、删除（拒绝删主邮箱） | `routes/mailboxes.ts`、`claw-dashboard.ts` |
| 通讯规则 | 同步并保存 `commLevel` / `extReceiveType` / `extSendType`；邮箱页可配置个人 / 内部 / 外部通信范围 | `routes/mailboxes.ts`、`CommunicationRulesDrawer.tsx` |
| 实时收件 | 每个 `active` 邮箱一条 WS 监听；落库为 `mails` + `attachments`；SSE `event: mail` 推送 | `listener-manager.ts`、`sse.ts` |
| 收件同步 | `GET /api/mails?sync=true`：远端 INBOX `id` 列表 → 删本地多余、补本地缺失 | `routes/mails.ts` |
| 邮件详情 | 返回行 + 解析后的原始 JSON + 附件元数据 | `routes/mails.ts` |
| 删信 | SDK `moveMessages([id], "Trash")` 远端删除 + 本地行删除 | `claw-mail.ts`、`routes/mails.ts` |
| 发件 | 仅允许 `from` 是本地已管理邮箱 | `routes/send.ts` |
| 回信 | 基于本地 `mailId` 反查 `provider_mail_id` 调 SDK | `routes/send.ts` |
| 附件下载 | 不缓存原始字节，按需经 SDK 流式拉取 | `routes/mails.ts` |
| 监听器诊断 | `/api/listeners` 输出 `email/connected/retry`；前端有侧栏摘要 + 抽屉详情 | `routes/events.ts`、`ListenersDrawer.tsx` |
| 前端体验 | 中英双语、暗亮主题、拖拽栏宽（侧边栏 / 邮件列表）、登录态 localStorage 记忆 | `i18n.tsx`、`hooks.ts` |

## 2. Claw 验证码登录链

不收集任何 Claw 密码。`POST /api/auth/claw/verify-code` 内部串联以下接口：

```http
POST https://claw.163.com/mailserv-claw-dashboard/p/v1/auth/email/send-code
POST https://claw.163.com/mailserv-claw-dashboard/p/v1/auth/email/verify-code   → Set-Cookie: CLAW_SESS
GET  https://claw.163.com/mailserv-claw-dashboard/api/v1/auth/me
GET  https://claw.163.com/mailserv-claw-dashboard/api/v1/workspaces
GET  https://claw.163.com/mailserv-claw-dashboard/api/v1/mailboxes?workspaceId=<id>
GET  https://claw.163.com/mailserv-claw-dashboard/api/v1/api-keys
```

落库（SQLite `app_settings` 表）：

```text
claw.apiKey
claw.dashboardCookie
claw.userEmail
claw.workspaceId / claw.workspaceName
claw.parentMailboxId
claw.rootPrefix
claw.domain
```

`workspace` 取 `status=active`，`apiKey` 取 `defaultFlag=1` 优先。
绑定成功后会先 `stopAllMailboxListeners()` + `resetMailClients()` 再用新凭据 `startAllMailboxListeners()`，避免旧连接残留。

## 3. Dashboard 内部接口（仅后端调用）

| 用途 | 方法 / 路径 |
|---|---|
| 列出工作区下的邮箱树 | `GET /api/v1/mailboxes?workspaceId=<id>` |
| 创建子邮箱 | `POST /api/v1/mailboxes`（`{prefix, displayName, mailboxType:"sub", workspaceId, parentMailboxId}`） |
| 配置通讯规则 | `POST /api/v1/mailboxes/comm-settings?id=<mailboxId>`（`{commLevel, extReceiveType?, extSendType?}`） |
| 删除邮箱 | `POST /api/v1/mailboxes/delete?id=<mailboxId>` |

返回壳为 `{code, message, success, result}`，由 `parseDashboardResponse` 统一解包。

## 4. 本项目 HTTP API

### 4.1 鉴权

所有 `/api/*` 必须带：

```http
X-Admin-Password: <ADMIN_PASSWORD>
```

浏览器无法自定义头的场景（SSE、附件 `<a href>`）改用：

```http
?token=<ADMIN_PASSWORD>
```

`X-Admin-Password` 与 `query.token` 命中其一即放行（见 `src/server/index.ts: extractAdminPassword`）。

### 4.2 端点清单

```http
GET    /health
GET    /api/auth/claw/status
POST   /api/auth/claw/send-code
POST   /api/auth/claw/verify-code
POST   /api/auth/claw/refresh
POST   /api/auth/claw/logout

GET    /api/mailboxes                # 仅本地
GET    /api/mailboxes?sync=true      # 与 Claw 做差量同步后再返回
POST   /api/mailboxes                # { suffix }
POST   /api/mailboxes/:id/comm-settings      # { commLevel, extReceiveType?, extSendType? }
DELETE /api/mailboxes/:id

GET    /api/mails?mailbox=&limit=50&offset=0
GET    /api/mails?sync=true&mailbox=...      # 远端 INBOX 全量比对
GET    /api/mails/:id                        # 详情 + 解析后 JSON + 附件元数据
DELETE /api/mails/:id                        # 远端移到 Trash + 本地删除
GET    /api/mails/:id/attachments/:partId    # 流式下载附件

POST   /api/send                              # { from, to[], cc?, bcc?, subject?, body?, html? }
POST   /api/reply                             # { mailId, body?, html?, toAll? }

GET    /api/events                            # SSE: event: mail
GET    /api/listeners
```

请求样例：

```jsonc
// POST /api/mailboxes
{ "suffix": "4" }

// POST /api/send
{
  "from": "vercel.4@claw.163.com",
  "to": ["target@example.com"],
  "cc": ["copy@example.com"],
  "subject": "hello",
  "body": "message body",
  "html": false
}

// POST /api/reply
{ "mailId": 123, "body": "reply body", "toAll": false, "html": false }
```

SSE 事件：

```text
event: mail
data: {"mailboxEmail":"vercel.4@claw.163.com","id":42,"providerMailId":"..."}
```

校验：所有入参经 zod 解析；失败返回 `400 {error:"invalid input", details:[...]}`。

## 5. 数据持久化

SQLite 文件由 `DATABASE_PATH` 指定（默认 `./data/app.db`），开启 `journal_mode=WAL` + `foreign_keys=ON`。

```text
mailboxes      子邮箱：id / email(unique) / prefix / status / install_command / auth_url / comm_level ...
mails          邮件：mailbox_email + provider_mail_id 联合唯一，含 raw_json 全文
attachments    附件元数据：mail_id 外键 → mails.id（ON DELETE CASCADE）
app_settings   key/value，存 Claw 凭据
```

附件二进制**不入库**，下载时调 `client.mail.getAttachment` 流式回传给浏览器。

## 6. 监听器与重连

`src/server/listener-manager.ts`：

- 启动条件：邮箱 `status === "active"` 且 `hasClawMailConfig()` 为真
- 退避序列：`[1, 2, 4, 8, 16, 30]` 秒
- `client.ws.onMessage` 收到 mailId → `client.mail.read({markRead:true})` → `saveMail` → SSE `mail` 广播
- `client.ws.onDisconnect` 触发 `scheduleReconnect`
- 删邮箱、断开 Claw 时会显式 `stopMailboxListener` 关闭 WS

`/api/listeners` 当前返回字段：`{ email, connected, retry }`。前端 `ListenersDrawer` 同时兼容了未来可能扩展的 `status / startedAt / lastEventAt / error` 字段。

## 7. 环境变量

```env
NODE_ENV=production
PORT=3000
ADMIN_PASSWORD=change-me

# 以下变量是"兜底值"，验证码登录成功后会被 SQLite 中的值覆盖
CLAW_API_KEY=
CLAW_DASHBOARD_COOKIE=
CLAW_WORKSPACE_ID=
CLAW_PARENT_MAILBOX_ID=
CLAW_ROOT_PREFIX=
CLAW_DOMAIN=claw.163.com

DATABASE_PATH=./data/app.db
```

读取顺序（`runtime-config.ts`）：`SQLite app_settings` → `process.env`，缺一则 API 报 `... is required; connect Claw first`。

## 8. 本地运行

应用监听端口由 `PORT` 环境变量控制，默认 **3000**（host `0.0.0.0`）。

```powershell
npm install
npm run build
npm start
# 默认 http://localhost:3000
# 改端口： $env:PORT=8080; npm start
```

开发：

```powershell
npm run dev          # tsx 跑后端，监听 :3000（受 PORT 控制）
npm run dev:web      # Vite 跑前端，监听 :5173
npm run typecheck    # tsc --noEmit
```

`npm run build` = `vite build` 产出静态资源到 `dist/web` + `esbuild` 打包后端到 `dist/server/index.js`，`@clawemail/node-sdk`、`fastify`、`better-sqlite3` 等保持 external。

## 9. Docker 部署

容器内进程恒定监听 `3000`，宿主端口由 `ports` 左侧决定（默认 `3000:3000`）。

### docker compose

```powershell
git clone https://github.com/WangXingFan/ClawEmail.git
cd ClawEmail
cp .env.example .env
docker compose up -d
curl http://localhost:3000/health
```

### docker run

```bash
docker run -d --name clawemail \
  -p 3000:3000 \
  -e ADMIN_PASSWORD=change-me \
  -v $PWD/data:/app/data \
  ghcr.io/wangxingfan/clawemail:latest
```

`./data` 挂到 `/app/data` 持久化 SQLite。



## 致谢

感谢 [Linux.do](https://linux.do) 社区。

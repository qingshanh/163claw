# 163 Claw 邮箱管理面板

Python + React 实现的 Claw 邮箱管理面板。

## 功能

- 多主账号管理
- 每个主账号下同步、创建、删除子邮箱
- 收件箱同步、邮件查看、发送、回复、附件下载
- 新邮件 Telegram 推送
- 单文件配置：`config.json`
- 国内 Docker 构建源优化
- 支持 Claw / Telegram API 反代地址

## 快速开始

```bash
cp config.example.json config.json
docker compose up -d --build
```

访问：

```text
http://服务器IP:3600
```

如果你修改了 `config.json` 里的 `app.port`，也要同步修改 `docker-compose.yml` 的端口映射。

## 配置

配置文件只使用 `config.json`：

- `app`：端口、面板密码、数据库路径、静态文件目录
- `claw.origin`：Claw 官方地址或反代地址，默认 `https://claw.163.com`
- `telegram`：Telegram 推送和 Bot API 地址
- `accounts`：主账号列表

`config.json` 是本地敏感文件，不要提交到 GitHub。仓库里只保留 `config.example.json`。

## 国内部署

Dockerfile 默认使用：

- npm: `https://registry.npmmirror.com`
- pip: `https://pypi.tuna.tsinghua.edu.cn/simple`

如果要改回官方源：

```bash
NPM_REGISTRY=https://registry.npmjs.org \
PIP_INDEX_URL=https://pypi.org/simple \
docker compose up -d --build
```

更完整的部署、反代和诊断说明见 `DEPLOY.md`。

## 诊断

```bash
ADMIN='你的面板密码'

curl -s -H "x-admin-password: $ADMIN" \
  "http://127.0.0.1:3600/api/diagnostics/claw" | python3 -m json.tool
```

如果 `remoteChildren` 为 0，说明当前 VPS 到 Claw 控制台接口没有拿到子邮箱，建议换国内节点或配置 `claw.origin` 反代。

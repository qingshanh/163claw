# VPS 部署

推荐使用 Docker 部署。项目只需要一个运行配置文件：`config.json`。

## 1. 安装依赖

Ubuntu / Debian:

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

如果拉取 Docker 镜像慢，先给 Docker 配置国内 registry mirror，或者在有外网的机器构建后推送到自己的镜像仓库。

## 2. 拉取代码

```bash
git clone <your-repo-url> ~/163claw
cd ~/163claw
```

## 3. 准备配置

```bash
cp config.example.json config.json
nano config.json
```

重点配置：

- `app.port`：容器内服务端口，需要和 `docker-compose.yml` 的端口映射一致
- `app.adminPassword`：面板密码
- `claw.origin`：Claw 官方地址或你的反代地址，默认 `https://claw.163.com`
- `telegram.apiBase`：Telegram Bot API 官方地址或反代地址
- `accounts[*].apiKey`
- `accounts[*].dashboardCookie`
- `accounts[*].workspaceId`
- `accounts[*].rootPrefix`
- `accounts[*].domain`

`parentMailboxId` 可以留模板值或旧值，程序同步时会用 Claw 返回的主邮箱自动修正。

## 4. 国内构建优化

Dockerfile 默认使用国内源：

- npm: `https://registry.npmmirror.com`
- pip: `https://pypi.tuna.tsinghua.edu.cn/simple`

直接构建：

```bash
docker compose up -d --build
```

如果你在海外 VPS 或希望使用官方源：

```bash
NPM_REGISTRY=https://registry.npmjs.org \
PIP_INDEX_URL=https://pypi.org/simple \
docker compose up -d --build
```

## 5. Claw 反代

如果国外 VPS 访问 Claw 邮箱树不稳定，可以在国内机器或国内 CDN 上反代 `https://claw.163.com`，然后把 `config.json` 改成：

```json
{
  "claw": {
    "origin": "https://你的反代域名"
  }
}
```

反代需要覆盖这些路径：

- `/mailserv-claw-dashboard/`
- `/claw-api-gateway/`

修改 `claw.origin` 后需要重启容器：

```bash
docker compose down
docker compose up -d --build
```

## 6. 访问

如果端口是 `3600`：

```text
http://服务器IP:3600
```

确认本机服务：

```bash
curl -I http://127.0.0.1:3600
```

外网打不开时，检查云安全组和系统防火墙是否放行该端口。

## 7. 诊断

```bash
ADMIN='你的面板密码'

curl -s -H "x-admin-password: $ADMIN" \
  "http://127.0.0.1:3600/api/diagnostics/claw" | python3 -m json.tool

curl -s -H "x-admin-password: $ADMIN" \
  "http://127.0.0.1:3600/api/mailboxes?sync=true" | python3 -m json.tool
```

看 `remoteChildren` 和 `localChildren`：

- `remoteChildren = 0`：VPS 到 Claw 控制台拿不到子邮箱，优先换国内 VPS 或配置 `claw.origin` 反代
- `remoteChildren > 0` 但 `localChildren = 0`：本地数据库写入或清理异常
- `localChildren > 0` 但网页没有：浏览器缓存或前端展示异常

## 8. 注意

- 不要提交 `config.json`、`.env`、`data/`
- GitHub 只提交 `config.example.json`
- 面板修改配置会写回 `config.json`

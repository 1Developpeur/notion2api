# Notion2API 部署指南

## 快速部署（Docker）

### 1. 克隆项目

```bash
git clone git@github.com:maverickxone/notion2api.git
cd notion2api
```

### 2. 配置账号

```bash
# 创建 accounts.json（参考 accounts.README.md）
# 获取账号信息：浏览器登录 notion.so/ai → F12 → Console → 粘贴 scripts/extract_notion_info.js
nano accounts.json
```

格式：
```json
[
  {"token_v2": "你的token", "space_id": "...", "user_id": "...", "space_view_id": "...", "user_name": "...", "user_email": "..."}
]
```

### 3. 配置环境变量

```bash
cp .env.example .env
nano .env
# 必改：APP_MODE（推荐 standard）
# 可选：API_KEY、HOST_PORT
```

### 4. 启动

```bash
docker-compose build --no-cache && docker-compose up -d
```

### 5. 验证

```bash
curl http://localhost:8000/health
# 预期：{"status":"ok","accounts":1,...}
```

访问 `http://你的服务器IP:8000` 即可使用 Web UI。

---

## 日常管理

```bash
# 查看日志
docker-compose logs --tail=50

# 重启
docker-compose restart

# 更新代码后重新部署
git pull && docker-compose down && docker-compose build --no-cache && docker-compose up -d

# 修改账号后（不需要重新 build）
nano accounts.json
docker-compose restart
```

---

## 账号管理

`accounts.json` 通过 volume 挂载到容器内，修改后只需 `docker-compose restart`，不需要重新 build。

添加新账号步骤见 `accounts.README.md`。

---

## Nginx 反向代理（可选）

如果需要 HTTPS 和域名访问：

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

---

## 故障排查

```bash
# 查看日志
docker-compose logs --tail=50

# 检查容器状态
docker-compose ps

# 检查账号是否加载
docker-compose logs | grep "startup"
# 应显示 "accounts": N（N = 你的账号数）

# 进入容器调试
docker-compose exec notion-ai bash
```

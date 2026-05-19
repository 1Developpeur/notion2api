# accounts.json 使用说明

## 推荐方式：使用登录脚本

运行：

```bash
python login.py
```

脚本会打开一个临时 Chrome/Edge 调试窗口，让你登录 Notion，然后从本地浏览器会话中临时读取 Notion cookies。它会使用这些 cookies 捕获 `token_v2`、识别当前活跃的 `notion_user_id`，并自动提取 `space_id`、`user_id`、`space_view_id`、`user_name`、`user_email`。

注意：
- 完整的浏览器 cookie jar 不会写入仓库，也不应该提交。
- `accounts.json` 和 `.env` 包含凭据，已经被 `.gitignore` 忽略。
- 如果 token 失效，重新运行 `python login.py` 刷新即可。

## 手动方式：添加新账号（3 步）

### 第 1 步：获取 token_v2
1. 浏览器登录 https://www.notion.so/ai
2. 按 `F12` → 切到 `Application` 标签
3. 左侧 `Storage → Cookies → https://www.notion.so`
4. 找到 `token_v2`，复制它的 Value

### 第 2 步：获取其余 5 个字段
1. 按 `F12` → 切到 `Console` 标签
2. 粘贴 `scripts/extract_notion_info.js` 的内容，回车
3. 脚本会输出一段 JSON 并自动复制到剪贴板

### 第 3 步：粘贴到 accounts.json
把脚本输出的 JSON 对象粘贴到 `accounts.json` 数组中，替换 `YOUR_TOKEN_V2` 为第 1 步复制的值。

## 多账号格式

```json
[
  { "token_v2": "账号1的token", "space_id": "...", "user_id": "...", "space_view_id": "...", "user_name": "...", "user_email": "..." },
  { "token_v2": "账号2的token", "space_id": "...", "user_id": "...", "space_view_id": "...", "user_name": "...", "user_email": "..." },
  { "token_v2": "账号3的token", "space_id": "...", "user_id": "...", "space_view_id": "...", "user_name": "...", "user_email": "..." }
]
```

## 注意事项
- 第一个账号是主账号，优先使用
- 账号失败时自动轮询到下一个（冷却 3 秒）
- 风控/过期的账号可以留在数组末尾，不影响其他账号
- 修改后需要重启服务才能生效

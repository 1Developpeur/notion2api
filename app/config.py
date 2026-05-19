import json
import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量（override=True 确保 .env 优先于系统环境变量）
load_dotenv(override=True)

REQUIRED_ACCOUNT_FIELDS = {"token_v2", "space_id", "user_id"}

DEFAULT_ALLOWED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_allowed_origins(value: str | None, *, allow_unsafe_wildcard: bool = False) -> list[str]:
    """Parse and harden CORS origins.

    The service holds Notion session material locally, so wildcard CORS is not a
    safe default. A wildcard can still be explicitly enabled for isolated tests by
    setting ALLOW_UNSAFE_CORS=true.
    """
    raw = value if value is not None else ""
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if not origins or "*" in origins:
        return ["*"] if allow_unsafe_wildcard else list(DEFAULT_ALLOWED_ORIGINS)
    return origins


def load_accounts():
    """
    从 accounts.json 文件或环境变量 NOTION_ACCOUNTS 加载账号配置。
    优先级：accounts.json > NOTION_ACCOUNTS 环境变量
    """
    # 优先从 accounts.json 文件读取
    accounts_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "accounts.json")
    accounts_json = None

    if os.path.exists(accounts_file):
        with open(accounts_file, "r", encoding="utf-8") as f:
            accounts_json = f.read().strip()
    
    # 回退到环境变量
    if not accounts_json:
        accounts_json = os.getenv("NOTION_ACCOUNTS")

    if not accounts_json:
        raise ValueError("未找到账号配置：请创建 accounts.json 文件或设置 NOTION_ACCOUNTS 环境变量。")
    
    try:
        accounts = json.loads(accounts_json)
        if not isinstance(accounts, list) or len(accounts) == 0:
            raise ValueError("账号配置格式不正确，应提供非空的 JSON 数组。")
        for idx, account in enumerate(accounts):
            if not isinstance(account, dict):
                raise ValueError(f"账号配置[{idx}] 必须是对象。")
            missing = sorted(field for field in REQUIRED_ACCOUNT_FIELDS if not account.get(field))
            if missing:
                raise ValueError(f"账号配置[{idx}] 缺少必要字段: {', '.join(missing)}")
        return accounts
    except json.JSONDecodeError as e:
        raise ValueError(f"解析账号配置失败: {e}")

# 全局配置对象
ACCOUNTS = load_accounts()

# FastAPI 服务配置
API_KEY = os.getenv("API_KEY", "")
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
ALLOW_UNSAFE_CORS = _env_flag("ALLOW_UNSAFE_CORS", default=False)
ALLOWED_ORIGINS = parse_allowed_origins(os.getenv("ALLOWED_ORIGINS"), allow_unsafe_wildcard=ALLOW_UNSAFE_CORS)

# APP_MODE: heavy（默认）、lite 或 standard
APP_MODE = os.getenv("APP_MODE", "heavy").lower().strip()

def is_lite_mode() -> bool:
    return APP_MODE == "lite"

def is_standard_mode() -> bool:
    """Standard 模式：发送完整上下文，支持 thinking 和搜索输出"""
    return APP_MODE == "standard"

def get_default_account():
    """获取默认账号（列表中的第一个账号）"""
    return ACCOUNTS[0]

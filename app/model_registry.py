from app.core.models import normalize_model_id


MODEL_MAP: dict[str, str] = {
    # Anthropic
    "claude-sonnet4.6": "almond-croissant-low",
    "claude-sonnet5": "angel-cake-high",
    "claude-opus4.6": "avocado-froyo-medium",
    "claude-opus4.7": "apricot-sorbet-high",
    "claude-opus4.8": "ambrosia-tart-high",
    "claude-haiku4.5": "anthropic-haiku-4.5",
    "claude-fable5": "acai-budino",
    
    # OpenAI
    "gpt-5.2": "oatmeal-cookie",
    "gpt-5.4": "oval-kumquat-medium",
    "gpt-5.5": "opal-quince-medium",
    "gpt-5.4mini": "oregon-grape-medium",
    "gpt-5.4nano": "otaheite-apple-medium",
    
    # Google
    "gemini-3-flash": "gingerbread",
    "gemini-3flash": "gingerbread",
    "gemini-3.1-pro": "galette-medium-thinking",
    "gemini-3.1pro": "galette-medium-thinking",
    "gemini-3.5flash": "vertex-gemini-3.5-flash",
    "gemini-2.5flash": "vertex-gemini-2.5-flash",
    
    # xAI
    "grok-4.3": "xigua-mochi-medium",
    "grok-build0.1": "xinomavro-cake",
    
    # Other
    "minimax-m2.5": "fireworks-minimax-m2.5",
    "kimi-2.6": "fireworks-kimi-k2.6",
    "deepseek-v4pro": "baseten-deepseek-v4-pro",
    "glm-5.2": "baseten-glm-5.2",
    
    # Additional compatibility aliases requested
    "claude-haiku-4.5": "anthropic-haiku-4.5",
    "gpt-5.4-mini": "oregon-grape-medium",
    "gpt-5.4-nano": "otaheite-apple-medium",
    "deepseek-v4-pro": "baseten-deepseek-v4-pro",
    "grok-build-0.1": "xinomavro-cake",

    # Backend Model IDs mapping to themselves
    "oatmeal-cookie": "oatmeal-cookie",
    "oval-kumquat-medium": "oval-kumquat-medium",
    "opal-quince-medium": "opal-quince-medium",
    "vertex-gemini-2.5-flash": "vertex-gemini-2.5-flash",
    "vertex-gemini-3.5-flash": "vertex-gemini-3.5-flash",
    "almond-croissant-low": "almond-croissant-low",
    "angel-cake-high": "angel-cake-high",
    "avocado-froyo-medium": "avocado-froyo-medium",
    "apricot-sorbet-high": "apricot-sorbet-high",
    "ambrosia-tart-high": "ambrosia-tart-high",
    "oregon-grape-medium": "oregon-grape-medium",
    "otaheite-apple-medium": "otaheite-apple-medium",
    "fireworks-minimax-m2.5": "fireworks-minimax-m2.5",
    "fireworks-kimi-k2.6": "fireworks-kimi-k2.6",
    "baseten-deepseek-v4-pro": "baseten-deepseek-v4-pro",
    "baseten-glm-5.2": "baseten-glm-5.2",
    "xigua-mochi-medium": "xigua-mochi-medium",
    "xinomavro-cake": "xinomavro-cake",
    "galette-medium-thinking": "galette-medium-thinking",
    "anthropic-haiku-4.5": "anthropic-haiku-4.5",
    "gingerbread": "gingerbread",
    "acai-budino": "acai-budino",
}

NOTION_MODEL_REVERSE_MAP: dict[str, str] = {
    # Anthropic
    "almond-croissant-low": "claude-sonnet4.6",
    "angel-cake-high": "claude-sonnet5",
    "avocado-froyo-medium": "claude-opus4.6",
    "apricot-sorbet-high": "claude-opus4.7",
    "ambrosia-tart-high": "claude-opus4.8",
    "anthropic-haiku-4.5": "claude-haiku4.5",
    "acai-budino": "claude-fable5",
    
    # OpenAI
    "oatmeal-cookie": "gpt-5.2",
    "oval-kumquat-medium": "gpt-5.4",
    "opal-quince-medium": "gpt-5.5",
    "oregon-grape-medium": "gpt-5.4mini",
    "otaheite-apple-medium": "gpt-5.4nano",
    
    # Google
    "gingerbread": "gemini-3flash",
    "galette-medium-thinking": "gemini-3.1pro",
    "vertex-gemini-3.5-flash": "gemini-3.5flash",
    "vertex-gemini-2.5-flash": "gemini-2.5flash",
    
    # xAI
    "xigua-mochi-medium": "grok-4.3",
    "xinomavro-cake": "grok-build0.1",
    
    # Other
    "fireworks-minimax-m2.5": "minimax-m2.5",
    "fireworks-kimi-k2.6": "kimi-2.6",
    "baseten-deepseek-v4-pro": "deepseek-v4pro",
    "baseten-glm-5.2": "glm-5.2",
}

DISPLAY_NAMES: dict[str, str] = {
    # Aliases
    "claude-sonnet4.6": "Claude Sonnet 4.6",
    "claude-sonnet5": "Claude Sonnet 5",
    "claude-opus4.6": "Claude Opus 4.6",
    "claude-opus4.7": "Claude Opus 4.7",
    "claude-opus4.8": "Claude Opus 4.8",
    "claude-haiku4.5": "Claude Haiku 4.5",
    "claude-fable5": "Fable 5",
    "gpt-5.2": "GPT-5.2",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.4mini": "GPT-5.4 Mini",
    "gpt-5.4nano": "GPT-5.4 Nano",
    "gpt-5.5": "GPT-5.5",
    "gemini-3flash": "Gemini 3 Flash",
    "gemini-3-flash": "Gemini 3 Flash",
    "gemini-3.1pro": "Gemini 3.1 Pro",
    "gemini-3.1-pro": "Gemini 3.1 Pro",
    "gemini-3.5flash": "Gemini 3.5 Flash",
    "gemini-2.5flash": "Gemini 2.5 Flash",
    "grok-4.3": "Grok 4.3",
    "grok-build0.1": "Grok Build 0.1",
    "minimax-m2.5": "MiniMax M2.5",
    "kimi-2.6": "Kimi 2.6",
    "deepseek-v4pro": "DeepSeek V4 Pro",
    "glm-5.2": "GLM 5.2",

    # Backend Model IDs
    "oatmeal-cookie": "GPT-5.2",
    "oval-kumquat-medium": "GPT-5.4",
    "opal-quince-medium": "GPT-5.5",
    "vertex-gemini-2.5-flash": "Gemini 2.5 Flash",
    "vertex-gemini-3.5-flash": "Gemini 3.5 Flash",
    "almond-croissant-low": "Sonnet 4.6",
    "angel-cake-high": "Sonnet 5",
    "avocado-froyo-medium": "Opus 4.6",
    "apricot-sorbet-high": "Opus 4.7",
    "ambrosia-tart-high": "Opus 4.8",
    "oregon-grape-medium": "GPT-5.4 Mini",
    "otaheite-apple-medium": "GPT-5.4 Nano",
    "fireworks-minimax-m2.5": "MiniMax M2.5",
    "fireworks-kimi-k2.6": "Kimi K2.6",
    "baseten-deepseek-v4-pro": "DeepSeek V4 Pro",
    "baseten-glm-5.2": "GLM 5.2",
    "xigua-mochi-medium": "Grok 4.3",
    "xinomavro-cake": "Grok Build 0.1",
    "galette-medium-thinking": "Gemini 3.1 Pro",
    "anthropic-haiku-4.5": "Haiku 4.5",
    "gingerbread": "Gemini 3 Flash",
    "acai-budino": "Fable 5",
}


# Only canonical Notion model codenames are advertised by /v1/models.
# Friendly names and compatibility aliases remain accepted for requests through MODEL_MAP.
EXPOSED_MODEL_IDS: tuple[str, ...] = tuple(NOTION_MODEL_REVERSE_MAP.keys())

MODEL_FAMILIES: dict[str, str] = {
    "almond-croissant-low": "anthropic",
    "angel-cake-high": "anthropic",
    "avocado-froyo-medium": "anthropic",
    "apricot-sorbet-high": "anthropic",
    "ambrosia-tart-high": "anthropic",
    "anthropic-haiku-4.5": "anthropic",
    "acai-budino": "anthropic",
    "oatmeal-cookie": "openai",
    "oval-kumquat-medium": "openai",
    "opal-quince-medium": "openai",
    "oregon-grape-medium": "openai",
    "otaheite-apple-medium": "openai",
    "gingerbread": "google",
    "galette-medium-thinking": "google",
    "vertex-gemini-3.5-flash": "google",
    "vertex-gemini-2.5-flash": "google",
    "xigua-mochi-medium": "xai",
    "xinomavro-cake": "xai",
    "fireworks-minimax-m2.5": "minimax",
    "fireworks-kimi-k2.6": "kimi",
    "baseten-deepseek-v4-pro": "deepseek",
    "baseten-glm-5.2": "glm",
}

MODEL_ICONS: dict[str, str] = {
    # Anthropic
    "claude-sonnet4.6": "✳️",
    "claude-sonnet5": "✳️",
    "claude-opus4.6": "✳️",
    "claude-opus4.7": "✳️",
    "claude-opus4.8": "✳️",
    "claude-haiku4.5": "✳️",
    "claude-fable5": "✳️",
    # OpenAI
    "gpt-5.2": "⚙",
    "gpt-5.4": "⚙",
    "gpt-5.4mini": "⚙",
    "gpt-5.4nano": "⚙",
    "gpt-5.5": "⚙",
    # Google
    "gemini-3flash": "✦",
    "gemini-3-flash": "✦",
    "gemini-3.1pro": "✦",
    "gemini-3.1-pro": "✦",
    "gemini-3.5flash": "✦",
    "gemini-2.5flash": "✦",
    # xAI
    "grok-4.3": "◐",
    "grok-build0.1": "◐",
    # Other
    "minimax-m2.5": "◈",
    "kimi-2.6": "🌙",
    "deepseek-v4pro": "🔷",
    "glm-5.2": "◆",

    # Backend Model IDs
    "almond-croissant-low": "✳️",
    "angel-cake-high": "✳️",
    "avocado-froyo-medium": "✳️",
    "apricot-sorbet-high": "✳️",
    "ambrosia-tart-high": "✳️",
    "anthropic-haiku-4.5": "✳️",
    "acai-budino": "✳️",
    "oatmeal-cookie": "⚙",
    "oval-kumquat-medium": "⚙",
    "oregon-grape-medium": "⚙",
    "otaheite-apple-medium": "⚙",
    "opal-quince-medium": "⚙",
    "gingerbread": "✦",
    "galette-medium-thinking": "✦",
    "vertex-gemini-3.5-flash": "✦",
    "vertex-gemini-2.5-flash": "✦",
    "xigua-mochi-medium": "◐",
    "xinomavro-cake": "◐",
    "fireworks-minimax-m2.5": "◈",
    "fireworks-kimi-k2.6": "🌙",
    "baseten-deepseek-v4-pro": "🔷",
    "baseten-glm-5.2": "◆",
}

# Default to Sonnet 4.6 for a balance of speed and quality.
DEFAULT_MODEL = "claude-sonnet4.6"


def get_notion_model(model_name: str) -> str:
    normalized_name = get_standard_model(model_name)
    return MODEL_MAP.get(normalized_name, MODEL_MAP[DEFAULT_MODEL])


# Notion's public model metadata currently advertises the newer Gemini models
# through workflow/custom-agent capable routes. Keeping them on markdown-chat
# causes Notion upstream 502 responses.
MARKDOWN_CHAT_MODELS: set[str] = {
}


def is_gemini_model(model_name: str) -> bool:
    """Return whether the model belongs to the Gemini family."""
    standard_name = get_standard_model(model_name)
    if standard_name.startswith("gemini-"):
        return True
    notion_model = get_notion_model(standard_name)
    return notion_model.startswith("vertex-") or notion_model.startswith("galette-")


def get_thread_type(model_name: str) -> str:
    """
    Resolve the Notion thread type for a model.
    Only vertex-prefixed models use markdown-chat; all other models use workflow.
    """
    standard_name = get_standard_model(model_name)
    notion_model = get_notion_model(standard_name)
    if notion_model in MARKDOWN_CHAT_MODELS:
        return "markdown-chat"
    return "workflow"


def get_standard_model(model_name: str) -> str:
    model_name = normalize_model_id(model_name)
    if not model_name:
        return DEFAULT_MODEL
    if model_name in NOTION_MODEL_REVERSE_MAP:
        return NOTION_MODEL_REVERSE_MAP[model_name]
    if model_name in MODEL_MAP:
        return model_name
    return DEFAULT_MODEL


def list_available_models() -> list[str]:
    """Return one canonical selectable ID per underlying Notion model."""
    return list(EXPOSED_MODEL_IDS)


def get_model_metadata(model_name: str) -> dict[str, object]:
    """Return canonical model metadata without exposing compatibility aliases as models."""
    notion_model = get_notion_model(model_name)
    public_name = NOTION_MODEL_REVERSE_MAP.get(notion_model, DEFAULT_MODEL)

    if notion_model.startswith("fireworks-"):
        upstream_host = "fireworks"
    elif notion_model.startswith("baseten-"):
        upstream_host = "baseten"
    elif notion_model.startswith("vertex-"):
        upstream_host = "vertex"
    else:
        upstream_host = "notion"

    aliases = [
        alias
        for alias, target in MODEL_MAP.items()
        if target == notion_model and alias != notion_model
    ]

    return {
        "canonical_id": notion_model,
        "public_name": public_name,
        "display_name": DISPLAY_NAMES.get(notion_model, DISPLAY_NAMES.get(public_name, public_name)),
        "model_family": MODEL_FAMILIES.get(notion_model, "unknown"),
        "transport": "notion2api",
        "upstream_host": upstream_host,
        "aliases": aliases,
    }


def is_supported_model(model_name: str) -> bool:
    normalized_name = normalize_model_id(model_name)
    return bool(normalized_name and normalized_name in MODEL_MAP)


def get_display_name(model_name: str) -> str:
    standard_name = get_standard_model(model_name)
    return DISPLAY_NAMES.get(standard_name, standard_name)


def get_model_icon(model_name: str) -> str:
    standard_name = get_standard_model(model_name)
    return MODEL_ICONS.get(standard_name, "")

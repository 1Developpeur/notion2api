from app.model_registry import (
    get_display_name,
    get_model_metadata,
    get_notion_model,
    get_standard_model,
    get_thread_type,
    list_available_models,
    is_supported_model,
)


def test_captured_notion_backend_mappings_are_registered():
    expected = {
        "gpt-5.2": "oatmeal-cookie",
        "gpt-5.4": "oval-kumquat-medium",
        "gpt-5.5": "opal-quince-medium",
        "gemini-2.5flash": "vertex-gemini-2.5-flash",
        "gemini-3.5flash": "vertex-gemini-3.5-flash",
        "claude-sonnet4.6": "almond-croissant-low",
        "claude-sonnet5": "angel-cake-high",
        "claude-opus4.6": "avocado-froyo-medium",
        "claude-opus4.7": "apricot-sorbet-high",
        "claude-opus4.8": "ambrosia-tart-high",
        "gpt-5.4mini": "oregon-grape-medium",
        "gpt-5.4nano": "otaheite-apple-medium",
        "minimax-m2.5": "fireworks-minimax-m2.5",
        "kimi-2.6": "fireworks-kimi-k2.6",
        "deepseek-v4pro": "baseten-deepseek-v4-pro",
        "glm-5.2": "baseten-glm-5.2",
        "grok-4.3": "xigua-mochi-medium",
        "grok-4.5": "strawberry-whoopiepie",
        "grok-build0.1": "xinomavro-cake",
        "gemini-3.1pro": "galette-medium-thinking",
        "claude-haiku4.5": "anthropic-haiku-4.5",
        "gemini-3flash": "gingerbread",
        "claude-fable5": "acai-budino",
    }

    for public_name, notion_name in expected.items():
        assert is_supported_model(public_name)
        assert get_notion_model(public_name) == notion_name
        assert get_standard_model(notion_name) == public_name


def test_captured_display_names_are_registered():
    assert get_display_name("grok-4.3") == "Grok 4.3"
    assert get_display_name("grok-4.5") == "Grok 4.5"
    assert get_display_name("strawberry-whoopiepie") == "Grok 4.5"
    assert get_display_name("grok-build0.1") == "Grok Build 0.1"
    assert get_display_name("minimax-m2.5") == "MiniMax M2.5"
    assert get_display_name("claude-sonnet5") == "Claude Sonnet 5"
    assert get_display_name("claude-haiku4.5") == "Claude Haiku 4.5"
    assert get_display_name("claude-fable5") == "Fable 5"
    assert get_display_name("glm-5.2") == "GLM 5.2"


def test_gemini_3_5_flash_no_longer_uses_markdown_chat_route():
    assert get_thread_type("gemini-2.5flash") == "workflow"
    assert get_thread_type("gemini-3.5flash") == "workflow"


def test_available_models_expose_only_canonical_notion_ids():
    models = list_available_models()

    assert len(models) == 23
    assert len(models) == len(set(models))
    assert "angel-cake-high" in models
    assert "claude-sonnet5" not in models
    assert "apricot-sorbet-high" in models
    assert "claude-opus4.7" not in models
    assert "baseten-glm-5.2" in models
    assert "glm-5.2" not in models
    assert "strawberry-whoopiepie" in models
    assert "grok-4.5" not in models


def test_model_metadata_preserves_transport_and_underlying_family():
    sonnet = get_model_metadata("claude-sonnet5")
    opus = get_model_metadata("claude-opus4.7")
    glm = get_model_metadata("baseten-glm-5.2")

    assert sonnet == {
        "canonical_id": "angel-cake-high",
        "public_name": "claude-sonnet5",
        "display_name": "Sonnet 5",
        "model_family": "anthropic",
        "transport": "notion2api",
        "upstream_host": "notion",
        "aliases": ["claude-sonnet5", "claude-sonnet-5", "sonnet-5", "sonnet5"],
    }
    assert opus == {
        "canonical_id": "apricot-sorbet-high",
        "public_name": "claude-opus4.7",
        "display_name": "Opus 4.7",
        "model_family": "anthropic",
        "transport": "notion2api",
        "upstream_host": "notion",
        "aliases": ["claude-opus4.7"],
    }
    assert glm == {
        "canonical_id": "baseten-glm-5.2",
        "public_name": "glm-5.2",
        "display_name": "GLM 5.2",
        "model_family": "glm",
        "transport": "notion2api",
        "upstream_host": "baseten",
        "aliases": ["glm-5.2"],
    }

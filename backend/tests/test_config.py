from __future__ import annotations

from app.core.config import Settings


def test_cors_origin_list_splits_and_strips() -> None:
    settings = Settings(_env_file=None, cors_origins="http://a:5173, http://b:5173 ,")
    assert settings.cors_origin_list == ["http://a:5173", "http://b:5173"]


def test_llm_configured_false_without_key(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.llm_configured is False


def test_llm_configured_true_with_key() -> None:
    settings = Settings(_env_file=None, deepseek_api_key="secret")
    assert settings.llm_configured is True


def test_default_model_is_deepseek_flash() -> None:
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "deepseek"
    assert settings.deepseek_model == "deepseek-flash"


def test_provider_configured_per_provider(monkeypatch) -> None:
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    settings = Settings(_env_file=None, deepseek_api_key="secret")
    assert settings.provider_configured("deepseek") is True
    assert settings.provider_configured("glm") is False
    assert settings.provider_configured("ollama") is False

    with_glm = Settings(_env_file=None, deepseek_api_key="secret", glm_api_key="  ")
    assert with_glm.provider_configured("glm") is False  # 空白 key 视为未配置

    with_glm2 = Settings(_env_file=None, deepseek_api_key=None, glm_api_key="zhu-pu-key")
    assert with_glm2.provider_configured("glm") is True
    assert with_glm2.provider_configured("deepseek") is False


def test_provider_model_returns_configured_model() -> None:
    settings = Settings(_env_file=None, glm_model="glm-5.3")
    assert settings.provider_model("deepseek") == "deepseek-flash"
    assert settings.provider_model("glm") == "glm-5.3"
    assert settings.provider_model("ollama") == ""


def test_default_glm_settings() -> None:
    settings = Settings(_env_file=None)
    assert settings.glm_base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert settings.glm_model == "glm-5.3-flash"


def test_placeholder_key_is_not_configured() -> None:
    """模板占位符不能被当成已配置（否则健康检查误报、调用时才 401）。"""
    settings = Settings(_env_file=None, deepseek_api_key="your_api_key_here")
    assert settings.provider_configured("deepseek") is False
    assert settings.llm_configured is False

    ok = Settings(_env_file=None, deepseek_api_key="sk-real-looking-key")
    assert ok.provider_configured("deepseek") is True


def test_section_budget_is_clamped() -> None:
    """章节预算：夹到 [MIN_SECTIONS, HARD_SECTION_CEILING] 且 target ≤ max。"""
    from app.core.limits import HARD_SECTION_CEILING, MIN_SECTIONS

    default = Settings(_env_file=None)
    assert default.effective_target_sections == 6
    assert default.effective_max_sections == 12

    too_small = Settings(_env_file=None, target_sections=1, max_sections=2)
    assert too_small.effective_target_sections == MIN_SECTIONS
    # max_sections 是生成上限，不应被 target 反向压低
    assert too_small.effective_max_sections == 2

    too_large = Settings(_env_file=None, target_sections=99, max_sections=99)
    assert too_large.effective_max_sections == HARD_SECTION_CEILING
    assert too_large.effective_target_sections == HARD_SECTION_CEILING

    target_over_max = Settings(_env_file=None, target_sections=18, max_sections=8)
    assert target_over_max.effective_max_sections == 8
    assert target_over_max.effective_target_sections == 8  # 不得高于生成上限


def test_total_chars_is_clamped() -> None:
    from app.core.limits import MAX_TOTAL_CHARS, MIN_TOTAL_CHARS

    assert Settings(_env_file=None).effective_total_chars == 6000
    assert Settings(_env_file=None, target_total_chars=10).effective_total_chars == MIN_TOTAL_CHARS
    big = Settings(_env_file=None, target_total_chars=10**9)
    assert big.effective_total_chars == MAX_TOTAL_CHARS

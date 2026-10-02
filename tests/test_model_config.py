from multicat.llm.model_config import DEFAULT_OPENROUTER_MODEL, model_for_agent


def test_model_for_agent_prefers_agent_specific_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("OPENROUTER_JUDGE_MODEL", "anthropic/claude-sonnet-4.5")

    assert model_for_agent("judge") == "anthropic/claude-sonnet-4.5"


def test_model_for_agent_falls_back_to_shared_env(monkeypatch):
    monkeypatch.delenv("OPENROUTER_EXTRACTION_MODEL", raising=False)
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")

    assert model_for_agent("extraction") == "openai/gpt-4.1-mini"


def test_model_for_agent_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("OPENROUTER_SCREENING_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

    assert model_for_agent("screening") == DEFAULT_OPENROUTER_MODEL

"""Tests for the external prompt-override loader."""
from __future__ import annotations

import importlib

import app.core.prompts as prompts_module


def test_default_template_used_when_prompt_dir_unset(monkeypatch):
    monkeypatch.setattr(prompts_module, "PROMPT_DIR", None)
    result = prompts_module._load_template("system", "DEFAULT-TEXT {agent_name}")
    assert result == "DEFAULT-TEXT {agent_name}"


def test_override_loaded_when_file_present(tmp_path, monkeypatch):
    (tmp_path / "system.md").write_text("OVERRIDE for {company_name}", encoding="utf-8")
    monkeypatch.setattr(prompts_module, "PROMPT_DIR", str(tmp_path))
    result = prompts_module._load_template("system", "DEFAULT")
    assert result == "OVERRIDE for {company_name}"


def test_default_used_when_named_file_missing(tmp_path, monkeypatch):
    # Dir exists but file doesn't.
    monkeypatch.setattr(prompts_module, "PROMPT_DIR", str(tmp_path))
    result = prompts_module._load_template("missing", "FALLBACK")
    assert result == "FALLBACK"


def test_get_system_prompt_uses_override(tmp_path, monkeypatch):
    """End-to-end: PROMPT_DIR + reload picks up overrides."""
    (tmp_path / "system.md").write_text(
        "Hi I am {agent_name} at {company_name}. Time: {now}.",
        encoding="utf-8",
    )
    monkeypatch.setenv("PROMPT_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_NAME", "Eve")
    monkeypatch.setenv("COMPANY_NAME", "Globex")

    # Reload config + prompts so the new env is picked up.
    import app.core.config as cfg
    importlib.reload(cfg)
    reloaded = importlib.reload(prompts_module)
    try:
        rendered = reloaded.get_system_prompt()
        assert "Eve" in rendered
        assert "Globex" in rendered
        assert "Hi I am Eve at Globex" in rendered
    finally:
        # Reset modules so other tests see the original env.
        importlib.reload(cfg)
        importlib.reload(prompts_module)

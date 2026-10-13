"""Guardrails: Model Armor screens what users send and what the agents answer.

Model Armor runs as an ADK plugin, so it wraps every agent call:
    before each model call  -> screen the user's latest message (prompt injection,
                               jailbreaks, hate/harassment/dangerous content,
                               malicious URLs, sensitive data like card numbers)
    after each model call   -> screen the model's text answer the same way
If something matches, the plugin replaces the model call with a safe message.
"""
from google.adk.plugins.base_plugin import BasePlugin

from .settings import MODEL_ARMOR_TEMPLATE

BLOCKED_INPUT = (
    "I can't help with that request. I answer questions about vehicle crash "
    "data, for example: \"Which states had the most traffic deaths in 2020?\""
)
BLOCKED_OUTPUT = "I can't share that answer. Please rephrase your question."


def build_plugins(template: str = MODEL_ARMOR_TEMPLATE, client=None) -> list[BasePlugin]:
    """Returns the guardrail plugins. No template configured = no plugins."""
    if not template:
        return []
    # Imported here so the app still runs without google-cloud-modelarmor
    # installed when guardrails are off.
    from google.adk.integrations.model_armor import ModelArmorConfig, ModelArmorPlugin

    config = ModelArmorConfig(
        prompt_template_name=template,
        response_template_name=template,
        input_blocked_message=BLOCKED_INPUT,
        output_blocked_message=BLOCKED_OUTPUT,
        # Fail closed: if Model Armor can't be reached, block instead of
        # letting unscreened text through.
        block_on_screening_failure=True,
    )
    return [ModelArmorPlugin(config=config, client=client)]

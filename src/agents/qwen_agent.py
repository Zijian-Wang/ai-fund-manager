"""Qwen agent powered by Ollama Cloud (best available Qwen model).

This uses the OLLAMA_CLOUD_API_KEY to run a strong open Qwen model
for portfolio decisions. Only open-weight models are available on Ollama Cloud.
"""

from src.agents.ollama_agent import OllamaAgent


class QwenAgent(OllamaAgent):
    name = "qwen"
    display_name = "Qwen 3.5 (Ollama Cloud)"

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = "qwen3.5:cloud",  # Latest Qwen 3.5 (cloud-hosted, multimodal, strong performance)
        _client=None,
    ) -> None:
        super().__init__(api_key=api_key, model_name=model_name, _client=_client)

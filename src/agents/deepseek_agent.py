"""DeepSeek agent powered by Ollama Cloud (best available DeepSeek-R1 model).

Uses OLLAMA_CLOUD_API_KEY to run the strongest open DeepSeek reasoning model.
"""

from src.agents.ollama_agent import OllamaAgent


class DeepSeekAgent(OllamaAgent):
    name = "deepseek"
    display_name = "DeepSeek R1 (Ollama Cloud)"

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = "deepseek-r1:70b",  # Top reasoning model on Ollama
        _client=None,
    ) -> None:
        super().__init__(api_key=api_key, model_name=model_name, _client=_client)

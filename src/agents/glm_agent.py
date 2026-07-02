"""GLM agent powered by Ollama Cloud (best available GLM model).

Uses OLLAMA_CLOUD_API_KEY for Zhipu GLM open model on cloud.
"""

from src.agents.ollama_agent import OllamaAgent


class GLMAgent(OllamaAgent):
    name = "glm"
    display_name = "GLM-5.2 (Ollama Cloud)"

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = "glm-5.2",  # Latest GLM-5.2 (flagship for long-horizon tasks on Ollama Cloud; 5.2 > 5.1, no 5.4 prominent)
        _client=None,
    ) -> None:
        super().__init__(api_key=api_key, model_name=model_name, _client=_client)

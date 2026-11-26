from __future__ import annotations

from app.live.benchmark import benchmark_models
from app.live.models import LlmResponse
from app.settings import Settings, YamlSettings


class FakeClient:
    def __init__(self) -> None:
        self.models: list[str] = []

    async def generate(self, **kwargs: object) -> LlmResponse:
        self.models.append(str(kwargs["model"]))
        return LlmResponse(text="OK")


async def test_benchmark_calls_agent_and_vision_models_without_network() -> None:
    settings = Settings(config=YamlSettings(), _env_file=None)
    fake = FakeClient()

    results = await benchmark_models(settings, fake)

    assert fake.models == ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]
    assert all(result.ok and result.response_text == "OK" for result in results)

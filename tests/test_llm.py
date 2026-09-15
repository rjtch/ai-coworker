"""LLM client uses only a self-hosted OpenAI-compatible base URL."""

from ai_coworker.config import Settings
from ai_coworker.llm import build_llm


def test_build_llm_points_at_local_endpoint():
    settings = Settings(
        llm_base_url="http://vllm:8000/v1/",
        llm_api_key="cluster-token",
        llm_model="Qwen/Qwen2.5-Coder-14B-Instruct",
        llm_num_ctx=8192,
    )
    llm = build_llm(settings)
    assert llm.openai_api_base == "http://vllm:8000/v1"
    assert llm.model_name == "Qwen/Qwen2.5-Coder-14B-Instruct"
    assert llm.extra_body == {"options": {"num_ctx": 8192}}

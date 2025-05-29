import httpx
import json
import os
import logging
import time
import asyncio
import uvicorn


from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional, List, Dict
from cryptography.fernet import Fernet

# Initialize FastAPI application
app = FastAPI(
    title="LLM Proxy API",
    version="1.0.0",
    description="Unified API wrapper LLM providers"
)

providers = dict()


"""
# Sambanova Provider
PROVIDERS = {
    "sambanova": ProviderConfig(
        name="Sambanova",
        base_url="https://api.sambanova.ai/v1",
        api_key_env="SAMBANOVA_API_KEY",
        supported_models=["DeepSeek-V3-0324"]
    )
}

PROVIDERS = {
    "xai": ProviderConfig(
        name="XAI",
        base_url="https://api.x.ai/v1",
        api_key_env="XAI_API_KEY",
        supported_models=["grok-3-latest"]
        payload["search_parameters"] =\
        {
            "mode": "on",
            "sources": [{ "type": "news", "country": "US" }],
            "from_date": "2025-05-22",
            "to_date": "2022-05-24" 
        }
    )
}
"""

# ========== Core LLM Provider Class ==========
class LLMProvider:
    def __init__(self, name: str, base_url: str, api_key_env: str,
                 supported_models: List[str],
                 payload_extra_options: Dict):
        """Initialize the LLMProvider
        """
        self.name = name
        self.base_url = base_url
        self.client = httpx.AsyncClient()
        self.supported_models = supported_models
        self.payload_extra_options = payload_extra_options
        self.logger = logging.getLogger(name)
        self.api_key = os.getenv(api_key_env)
        if not self.api_key:
            raise ValueError("API Key is missing")

    def get_name(self) -> str:
        """Get the name of the model
        """
        return self.name

    def check_if_model_supported(self, model_name:str):
        """Check if a specific model is supported
        """
        if model_name in self.supported_models:
            return True
        else:
            return False

    def chat_completion(self, payload: dict, stream: bool = False):
        """Complete the chat, given payload
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload.update(self.payload_extra_options)
        print (payload)
        
        if stream:
            print ("--Redirecting to stream completion--")
            return self._stream_completion(payload, headers)
        else:
            return None
            #return await self._standard_completion(payload, headers)

    async def _standard_completion(self, payload: dict, headers: dict):
        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            self.logger.error(f"API Error: {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Provider API error: {e.response.text}"
            )

    async def _stream_completion(self, payload: dict, headers: dict) -> AsyncGenerator[str, None]:
        print ("Starting streaming response")
        print (f"{self.base_url}/chat/completions")
        print (headers)
        print (payload)
        self.client = httpx.AsyncClient()
        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout= 1800
            )
            async for chunk in response.aiter_lines():
                processed = self.process_streaming_chunk(chunk)
                if processed:
                    yield processed
        except httpx.HTTPError as e:
            self.logger.error(f"Streaming error: {str(e)}")
            yield json.dumps({"error": str(e)})

    def process_streaming_chunk(self, chunk: str) -> Optional[str]:
        if chunk.startswith("data: "):
            data = chunk[6:].strip()
            if data == "[DONE]":
                return "data: [DONE]\n\n"
            try:
                parsed = json.loads(data)
                normalized = self.normalize_response(parsed)
                return f"data: {json.dumps(normalized)}\n\n"
            except json.JSONDecodeError:
                return None
        return None

    def normalize_response(self, response: dict) -> dict:
        if "choices" not in response:
            response["choices"] = [{"message": {"role": "assistant", "content": ""}}]
        response["created"] = response.get("created", int(time.time()))
        response["model"] = response.get("model", "unknown")
        return response


class AnalyticsLogger:
    def __init__(self):
        self.logger = logging.getLogger("analytics")
        logging.basicConfig(
            filename="llm_proxy.log",
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    def log_request(self, provider: str, model: str):
        self.logger.info(
            f"Request - Provider: {provider}, Model: {model}"
        )

def load_providers(config_file: str):
    global providers
    with open(config_file, 'r') as f:
        data = json.load(f)
    
        for provider_name, config_data in data.items():
            providers[provider_name] = LLMProvider(
                name=config_data.get("name"),
                base_url=config_data.get("base_url"),
                api_key_env=config_data.get("api_key_env"),
                supported_models=config_data.get("supported_models", []),
                payload_extra_options = config_data.get("payload_extra_parameters")
            )

def get_provider(model: str) -> LLMProvider:
    """Returns an instance of the LLMProvider given an input model.
       Note: In case multiple LLM providers provide the same model,
       the current logic is to return the LLMProvider first encountered.
    """
    for provider in providers.values():
        if provider.check_if_model_supported(model):
            return provider
    raise HTTPException(
        status_code=400,
        detail=f"Model {model} not supported"
    )

# ========== API Endpoints ==========
@app.post("/v1/chat/completions")
async def chat_endpoint(
    request: Request,
    payload: dict,
    authorization: Optional[str] = Header(None)
):
    model = payload.get("model", "")
    provider = get_provider(model)
    AnalyticsLogger().log_request(provider.get_name(), model)
   
    if payload.get("stream", True):
        return StreamingResponse(
            provider.chat_completion(payload, True),
            media_type="text/event-stream"
        )
    else:
        response = await provider.chat_completion(payload, False)
        return response


# ========== Main Execution ==========
if __name__ == "__main__":
    import uvicorn
    load_providers("./config.json")
    uvicorn.run(app, host="0.0.0.0", port=8000)

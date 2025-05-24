from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from dataclasses import dataclass
import httpx
import json
import os
import logging
import time
import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional, List, Dict
from cryptography.fernet import Fernet

# Initialize FastAPI application
app = FastAPI(
    title="LLM Proxy API",
    version="1.0.0",
    description="Unified API wrapper for multiple LLM providers"
)

# ========== Configuration Classes ==========
@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    supported_models: List[str]
    rate_limit: int = 100

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
"""

PROVIDERS = {
    "xai": ProviderConfig(
        name="XAI",
        base_url="https://api.x.ai/v1",
        api_key_env="XAI_API_KEY",
        supported_models=["grok-3-latest"]
    )
}

# ========== Core Provider Class ==========
class LLMProvider:
    def __init__(self, name: str, base_url: str, api_key: str):
        self.name = name
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.AsyncClient()
        self.logger = logging.getLogger(name)

    def chat_completion(self, payload: dict, stream: bool = False):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        print (stream)
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
        payload["search_parameters"] =\
        {
            "mode": "on"
        }
        print (payload)
        self.client = httpx.AsyncClient()
        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout= 1800
            )
            print ("Received response")
            async for chunk in response.aiter_lines():
                print (chunk)
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

# ========== Routing and Rate Limiting ==========
class Router:
    @staticmethod
    def get_provider(model: str) -> LLMProvider:
        for config in PROVIDERS.values():
            if model in config.supported_models:
                api_key = os.getenv(config.api_key_env)
                if not api_key:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Missing API key for {config.name}"
                    )
                return LLMProvider(config.name, config.base_url, api_key)
        raise HTTPException(
            status_code=400,
            detail=f"Model {model} not supported"
        )
"""
class RateLimiter:
    def __init__(self):
        self.counts = defaultdict(list)
        self.limits = {
            "openai": {"req_per_min": 60, "tokens_per_min": 90000},
            "together": {"req_per_min": 100, "tokens_per_min": 120000}
        }

    async def check_limit(self, provider: str, tokens: int) -> bool:
        now = datetime.now()
        window = now - timedelta(minutes=1)
        
        self.counts[provider] = [
            req for req in self.counts[provider]
            if req["time"] > window
        ]
        
        req_count = len(self.counts[provider])
        token_count = sum(req["tokens"] for req in self.counts[provider])
        
        limit = self.limits.get(provider, self.limits["openai"])
        
        if req_count >= limit["req_per_min"]:
            return False
        if token_count + tokens > limit["tokens_per_min"]:
            return False
        
        self.counts[provider].append({
            "time": now,
            "tokens": tokens
        })
        return True
"""

# ========== Security and Logging ==========
class SecureConfig:
    def __init__(self):
        self.cipher = Fernet(os.getenv("ENCRYPTION_KEY", Fernet.generate_key()))
    
    def decrypt_key(self, encrypted: str) -> str:
        return self.cipher.decrypt(encrypted.encode()).decode()

class AnalyticsLogger:
    def __init__(self):
        self.logger = logging.getLogger("analytics")
        logging.basicConfig(
            filename="llm_proxy.log",
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    def log_request(self, provider: str, model: str, tokens: int):
        self.logger.info(
            f"Request - Provider: {provider}, Model: {model}, Tokens: {tokens}"
        )

# ========== API Endpoints ==========
@app.post("/v1/chat/completions")
async def chat_endpoint(
    request: Request,
    payload: dict,
    authorization: Optional[str] = Header(None)
):
    model = payload.get("model", "")
    provider = Router.get_provider(model)
    
    # Estimate tokens (simplified)
    tokens = len(payload.get("messages", [])) * 50
   
    """ 
    if not RateLimiter().check_limit(provider.name.lower(), tokens):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded"
        )
    """
    AnalyticsLogger().log_request(provider.name, model, tokens)
   
    print ("Payload")
    print (payload) 
   
    """ 
    if payload.get("stream", False) or payload.get("stream", True):
        print ("Calling Streaming response")
        return StreamingResponse(
            provider.chat_completion(payload),
            media_type="text/event-stream"
        )
    """
    return StreamingResponse(provider.chat_completion(payload, True), media_type="text/event-stream")
    """
    streaming_mode = payload.get("stream")
    response = await provider.chat_completion(payload, stream=streaming_mode)
    return response
    """


# ========== Main Execution ==========
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

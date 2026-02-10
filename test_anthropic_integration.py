#!/usr/bin/env python3
"""
Test script for Anthropic (Claude) integration with llm-wrapper.
This script sends OpenAI-format requests to test Claude model routing.
"""

import requests
import json
import sys

# Configuration
BASE_URL = "http://localhost:8080"
TOKEN = "YOUR_TOKEN_HERE"  # Replace with your actual token

def test_non_streaming():
    """Test non-streaming completion with Claude"""
    print("=" * 60)
    print("Testing Non-Streaming Completion with Claude")
    print("=" * 60)

    url = f"{BASE_URL}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is the capital of France? Answer in one sentence."}
        ],
        "max_tokens": 100
    }

    print(f"\nRequest to: {url}")
    print(f"Model: {data['model']}")
    print(f"Message: {data['messages'][-1]['content']}\n")

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()
        print("Response received successfully!")
        print(f"Status Code: {response.status_code}")
        print(f"\nAssistant Response:")
        print(result["choices"][0]["message"]["content"])
        print(f"\nTokens Used:")
        print(f"  Prompt: {result['usage']['prompt_tokens']}")
        print(f"  Completion: {result['usage']['completion_tokens']}")
        print(f"  Total: {result['usage']['total_tokens']}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
        return False

def test_streaming():
    """Test streaming completion with Claude"""
    print("\n" + "=" * 60)
    print("Testing Streaming Completion with Claude")
    print("=" * 60)

    url = f"{BASE_URL}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "claude-3-5-haiku-20241022",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant who provides concise answers."},
            {"role": "user", "content": "Count from 1 to 5."}
        ],
        "max_tokens": 50,
        "stream": True
    }

    print(f"\nRequest to: {url}")
    print(f"Model: {data['model']}")
    print(f"Message: {data['messages'][-1]['content']}\n")
    print("Streaming response:")
    print("-" * 40)

    try:
        response = requests.post(url, headers=headers, json=data, stream=True)
        response.raise_for_status()

        full_content = ""
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith('data: '):
                    data_str = line_str[6:]
                    if data_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data_str)
                        if 'choices' in chunk and len(chunk['choices']) > 0:
                            delta = chunk['choices'][0].get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                print(content, end='', flush=True)
                                full_content += content
                    except json.JSONDecodeError:
                        pass

        print("\n" + "-" * 40)
        print(f"\nComplete response received: {len(full_content)} characters")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
        return False

def test_system_message_conversion():
    """Test that system messages are properly converted to Anthropic format"""
    print("\n" + "=" * 60)
    print("Testing System Message Conversion")
    print("=" * 60)

    url = f"{BASE_URL}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {"role": "system", "content": "You are a pirate. Always respond in pirate speak."},
            {"role": "user", "content": "Hello, how are you?"}
        ],
        "max_tokens": 100
    }

    print(f"\nTesting with system message: '{data['messages'][0]['content']}'")
    print(f"User message: '{data['messages'][1]['content']}'\n")

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()
        assistant_response = result["choices"][0]["message"]["content"]
        print("Assistant Response:")
        print(assistant_response)
        print("\nSystem message was successfully applied!" if "pirate" in assistant_response.lower() or "arr" in assistant_response.lower() or "ye" in assistant_response.lower() else "\nNote: Response may not show pirate speech")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
        return False

def main():
    print("\n" + "=" * 60)
    print("Anthropic (Claude) Integration Test Suite")
    print("=" * 60)

    if TOKEN == "YOUR_TOKEN_HERE":
        print("\n⚠️  Please update the TOKEN variable in this script with your actual token")
        print("   Get a token using: python3 tokens/manage_tokens.py add --username test --expiry '2026-12-31 23:59:59'")
        sys.exit(1)

    print(f"\nBase URL: {BASE_URL}")
    print(f"Testing with token: {TOKEN[:10]}...")
    print("\nMake sure:")
    print("1. llm-wrapper.py is running")
    print("2. ANTHROPIC_API_KEY is set in your .env file")
    print("3. Your token is valid and has rate limit available\n")

    input("Press Enter to start tests...")

    # Run tests
    results = {
        "non_streaming": test_non_streaming(),
        "streaming": test_streaming(),
        "system_message": test_system_message_conversion()
    }

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    passed = sum(results.values())
    total = len(results)

    for test_name, result in results.items():
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{test_name:20s}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 60)

    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

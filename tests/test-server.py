import unittest
import requests
import json

class TestChatCompletionsAPI(unittest.TestCase):

    def test_chat_completions(self, set_streaming=True):
        """Test for chat completions.
           :param set_streaming Set to False if you wish to test non-streaming mode
        """
        # Set API endpoint URL
        url = "http://localhost:8000/v1/chat/completions"

        # Set API request headers
        headers = {
            "Authorization": "Bearer", #Note that we are running without an authorization token
            "Content-Type": "application/json"
        }

        # Set API request data
        data = {
            "model": "grok-3-latest",
            "messages": [{"role": "user", "content": "Give me the top news headlines in the last one day"}],
            "stream": set_streaming
        }

        # Send POST request to API endpoint
        response = requests.post(url, headers=headers, data=json.dumps(data))

        # Check if API response is successful (200 OK)
        self.assertEqual(response.status_code, 200)

if __name__ == "__main__":
    unittest.main()

# llm-wrapper
llm-wrapper is built to intercept calls for inference on Large Language Models (LLMs) and re-route the calls to customized cloud providers with customized options and parameters. In essence, you hack the LLM inference API call made by your application, without actually touching the application.

An instance of llm-wrapper is running at: http://knowledge.learnwitharobot.com

# Reasons to use llm-wrapper
llm-wrapper can be useful in the following scenarios:

1. Re-routing LLM calls with specific parameters without touching the application. Most applications have an interface where you can input an OpenAI API compatible cloud provider, and API Key, and usually a LLM model name for running LLM inference. The app then routes calls to the provided LLM provider when it requires to do inference. You might want to adjust specific parameters of the LLM call, but then you would need to change the app software/code, which you might not have access to, or might not understand. llm-wrapper is used to hack the LLM inference call, and then re-route with the needed parameters without much added latency. Please see the use case for Vector robot's Wirepod server as a reference for this use case.
2. Applying rate limits to your LLM inference calls. Typically apps don't set rate limits on the number of LLM inference queries they will issue. Cloud providers allow you to set coarse expense limits such as the amount of money you want to spend in a week or a month. llm-wrapper can be useful to set rate limits on per token granularity, so you can manage exactlty how much inference you want to do.
3. Routing LLM Inference calls across multiple providers. You can implement your own version of Openrouter.ai by routing inference calls across different cloud providers depending on which provider is cheap, has maximum uptime, or is delivering the lowest latency to your request.

4. Parsing the response to generate the final response in OpenAI API compatible format. As an example, for some vendors such as Perplexity Sonar who provide details on citations and search channels, the results need to be morphed to be compliant with other Open API AI compatible providers. 

Note that items 2 and 3 are in the works and are not available yet.

# Using llm-wrapper
After cloning the code from this git repository, please follow the following steps. These steps have been tried and tested on python 3.10

1. Install dependencies:
   
   `python3 -m venv ./venv`
   
   `source ./venv/bin/activate`
   
   `python3 -m pip install -r requirements.txt`
2. Edit the config file. The default config file is set up for XAI, and Perplexity Sonar, and is designed to issue a LLM inference call with additional search for the latest news. The relevant lines in the config file are as follows:
   
```"payload_extra_parameters": {
            "search_parameters": {
                "mode": "on",
                "sources": [{"type": "news"}]
            }
        }
```

Anything added for the key `payload_extra_parameters` is updated in the LLM inference request.

You can also modify the `base_url` to point to your preferred LLM provider (make sure they are OpenAI supported), or `supported_models` to choose a different model you want to use for LLM inference. The `api_key_env` specifies the name of the API_KEY environment variable. As an example, for the provider XAI, the name of the environment varaiable is set to XAI_API_KEY

3. Edit the  .env file which specifies the API Keys for all the providers. You need to get your own API key for each provider. As an example for XAI, you can get the API KEY at the URL https://console.x.ai/
 Currently the .env file looks like:

```
# Insert your XAI API Key below
XAI_API_KEY="<Insert your XAI APi Key here"
# Insert your Perplexity API Key below
PPLX_API_KEY="<Insert your Perplexity Sonar API Key here>"
```

4. Before starting the server for the first time, create the token database (this only needs to be done once):

`python3 tokens/manage_tokens.py list`

This command will initialize the database file at `tokens/auth_tokens.db` with the required schema. You can then use the same script to add or manage tokens as needed.

To add a new token use:
`python3 tokens/manage_tokens.py add --username <username> --expiry <expiry date> --rate-limit <rate-limit>`

You can now see the token with `python3 tokens/manage_tokens.py list`

5. Now start the server using:

`python3 llm-wrapper.py`

This will start the llm wrapper on your localhost at http://0.0.0.0:8000 and use it as your API Key

6. Now on your app which needs to do LLM Inference, you can set the parameters for LLM inference as:
API URL: http://localhost:8000/v1
API Key: <Token created using Step 4>
Model Name: <Choose one of the models from the `supported_models` section of config.json

# Parallel Monitor (offline setup)

This repo includes an **offline** script to create a Parallel Monitor (not integrated into `llm-wrapper.py`).

Per the Monitor API Quickstart, monitor creation is done via `POST https://api.parallel.ai/v1alpha/monitors` with `x-api-key`, `query`, `cadence`, and a `webhook` configuration. See: https://docs.parallel.ai/monitor-api/monitor-quickstart

1. Export your API key:
`export PARALLEL_API_KEY="..."`

2. Create a monitor:

`python3 monitor/create_monitor.py --query "Extract recent news about quantum in AI" --cadence daily --webhook_url "https://YOUR_DOMAIN/webhooks/parallel-monitor" --event_types "monitor.event.detected" --metadata_json '{"key":"value"}'`

# Notes

1. config.json is set up with two providers: XAI and Perplexity Sonar. If you want to use one provider, just delete teh corresponding lines. Commenting out doesn't work in a json file
2. To make the server work in the background, the easiest way is to use nohup. So you can do:
   `nohup python3 llm-wrapper.py&`
and the server starts in the background and output is directed to nohup.out. This will ensure that the server keeps running even after you terminate your shell.
3. In some systems, load_dotenv() does not load from the .env file because it is usable to find the correct location of the .env file. If you run into an error where the script is unable to locate the API keys, it implies that the .env is not locaded correctly. Specify the exact file path to the .env file in load_dotenv(). e.g.
`load_dotenv("/home/amitabha/llm-wrapper/.env`
4. Another alternative is to create a service file and use:
   `systemctl start <service name>`
to start the service.

# Use case: Wirepod server for Vector robot

The Wirepod server for the Vector robot uses LLMs to answer questions that you ask to the Vector robot. In essence, the LLM serves as a knowledge bank. You can use the following screenshot as a reference on how to make Wirepod connect to the llm-wrapper for making inference calls.The following screenshot can be used for reference. Note: Use the token created in Step 4 as the API Key.
![Wirepod-use case](https://github.com/user-attachments/assets/f5dd3bde-3974-4a69-bd13-ae4ee8c2a818)

Now, you can ask Vector about news, and get a response from him. An example is available at: https://youtu.be/FTCZbYjh3oc


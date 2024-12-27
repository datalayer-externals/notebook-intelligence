# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

from enum import Enum
import os, json, time, requests, threading
import nbformat as nbf
from pathlib import Path
import uuid
import secrets
import sseclient
from jupyter_notebook_intelligence.extension import ChatCommand, ChatResponse, ChatRequest, ChatParticipant
from jupyter_notebook_intelligence.config import ContextResponse
from jupyter_notebook_intelligence.github_copilot_prompts import CopilotPrompts

EDITOR_VERSION = "NotebookIntelligence/4.2.5"
EDITOR_PLUGIN_VERSION = "NotebookIntelligence/4.2.5"
USER_AGENT = "NotebookIntelligence/4.2.5"
CLIENT_ID = "Iv1.b507a08c87ecfe98"
MACHINE_ID = secrets.token_hex(33)[0:65]

API_ENDPOINT = "https://api.githubcopilot.com"
PROXY_ENDPOINT = "https://copilot-proxy.githubusercontent.com"
TOKEN_REFRESH_INTERVAL = 1500

LoginStatus = Enum('LoginStatus', ['NOT_LOGGED_IN', 'ACTIVATING_DEVICE', 'LOGGING_IN', 'LOGGED_IN'])

github_auth = {
    "verification_uri": None,
    "user_code": None,
    "device_code": None,
    "access_token": None,
    "status" : LoginStatus.NOT_LOGGED_IN,
    "token": None
}

get_token_thread = None

def get_login_status():
    global github_auth

    response = {
        "status": github_auth["status"].name
    }
    if github_auth["status"] is LoginStatus.ACTIVATING_DEVICE:
        response.update({
            "verification_uri": github_auth["verification_uri"],
            "user_code": github_auth["user_code"]
        })

    return response

def login():
    login_info = get_device_verification_info()
    wait_for_tokens()
    return login_info

def logout():
    global github_auth
    github_auth.update({
        "verification_uri": None,
        "user_code": None,
        "device_code": None,
        "access_token": None,
        "status" : LoginStatus.NOT_LOGGED_IN,
        "token": None
    })
    return {
        "status": github_auth["status"].name
    }

def get_device_verification_info():
    global github_auth
    data = {
        "client_id": CLIENT_ID,
        "scope": "read:user"
    }
    resp = requests.post('https://github.com/login/device/code',
        headers={
            'accept': 'application/json',
            'editor-version': EDITOR_VERSION,
            'editor-plugin-version': EDITOR_PLUGIN_VERSION,
            'content-type': 'application/json',
            'user-agent': USER_AGENT,
            'accept-encoding': 'gzip,deflate,br'
        },
        data=json.dumps(data)
    )

    resp_json = resp.json()
    github_auth["verification_uri"] = resp_json.get('verification_uri')
    github_auth["user_code"] = resp_json.get('user_code')
    github_auth["device_code"] = resp_json.get('device_code')

    github_auth["status"] = LoginStatus.ACTIVATING_DEVICE

    # user needs to visit the verification_uri and enter the user_code
    return {
        "verification_uri": github_auth["verification_uri"],
        "user_code": github_auth["user_code"]
    }

def wait_for_user_access_token_thread_func():
    global github_auth

    while True:
        if github_auth["access_token"] is not None:
            break
        time.sleep(5)
        data = {
            "client_id": CLIENT_ID,
            "device_code": github_auth["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
        }
        resp = requests.post('https://github.com/login/oauth/access_token',
            headers={
            'accept': 'application/json',
            'editor-version': EDITOR_VERSION,
            'editor-plugin-version': EDITOR_PLUGIN_VERSION,
            'content-type': 'application/json',
            'user-agent': USER_AGENT,
            'accept-encoding': 'gzip,deflate,br'
            },
            data=json.dumps(data)
        )

        resp_json = resp.json()
        access_token = resp_json.get('access_token')
        # print(f"ACCESS TOKEN {access_token}")

        if access_token:
            github_auth["access_token"] = access_token
            get_token()

def get_token():
    global github_auth, API_ENDPOINT, PROXY_ENDPOINT, TOKEN_REFRESH_INTERVAL
    access_token = github_auth["access_token"]

    if access_token is None:
        return

    github_auth["status"] = LoginStatus.LOGGING_IN

    resp = requests.get('https://api.github.com/copilot_internal/v2/token', headers={
        'authorization': f'token {access_token}',
        'editor-version': EDITOR_VERSION,
        'editor-plugin-version': EDITOR_PLUGIN_VERSION,
        'user-agent': USER_AGENT
    })

    resp_json = resp.json()
    token = resp_json.get('token')
    github_auth["token"] = token
    github_auth["verification_uri"] = None
    github_auth["user_code"] = None
    github_auth["status"] = LoginStatus.LOGGED_IN

    endpoints = resp_json.get('endpoints', {})
    API_ENDPOINT = endpoints.get('api', API_ENDPOINT)
    PROXY_ENDPOINT = endpoints.get('proxy', PROXY_ENDPOINT)
    TOKEN_REFRESH_INTERVAL = resp_json.get('refresh_in', TOKEN_REFRESH_INTERVAL)

def get_token_thread_func():
    global github_auth
    while True:
        get_token()
        token = github_auth["token"]
        wait_time = 15 if token is None else TOKEN_REFRESH_INTERVAL
        time.sleep(wait_time)

def wait_for_tokens():
    global get_token_thread
    if github_auth["access_token"] is None:
        threading.Thread(target=wait_for_user_access_token_thread_func).start()

    if get_token_thread is None:
        get_token_thread = threading.Thread(target=get_token_thread_func)
        get_token_thread.start()

def _generate_copilot_headers():
    global github_auth
    token = github_auth['token']

    return {
        'authorization': f'Bearer {token}',
        'editor-version': EDITOR_VERSION,
        'editor-plugin-version': EDITOR_PLUGIN_VERSION,
        'user-agent': USER_AGENT,
        'content-type': 'application/json',
        'openai-intent': 'conversation-panel',
        'openai-organization': 'github-copilot',
        'copilot-integration-id': 'vscode-chat',
        'x-request-id': str(uuid.uuid4()),
        'vscode-sessionid': str(uuid.uuid4()),
        'vscode-machineid': MACHINE_ID,
    }

def inline_completions(prefix, suffix, language, filename, context: ContextResponse):
    global github_auth
    token = github_auth['token']

    prompt = f"# Path: {filename}"

    if context is not None:
        for item in context.items:
            context_file = f"Compare this snippet from {item.file_path}:\n{item.content}\n"
            prompt += "\n# " + "\n# ".join(context_file.split('\n'))

    prompt += f"\n{prefix}"

    try:
        resp = requests.post(f"{PROXY_ENDPOINT}/v1/engines/copilot-codex/completions",
            headers={'authorization': f'Bearer {token}'},
                json={
                'prompt': prompt,
                'suffix': suffix,
                'min_tokens': 500,
                'max_tokens': 2000,
                'temperature': 0,
                'top_p': 1,
                'n': 1,
                'stop': ['<END>', '```'],
                'nwo': 'NotebookIntelligence',
                'stream': True,
                'extra': {
                    'language': language,
                    'next_indent': 0,
                    'trim_by_indentation': True
                }
            }
        )
    except requests.exceptions.ConnectionError:
        return ''

    result = ''

    resp_text = resp.text.split('\n')
    for line in resp_text:
        if line.startswith('data: {'):
            json_completion = json.loads(line[6:])
            completion = json_completion.get('choices')[0].get('text')
            if completion:
                result += completion
            # else:
            #     result += '\n'
    
    return result

def completions(messages, tools = None, response: ChatResponse = None):
    stream = response is not None

    try:
        request = requests.post(
            f"{API_ENDPOINT}/chat/completions",
            headers = _generate_copilot_headers(),
            json = {
                'messages': messages,
                'tools': tools,
                'max_tokens': 1000,
                'temperature': 0,
                'top_p': 1,
                'n': 1,
                'stop': ['<END>'],
                'nwo': 'NotebookIntelligence',
                'stream': stream
            },
            stream = stream
        )

        if stream:
            client = sseclient.SSEClient(request)
            for event in client.events():
                if event.data == '[DONE]':
                    response.finish()
                else:
                    response.stream(json.loads(event.data))
            return
        else:
            return request.json()
    except requests.exceptions.ConnectionError:
        raise Exception("Connection error")

def chat(prompt, language, filename, context: ContextResponse):
    messages = [
        {"role": "system", "content": CopilotPrompts.chat_prompt()},
        {"role": "user", "content": f"Active document is {filename}, written in {language}"}
    ]

    if context is not None:
        context_lines = [item.content for item in context.items]
        messages += [{
            "role": "user",
            "content": f"Here is some additional context to help answer this question: \n{"\n".join(context_lines)}"
        }]

    messages += [{"role": "user", "content": prompt}]

    return completions(messages)

def explain_this(selection, language, filename):
    messages = [
        {"role": "system", "content": CopilotPrompts.explain_this_prompt()},
        {"role": "user", "content": f"Active document is {filename}, written in {language}.\nActive selection is \n{selection}\n"},
        {"role": "user", "content": "Can you explain this code?"}
    ]
    return completions(messages)

def fix_this(selection, language, filename):
    messages = [
        {"role": "system", "content": CopilotPrompts.fix_this_prompt()},
        {"role": "user", "content": f"Active document is {filename}, written in {language}.\nActive selection is: \n{selection}\n"},
        {"role": "user", "content": "Can you fix this code?"}
    ]
    return completions(messages)

def _get_unique_notebook_name(parent_path, name):
    if parent_path.startswith("~"):
        parent_path = os.path.expanduser(parent_path)

    tried = 0

    while True:
        suffix = "" if tried == 0 else f"{tried + 1}"
        notebook_name = f"{name}{suffix}.ipynb"
        file_path = Path(os.path.join(parent_path, notebook_name))
        if not file_path.exists():
            return notebook_name
        tried += 1

def new_notebook(prompt, parent_path, context: ContextResponse):
    messages = [{"role": "system", "content": CopilotPrompts.new_notebook_prompt()}]
    if context is not None:
        context_lines = [item.content for item in context.items]
        messages += [{
            "role": "user",
            "content": f"Here is some additional context to help answer this question: \n{"\n".join(context_lines)}"
        }]

    messages += [
        {"role": "user", "content": "Can you create a notebook based on this information:"},
        {"role": "user", "content": prompt}
    ]
    copilot_response = completions(messages)

    if "message" in copilot_response:
        notebook_content = copilot_response["message"]
        response_lines = notebook_content.split("\n")
        content_lines = []
        section_start_found = False
        for line in response_lines:
            if line.startswith("```"):
                if not section_start_found:
                    section_start_found = True
                    continue
                else:
                    break
            if section_start_found:
                content_lines.append(line)

        if len(content_lines) == 0:
            return None
        
        notebook_name = _get_unique_notebook_name(parent_path, "copilot_generated")

        output_path = os.path.join(parent_path, notebook_name)
        save_path = output_path
        if output_path.startswith("~"):
            save_path = os.path.expanduser(output_path)

        content = "\n".join(content_lines)
        nb = nbf.v4.new_notebook()
        nb['metadata'] = {
            "kernelspec": {
                "display_name": "Python 3 (ipykernel)",
                "language": "python",
                "name": "python3"
            }
        }
        nb['cells'] = []
        nb['cells'].append(nbf.v4.new_code_cell(content))
        nbf.write(nb, save_path)

        return {
            "notebook_path": os.path.join(parent_path, notebook_name)
        }

class GithubCopilotChatParticipant(ChatParticipant):
    @property
    def id(self) -> str:
        return "default"
    
    @property
    def commands(self) -> list[ChatCommand]:
        return [
            ChatCommand(name='clear', description='Clears chat history'),
            ChatCommand(name='logout', description='Logs out from GitHub Copilot')
        ]

    async def handle_chat_request(self, request: ChatRequest, response: ChatResponse) -> None:
        messages = [
            {"role": "system", "content": CopilotPrompts.chat_prompt()},
        ]

        print("FROM GITHUB COPILOT CHAT AGENT")

        messages += [{"role": "user", "content": request.prompt}]

        completions(messages, response=response)

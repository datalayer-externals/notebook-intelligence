# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import asyncio
from dataclasses import dataclass
import json
from os import path
import os
from typing import Union
import uuid
import threading
import logging
import tiktoken

from jupyter_server.extension.application import ExtensionApp
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
import tornado
from tornado import websocket
from traitlets import Unicode
from notebook_intelligence.api import CancelToken, ChatResponse, ChatRequest, ContextRequest, ContextRequestType, RequestDataType, ResponseStreamData, ResponseStreamDataType, BackendMessageType, Signal, SignalImpl
from notebook_intelligence.ai_service_manager import AIServiceManager
import notebook_intelligence.github_copilot as github_copilot
from notebook_intelligence.github_copilot_participant import GithubCopilotChatParticipant

ai_service_manager: AIServiceManager = None
log = logging.getLogger(__name__)
tiktoken_encoding = tiktoken.encoding_for_model('gpt-4o')
MAX_TOKENS = 4096

class GetCapabilitiesHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        response = {
            "chat_participants": []
        }
        for participant_id in ai_service_manager.chat_participants:
            participant = ai_service_manager.chat_participants[participant_id]
            response["chat_participants"].append({
                "id": participant.id,
                "name": participant.name,
                "description": participant.description,
                "iconPath": participant.icon_path,
                "commands": [command.name for command in participant.commands]
            })
        self.finish(json.dumps(response))

class GetGitHubLoginStatusHandler(APIHandler):
    # The following decorator should be present on all verb methods (head, get, post,
    # patch, put, delete, options) to ensure only authorized user can request the
    # Jupyter server
    @tornado.web.authenticated
    def get(self):
        self.finish(json.dumps(github_copilot.get_login_status()))

class PostGitHubLoginHandler(APIHandler):
    @tornado.web.authenticated
    def post(self):
        device_verification_info = github_copilot.login()
        if device_verification_info is None:
            self.set_status(500)
            self.finish(json.dumps({
                "error": "Failed to get device verification info from GitHub Copilot"
            }))
            return
        self.finish(json.dumps(device_verification_info))

class GetGitHubLogoutHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        self.finish(json.dumps(github_copilot.logout()))

class ChatHistory:
    """
    History of chat messages, key is chat id, value is list of messages
    keep the last 10 messages in the same chat participant
    """
    MAX_MESSAGES = 10

    def __init__(self):
        self.messages = {}

    def clear(self, chatId = None):
        if chatId is None:
            self.messages = {}
            return True
        elif chatId in self.messages:
            del self.messages[chatId]
            return True

        return False

    def add_message(self, chatId, message):
        if chatId not in self.messages:
            self.messages[chatId] = []

        # clear the chat history if participant changed
        if message["role"] == "user":
            existing_messages = self.messages[chatId]
            prev_user_message = next((m for m in reversed(existing_messages) if m["role"] == "user"), None)
            if prev_user_message is not None:
                (current_participant, command, prompt) = AIServiceManager.parse_prompt(message["content"])
                (prev_participant, command, prompt) = AIServiceManager.parse_prompt(prev_user_message["content"])
                if current_participant != prev_participant:
                    self.messages[chatId] = []

        self.messages[chatId].append(message)
        # limit number of messages kept in history
        if len(self.messages[chatId]) > ChatHistory.MAX_MESSAGES:
            self.messages[chatId] = self.messages[chatId][-ChatHistory.MAX_MESSAGES:]

    def get_history(self, chatId):
        return self.messages.get(chatId, [])

class WebsocketCopilotResponseEmitter(ChatResponse):
    def __init__(self, chatId, messageId, websocket_handler, chat_history):
        super().__init__()
        self.chatId = chatId
        self.messageId = messageId
        self.websocket_handler = websocket_handler
        self.chat_history = chat_history
        self.streamed_contents = []

    @property
    def chat_id(self) -> str:
        return self.chatId

    @property
    def message_id(self) -> str:
        return self.messageId

    def stream(self, data: Union[ResponseStreamData, dict]):
        data_type = ResponseStreamDataType.LLMRaw if type(data) is dict else data.data_type

        if data_type == ResponseStreamDataType.Markdown:
            self.chat_history.add_message(self.chatId, {"role": "assistant", "content": data.content})
            data = {
                "choices": [
                    {
                        "delta": {
                            "nbiContent": {
                                "type": data_type,
                                "content": data.content
                            },
                            "content": "",
                            "role": "assistant"
                        }
                    }
                ]
            }
        elif data_type == ResponseStreamDataType.HTMLFrame:
            data = {
                "choices": [
                    {
                        "delta": {
                            "nbiContent": {
                                "type": data_type,
                                "content" : {
                                    "source": data.source,
                                    "height": data.height
                                }
                            },
                            "content": "",
                            "role": "assistant"
                        }
                    }
                ]
            }
        elif data_type == ResponseStreamDataType.Anchor:
            data = {
                "choices": [
                    {
                        "delta": {
                            "nbiContent": {
                                "type": data_type,
                                "content": {
                                    "uri": data.uri,
                                    "title": data.title
                                }
                            },
                            "content": "",
                            "role": "assistant"
                        }
                    }
                ]
            }
        elif data_type == ResponseStreamDataType.Button:
            data = {
                "choices": [
                    {
                        "delta": {
                            "nbiContent": {
                                "type": data_type,
                                "content": {
                                    "title": data.title,
                                    "commandId": data.commandId,
                                    "args": data.args if data.args is not None else {}
                                }
                            },
                            "content": "",
                            "role": "assistant"
                        }
                    }
                ]
            }
        elif data_type == ResponseStreamDataType.Progress:
            data = {
                "choices": [
                    {
                        "delta": {
                            "nbiContent": {
                                "type": data_type,
                                "content": data.title
                            },
                            "content": "",
                            "role": "assistant"
                        }
                    }
                ]
            }
        elif data_type == ResponseStreamDataType.Confirmation:
            data = {
                "choices": [
                    {
                        "delta": {
                            "nbiContent": {
                                "type": data_type,
                                "content": {
                                    "title": data.title,
                                    "message": data.message,
                                    "confirmArgs": data.confirmArgs if data.confirmArgs is not None else {},
                                    "cancelArgs": data.cancelArgs if data.cancelArgs is not None else {},
                                    "confirmLabel": data.confirmLabel if data.confirmLabel is not None else "Proceed",
                                    "cancelLabel": data.cancelLabel if data.cancelLabel is not None else "Cancel"
                                }
                            },
                            "content": "",
                            "role": "assistant"
                        }
                    }
                ]
            }
        else: # ResponseStreamDataType.LLMRaw
            if len(data.get("choices", [])) > 0:
                part = data["choices"][0].get("delta", {}).get("content", "")
                if part is not None:
                    self.streamed_contents.append(part)

        self.websocket_handler.write_message({
            "id": self.messageId,
            "participant": self.participant_id,
            "type": BackendMessageType.StreamMessage,
            "data": data
        })

    def finish(self) -> None:
        self.chat_history.add_message(self.chatId, {"role": "assistant", "content": "".join(self.streamed_contents)})
        self.streamed_contents = []
        self.websocket_handler.write_message({
            "id": self.messageId,
            "participant": self.participant_id,
            "type": BackendMessageType.StreamEnd,
            "data": {}
        })

    async def run_ui_command(self, command: str, args: dict = {}) -> None:
        callback_id = str(uuid.uuid4())
        self.websocket_handler.write_message({
            "id": self.messageId,
            "participant": self.participant_id,
            "type": BackendMessageType.RunUICommand,
            "data": {
                "callback_id": callback_id,
                "commandId": command,
                "args": args
            }
        })
        response = await ChatResponse.wait_for_run_ui_command_response(self, callback_id)
        return response

class CancelTokenImpl(CancelToken):
    def __init__(self):
        super().__init__()
        self._cancellation_signal = SignalImpl()

    def cancel_request(self) -> None:
        self._cancellation_requested = True
        self._cancellation_signal.emit()

@dataclass
class MessageCallbackHandlers:
    response_emitter: WebsocketCopilotResponseEmitter
    cancel_token: CancelTokenImpl

class WebsocketCopilotHandler(websocket.WebSocketHandler):
    def __init__(self, application, request, **kwargs):
        super().__init__(application, request, **kwargs)
        # TODO: cleanup
        self._messageCallbackHandlers: dict[str, MessageCallbackHandlers] = {}
        self.chat_history = ChatHistory()

    def open(self):
        pass

    def on_message(self, message):
        msg = json.loads(message)

        messageId = msg['id']
        messageType = msg['type']
        if messageType == RequestDataType.ChatRequest:
            data = msg['data']
            chatId = data['chatId']
            prompt = data['prompt']
            language = data['language']
            filename = data['filename']
            additionalContext = data.get('additionalContext', [])

            request_chat_history = self.chat_history.get_history(chatId).copy()

            token_budget = 0.8 * MAX_TOKENS

            for context in additionalContext:
                file_path = context["filePath"]
                file_path = path.join(NotebookIntelligence.root_dir, file_path)
                filename = path.basename(file_path)
                start_line = context["startLine"]
                end_line = context["endLine"]
                current_cell_contents = context["currentCellContents"]
                current_cell_input = current_cell_contents["input"] if current_cell_contents is not None else ""
                current_cell_output = current_cell_contents["output"] if current_cell_contents is not None else ""
                current_cell_context = f"This is a Jupyter notebook and currently selected cell input is: ```{current_cell_input}``` and currently selected cell output is: ```{current_cell_output}```. If user asks a question about 'this' cell then assume that user is referring to currently selected cell." if current_cell_contents is not None else ""
                context_content = context["content"]
                token_count = len(tiktoken_encoding.encode(context_content))
                if token_count > token_budget:
                    context_content = context_content[:int(token_budget)] + "..."

                request_chat_history.append({"role": "user", "content": f"Use this as additional context: ```{context_content}```. It is from current file: '{filename}' at path '{file_path}', lines: {start_line} - {end_line}. {current_cell_context}"})
                self.chat_history.add_message(chatId, {"role": "user", "content": f"This file was provided as additional context: '{filename}' at path '{file_path}', lines: {start_line} - {end_line}. {current_cell_context}"})

            self.chat_history.add_message(chatId, {"role": "user", "content": prompt})
            request_chat_history.append({"role": "user", "content": prompt})
            response_emitter = WebsocketCopilotResponseEmitter(chatId, messageId, self, self.chat_history)
            cancel_token = CancelTokenImpl()
            self._messageCallbackHandlers[messageId] = MessageCallbackHandlers(response_emitter, cancel_token)
            thread = threading.Thread(target=asyncio.run, args=(ai_service_manager.handle_chat_request(ChatRequest(prompt=prompt, chat_history=request_chat_history, cancel_token=cancel_token), response_emitter),))
            thread.start()
        elif messageType == RequestDataType.GenerateCode:
            data = msg['data']
            chatId = data['chatId']
            prompt = data['prompt']
            prefix = data['prefix']
            suffix = data['suffix']
            existing_code = data['existingCode']
            language = data['language']
            filename = data['filename']
            if prefix != '':
                self.chat_history.add_message(chatId, {"role": "user", "content": f"This code section comes before the code section you will generate, use as context. Leading content: ```{prefix}```"})
            if suffix != '':
                self.chat_history.add_message(chatId, {"role": "user", "content": f"This code section comes after the code section you will generate, use as context. Trailing content: ```{suffix}```"})
            if existing_code != '':
                self.chat_history.add_message(chatId, {"role": "user", "content": f"You are asked to modify the existing code. Generate a replacement for this existing code : ```{existing_code}```"})
            self.chat_history.add_message(chatId, {"role": "user", "content": f"Generate code for: {prompt}"})
            response_emitter = WebsocketCopilotResponseEmitter(chatId, messageId, self, self.chat_history)
            cancel_token = CancelTokenImpl()
            self._messageCallbackHandlers[messageId] = MessageCallbackHandlers(response_emitter, cancel_token)
            existing_code_message = " Update the existing code section and return a modified version. Don't just return the update, recreate the existing code section with the update." if existing_code != '' else ''
            thread = threading.Thread(target=asyncio.run, args=(ai_service_manager.handle_chat_request(ChatRequest(prompt=prompt, chat_history=self.chat_history.get_history(chatId), cancel_token=cancel_token), response_emitter, options={"system_prompt": f"You are an assistant that generates code for '{language}' language. You generate code between existing leading and trailing code sections.{existing_code_message} Be concise and return only code as a response. Don't include leading content or trailing content in your response, they are provided only for context. You can reuse methods and symbols defined in leading and trailing content."}),))
            thread.start()
        elif messageType == RequestDataType.InlineCompletionRequest:
            data = msg['data']
            chatId = data['chatId']
            prefix = data['prefix']
            suffix = data['suffix']
            language = data['language']
            filename = data['filename']
            chat_history = ChatHistory()

            response_emitter = WebsocketCopilotResponseEmitter(chatId, messageId, self, chat_history)
            cancel_token = CancelTokenImpl()
            self._messageCallbackHandlers[messageId] = MessageCallbackHandlers(response_emitter, cancel_token)

            thread = threading.Thread(target=asyncio.run, args=(WebsocketCopilotHandler.handle_inline_completions(prefix, suffix, language, filename, response_emitter, cancel_token),))
            thread.start()
        elif messageType == RequestDataType.ChatUserInput:
            handlers = self._messageCallbackHandlers.get(messageId)
            if handlers is None:
                return
            handlers.response_emitter.on_user_input(msg['data'])
        elif messageType == RequestDataType.ClearChatHistory:
            self.chat_history.clear(msg['data']['chatId'])
        elif messageType == RequestDataType.RunUICommandResponse:
            handlers = self._messageCallbackHandlers.get(messageId)
            if handlers is None:
                return
            handlers.response_emitter.on_run_ui_command_response(msg['data'])
        elif messageType == RequestDataType.CancelChatRequest or  messageType == RequestDataType.CancelInlineCompletionRequest:
            handlers = self._messageCallbackHandlers.get(messageId)
            if handlers is None:
                return
            handlers.cancel_token.cancel_request()
 
    def on_close(self):
        pass

    async def handle_inline_completions(prefix, suffix, language, filename, response_emitter, cancel_token):
        context = await ai_service_manager.get_completion_context(ContextRequest(ContextRequestType.InlineCompletion, prefix, suffix, language, filename, participant=ai_service_manager.get_chat_participant(prefix), cancel_token=cancel_token))

        if cancel_token.is_cancel_requested:
            response_emitter.finish()
            return

        completions = ai_service_manager.llm_provider.inline_completions(prefix, suffix, language, filename, context, cancel_token)
        if cancel_token.is_cancel_requested:
            response_emitter.finish()
            return

        response_emitter.stream({"completions": completions})
        response_emitter.finish()

def initialize_extensions():
    global ai_service_manager
    default_chat_participant = GithubCopilotChatParticipant()
    ai_service_manager = AIServiceManager(default_chat_participant)


class NotebookIntelligence(ExtensionApp):
    name = "notebook_intelligence"
    default_url = "/notebook-intelligence"
    load_other_extensions = True
    file_url_prefix = "/render"

    static_paths = []
    template_paths = []
    settings = {}
    handlers = []
    root_dir = ''

    github_access_token = Unicode(
        default_value=None,
        help="""
        GitHub Copilot credentials storage options.

        'remember' - Store credentials in keyring and remember next time.
        'forget' - Remove credentials stored in keyring.
        '<TOKEN_VALUE>' - Use the provided access token value.

        """,
        allow_none=True,
        config=True,
    )

    def initialize_settings(self):
        pass

    def initialize_handlers(self):
        NotebookIntelligence.root_dir = self.serverapp.root_dir
        initialize_extensions()
        self._setup_handlers(self.serverapp.web_app)
        self.serverapp.log.info(f"Registered {self.name} server extension")
        github_copilot.login_with_existing_credentials(self.github_access_token)

    def initialize_templates(self):
        pass

    async def stop_extension(self):
        log.info(f"Stopping {self.name} extension...")
        github_copilot.handle_stop_request()

    def _setup_handlers(self, web_app):
        host_pattern = ".*$"

        base_url = web_app.settings["base_url"]
        route_pattern_capabilities = url_path_join(base_url, "notebook-intelligence", "capabilities")
        route_pattern_github_login_status = url_path_join(base_url, "notebook-intelligence", "gh-login-status")
        route_pattern_github_login = url_path_join(base_url, "notebook-intelligence", "gh-login")
        route_pattern_github_logout = url_path_join(base_url, "notebook-intelligence", "gh-logout")
        route_pattern_copilot = url_path_join(base_url, "notebook-intelligence", "copilot")
        NotebookIntelligence.handlers = [
            (route_pattern_capabilities, GetCapabilitiesHandler),
            (route_pattern_github_login_status, GetGitHubLoginStatusHandler),
            (route_pattern_github_login, PostGitHubLoginHandler),
            (route_pattern_github_logout, GetGitHubLogoutHandler),
            (route_pattern_copilot, WebsocketCopilotHandler),
        ]
        web_app.add_handlers(host_pattern, NotebookIntelligence.handlers)

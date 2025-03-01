# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import json
from os import path
import os
import sys
from typing import Dict
import logging
from notebook_intelligence import github_copilot
from notebook_intelligence.api import ChatModel, EmbeddingModel, InlineCompletionModel, LLMProvider, ChatParticipant, ChatRequest, ChatResponse, CompletionContext, ContextRequest, Host, CompletionContextProvider, NotebookIntelligenceExtension
from notebook_intelligence.base_chat_participant import BaseChatParticipant
from notebook_intelligence.config import NBIConfig
from notebook_intelligence.github_copilot_chat_participant import GithubCopilotChatParticipant
from notebook_intelligence.llm_providers.github_copilot_llm_provider import GitHubCopilotLLMProvider
from notebook_intelligence.llm_providers.ollama_llm_provider import OllamaLLMProvider
from notebook_intelligence.llm_providers.openai_compatible_llm_provider import OpenAICompatibleLLMProvider

log = logging.getLogger(__name__)

DEFAULT_CHAT_PARTICIPANT_ID = 'default'
RESERVED_LLM_PROVIDER_IDS = set([
    'openai', 'anthropic', 'chat', 'copilot', 'jupyter', 'jupyterlab', 'jlab', 'notebook', 'intelligence', 'nb', 'nbi', 'ai', 'config', 'settings', 'ui', 'cell', 'code', 'file', 'data', 'new'
])
RESERVED_PARTICIPANT_IDS = set([
    'chat', 'copilot', 'jupyter', 'jupyterlab', 'jlab', 'notebook', 'intelligence', 'nb', 'nbi', 'terminal', 'vscode', 'workspace', 'help', 'ai', 'config', 'settings', 'ui', 'cell', 'code', 'file', 'data', 'new', 'run', 'search'
])

class AIServiceManager(Host):
    def __init__(self, options: dict = {}):
        self.llm_providers: Dict[str, LLMProvider] = {}
        self.chat_participants: Dict[str, ChatParticipant] = {}
        self.completion_context_providers: Dict[str, CompletionContextProvider] = {}
        self._nbi_config = NBIConfig()
        self._options = options.copy()
        self._openai_compatible_llm_provider = OpenAICompatibleLLMProvider()
        self.initialize()

    @property
    def nbi_config(self) -> NBIConfig:
        return self._nbi_config

    def initialize(self):
        self.chat_participants = {}
        self.register_llm_provider(GitHubCopilotLLMProvider())
        self.register_llm_provider(OllamaLLMProvider())
        self.register_llm_provider(self._openai_compatible_llm_provider)

        self.update_models_from_config()

        self.initialize_extensions()

    def update_models_from_config(self):
        if self.nbi_config.using_github_copilot_service:
            github_copilot.login_with_existing_credentials(self._options.get("github_access_token"))

        chat_model_cfg = self.nbi_config.chat_model
        chat_model_provider_id = chat_model_cfg.get('provider', 'github-copilot')
        chat_model_id = chat_model_cfg.get('model', 'gpt-4o')
        chat_model_provider = self.get_llm_provider(chat_model_provider_id)
        self._chat_model = chat_model_provider.get_chat_model(chat_model_id) if chat_model_provider is not None else None
        print(f"Chat model updated to: {self._chat_model.name if self._chat_model is not None else None}")

        inline_completion_model_cfg = self.nbi_config.inline_completion_model
        inline_completion_model_provider_id = inline_completion_model_cfg.get('provider', 'github-copilot')
        inline_completion_model_id = inline_completion_model_cfg.get('model', 'gpt-4o')
        inline_completion_model_provider = self.get_llm_provider(inline_completion_model_provider_id)
        self._inline_completion_model = inline_completion_model_provider.get_inline_completion_model(inline_completion_model_id) if inline_completion_model_provider is not None else None
        print(f"Inline completion model updated to: {self._inline_completion_model.name if self._inline_completion_model is not None else None}")


        # inline_completion_model_ref = self.nbi_config.inline_completion_model

        # if self._chat_model:
        #     print(f"Chat model: ref: {chat_model_ref}, id: {self._chat_model.id}")
        # self._inline_completion_model = self.get_inline_completion_model(inline_completion_model_ref)
        # if self._inline_completion_model:
        #     print(f"Inlline comple model: {self._inline_completion_model.id}")
        self._embedding_model = None
        
        # if chat_model_provider:
        #     print(f"Chat model provider: {chat_model_provider.id}")

        if chat_model_provider_id == 'openai-compatible':
            chat_model = self._openai_compatible_llm_provider.chat_models[0]
            properties = chat_model_cfg.get('properties', [])
            for property in properties:
                chat_model.set_property_value(property['id'], property['value'])

        if inline_completion_model_provider_id == 'openai-compatible':
            inline_completion_model = self._openai_compatible_llm_provider.inline_completion_models[0]
            properties = inline_completion_model_cfg.get('properties', [])
            for property in properties:
                inline_completion_model.set_property_value(property['id'], property['value'])

        is_github_copilot_chat_model = isinstance(chat_model_provider, GitHubCopilotLLMProvider)
        default_chat_participant = GithubCopilotChatParticipant() if is_github_copilot_chat_model else BaseChatParticipant()
        self._default_chat_participant = default_chat_participant

        self.chat_participants[DEFAULT_CHAT_PARTICIPANT_ID] = self._default_chat_participant


    def initialize_extensions(self):
        extensions_dir = path.join(sys.prefix, "share", "jupyter", "nbi_extensions")
        if not path.exists(extensions_dir):
            return
        subfolders = [f.path for f in os.scandir(extensions_dir) if f.is_dir()]
        for extension_dir in list(subfolders):
            try:
                log.info(f"Loading NBI extension from '{extension_dir}'...")
                metadata_path = path.join(extension_dir, "extension.json")
                if path.exists(metadata_path) and path.isfile(metadata_path):
                    with open(metadata_path, 'r') as file:
                        data = json.load(file)
                        class_name = data['class']
                        extension = self.load_extension(class_name)
                        if extension:
                            extension.activate(self)
                            log.info(f"Activated NBI extension '{class_name}'.")
            except Exception as e:
                log.error(f"Failed to load NBI extension from '{extension_dir}'!\n{e}")
    
    def load_extension(self, extension_class: str) -> NotebookIntelligenceExtension:
        import importlib
        try:
            parts = extension_class.split(".")
            module_name = ".".join(parts[0:-1])
            class_name = parts[-1]
            ExtensionClass = getattr(importlib.import_module(module_name), class_name)
            if ExtensionClass is not None and issubclass(ExtensionClass, NotebookIntelligenceExtension):
                instance = ExtensionClass()
                return instance
        except Exception as e:
            log.error(f"Failed to load NBI extension: '{extension_class}'!\n{e}")

        return None

    def register_chat_participant(self, participant: ChatParticipant):
        if participant.id in RESERVED_PARTICIPANT_IDS:
            log.error(f"Participant ID '{participant.id}' is reserved!")
            return
        if participant.id in self.chat_participants:
            log.error(f"Participant ID '{participant.id}' is already in use!")
            return
        self.chat_participants[participant.id] = participant

    def register_llm_provider(self, provider: LLMProvider) -> None:
        if provider.id in RESERVED_LLM_PROVIDER_IDS:
            log.error(f"LLM Provider ID '{provider.id}' is reserved!")
            return
        if provider.id in self.chat_participants:
            log.error(f"LLM Provider ID '{provider.id}' is already in use!")
            return
        self.llm_providers[provider.id] = provider

    def register_completion_context_provider(self, provider: CompletionContextProvider) -> None:
        if provider.id in self.completion_context_providers:
            log.error(f"Completion Context Provider ID '{provider.id}' is already in use!")
            return
        self.completion_context_providers[provider.id] = provider

    @property
    def default_chat_participant(self) -> ChatParticipant:
        return self._default_chat_participant

    @property
    def chat_model(self) -> ChatModel:
        return self._chat_model
    
    @property
    def inline_completion_model(self) -> InlineCompletionModel:
        return self._inline_completion_model
    
    @property
    def embedding_model(self) -> EmbeddingModel:
        return self._embedding_model

    @staticmethod
    def parse_prompt(prompt: str) -> tuple[str, str, str]:
        participant = DEFAULT_CHAT_PARTICIPANT_ID
        command = ''
        input = ''

        prompt = prompt.lstrip()
        parts = prompt.split(' ')
        parts = [part for part in parts if part.strip() != '']

        if len(parts) > 0:
            if parts[0].startswith('@'):
                participant = parts[0][1:]
                parts = parts[1:]

        if len(parts) > 0:
            if parts[0].startswith('/'):
                command = parts[0][1:]
                parts = parts[1:]

        if len(parts) > 0:
            input = " ".join(parts)

        return [participant, command, input]
    
    def get_llm_provider(self, provider_id: str) -> LLMProvider:
        return self.llm_providers.get(provider_id)
    
    def get_llm_provider_for_model_ref(self, model_ref: str) -> LLMProvider:
        parts = model_ref.split('::')
        if len(parts) < 2:
            return None

        provider_id = parts[0]

        return self.get_llm_provider(provider_id)

    def get_chat_model(self, model_ref: str) -> ChatModel:
        return self._get_provider_model(model_ref, 'chat')
    
    def get_inline_completion_model(self, model_ref: str) -> ChatModel:
        return self._get_provider_model(model_ref, 'inline-completion')
    
    def get_embedding_model(self, model_ref: str) -> ChatModel:
        return self._get_provider_model(model_ref, 'embedding')
    
    def _get_provider_model(self, model_ref: str, model_type: str) -> ChatModel:
        parts = model_ref.split('::')
        if len(parts) < 2:
            return None

        provider_id = parts[0]
        model_id = parts[1]
        llm_provider = self.get_llm_provider(provider_id)

        # print(f"Provider ID: {provider_id}, Model ID {model_id}, {llm_provider}")

        if llm_provider is None:
            return None

        model_list = llm_provider.chat_models if model_type == 'chat' else llm_provider.inline_completion_models if model_type == 'inline-completion' else llm_provider.embedding_models

        # print(f"model_list: {model_list}")

        for model in model_list:
            if model.id == model_id:
                return model

        return None
    
    @property
    def chat_model_ids(self) -> list[ChatModel]:
        model_ids = []
        for provider in self.llm_providers.values():
            model_ids += [{"provider": provider.id, "id": model.id, "name": model.name, "context_window": model.context_window, "properties": [property.to_dict() for property in model.properties]} for model in provider.chat_models]
        return model_ids

    @property
    def inline_completion_model_ids(self) -> list[InlineCompletionModel]:
        model_ids = []
        for provider in self.llm_providers.values():
            model_ids += [{"provider": provider.id, "id": model.id, "name": model.name, "context_window": model.context_window, "properties": [property.to_dict() for property in model.properties]} for model in provider.inline_completion_models]
        return model_ids
    
    @property
    def embedding_model_ids(self) -> list[EmbeddingModel]:
        model_ids = []
        for provider in self.llm_providers.values():
            model_ids += [{"id": f"{provider.id}::{model.id}", "name": f"{provider.name} / {model.name}", "context_window": model.context_window} for model in provider.embedding_models]
        return model_ids

    def get_chat_participant(self, prompt: str) -> ChatParticipant:
        (participant_id, command, input) = AIServiceManager.parse_prompt(prompt)
        return self.chat_participants.get(participant_id, DEFAULT_CHAT_PARTICIPANT_ID)

    async def handle_chat_request(self, request: ChatRequest, response: ChatResponse, options: dict = {}) -> None:
        request.host = self
        (participant_id, command, prompt) = AIServiceManager.parse_prompt(request.prompt)
        participant = self.chat_participants.get(participant_id, DEFAULT_CHAT_PARTICIPANT_ID)
        request.command = command
        request.prompt = prompt
        response.participant_id  = participant_id
        return await participant.handle_chat_request(request, response, options)

    async def get_completion_context(self, request: ContextRequest) -> CompletionContext:
        cancel_token = request.cancel_token
        context = CompletionContext([])

        allowed_context_providers = request.participant.allowed_context_providers

        if cancel_token.is_cancel_requested:
            return context

        for provider in self.completion_context_providers:
            if cancel_token.is_cancel_requested:
                return context
            provider = self.completion_context_providers.get(provider)
            if provider.id not in allowed_context_providers and '*' not in allowed_context_providers:
                continue
            try:
                provider_context = provider.handle_completion_context_request(request)
                if provider_context.items:
                    context.items += provider_context.items
            except Exception as e:
                log.error(f"Error while getting completion context from provider '{provider.id}'!\n{e}")

        return context

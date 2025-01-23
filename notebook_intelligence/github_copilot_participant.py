# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

from notebook_intelligence.api import ChatCommand, ChatParticipant, ChatRequest, ChatResponse, MarkdownData, Tool
from notebook_intelligence.github_copilot import completions
from notebook_intelligence.github_copilot_prompts import CopilotPrompts
import base64

COPILOT_ICON_SVG = '<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="#000000"><path d="M6.25 9.016C6.66421 9.016 7 9.35089 7 9.76399V11.26C7 11.6731 6.66421 12.008 6.25 12.008C5.83579 12.008 5.5 11.6731 5.5 11.26V9.76399C5.5 9.35089 5.83579 9.016 6.25 9.016Z"/><path d="M10.5 9.76399C10.5 9.35089 10.1642 9.016 9.75 9.016C9.33579 9.016 9 9.35089 9 9.76399V11.26C9 11.6731 9.33579 12.008 9.75 12.008C10.1642 12.008 10.5 11.6731 10.5 11.26V9.76399Z"/><path d="M7.86079 1.80482C7.91028 1.8577 7.95663 1.91232 8 1.96856C8.04337 1.91232 8.08972 1.8577 8.13921 1.80482C8.82116 1.07611 9.87702 0.90832 11.0828 1.04194C12.3131 1.17827 13.2283 1.56829 13.8072 2.29916C14.3725 3.01276 14.5 3.90895 14.5 4.77735C14.5 5.34785 14.447 5.92141 14.2459 6.428L14.4135 7.26391L14.4798 7.29699C15.4115 7.76158 16 8.71126 16 9.7501V11.0107C16 11.2495 15.9143 11.4478 15.844 11.5763C15.7691 11.7131 15.6751 11.8368 15.5851 11.9416C15.4049 12.1512 15.181 12.3534 14.9801 12.5202C14.7751 12.6907 14.5728 12.8419 14.4235 12.9494C14.1842 13.1217 13.9389 13.2807 13.6826 13.4277C13.3756 13.6038 12.9344 13.8361 12.3867 14.0679C11.2956 14.5296 9.75604 15 8 15C6.24396 15 4.70442 14.5296 3.61334 14.0679C3.06559 13.8361 2.62435 13.6038 2.31739 13.4277C2.0611 13.2807 1.81581 13.1217 1.57651 12.9494C1.42716 12.8419 1.2249 12.6907 1.01986 12.5202C0.819 12.3534 0.595113 12.1512 0.414932 11.9416C0.3249 11.8368 0.230849 11.7131 0.156031 11.5763C0.0857453 11.4478 0 11.2495 1.90735e-06 11.0107L0 9.7501C0 8.71126 0.588507 7.76158 1.52017 7.29699L1.5865 7.26391L1.75413 6.42799C1.55295 5.9214 1.5 5.34785 1.5 4.77735C1.5 3.90895 1.62745 3.01276 2.19275 2.29916C2.77172 1.56829 3.68694 1.17827 4.91718 1.04194C6.12298 0.90832 7.17884 1.07611 7.86079 1.80482ZM3.0231 7.7282L3 7.8434V12.0931C3.02086 12.1053 3.04268 12.1179 3.06543 12.131C3.32878 12.2821 3.71567 12.4861 4.19916 12.6907C5.17058 13.1017 6.50604 13.504 8 13.504C9.49396 13.504 10.8294 13.1017 11.8008 12.6907C12.2843 12.4861 12.6712 12.2821 12.9346 12.131C12.9573 12.1179 12.9791 12.1053 13 12.0931V7.8434L12.9769 7.7282C12.4867 7.93728 11.9022 8.01867 11.25 8.01867C10.1037 8.01867 9.19051 7.69201 8.54033 7.03004C8.3213 6.80703 8.14352 6.55741 8 6.28924C7.85648 6.55741 7.6787 6.80703 7.45967 7.03004C6.80949 7.69201 5.89633 8.01867 4.75 8.01867C4.09776 8.01867 3.51325 7.93728 3.0231 7.7282ZM6.76421 2.82557C6.57116 2.61928 6.12702 2.41307 5.08282 2.52878C4.06306 2.64179 3.60328 2.93176 3.36975 3.22656C3.12255 3.53861 3 4.01374 3 4.77735C3 5.56754 3.12905 5.94499 3.3082 6.1441C3.47045 6.32443 3.82768 6.52267 4.75 6.52267C5.60367 6.52267 6.08903 6.28769 6.38811 5.98319C6.70349 5.66209 6.91507 5.1591 7.00579 4.43524C7.12274 3.50212 6.96805 3.04338 6.76421 2.82557ZM9.23579 2.82557C9.03195 3.04338 8.87726 3.50212 8.99421 4.43524C9.08493 5.1591 9.29651 5.66209 9.61189 5.98319C9.91097 6.28769 10.3963 6.52267 11.25 6.52267C12.1723 6.52267 12.5295 6.32443 12.6918 6.1441C12.871 5.94499 13 5.56754 13 4.77735C13 4.01374 12.8775 3.53861 12.6303 3.22656C12.3967 2.93176 11.9369 2.64179 10.9172 2.52878C9.87298 2.41307 9.42884 2.61928 9.23579 2.82557Z"/></svg>'
COPILOT_ICON_URL = f"data:image/svg+xml;base64,{base64.b64encode(COPILOT_ICON_SVG.encode("utf-8")).decode('utf-8')}"

class AddMarkdownCellToNotebookTool(Tool):
    @property
    def name(self) -> str:
        return "add_markdown_cell_to_notebook"

    @property
    def title(self) -> str:
        return "Add markdown cell to notebook"
    
    @property
    def tags(self) -> list[str]:
        return ["default-participant-tool"]
    
    @property
    def description(self) -> str:
        return "This is a tool that adds markdown cell to a notebook"
    
    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "markdown_cell_source": {
                            "type": "string",
                            "description": "Markdown to add to the notebook",
                        }
                    },
                    "required": ["markdown_cell_source"],
                    "additionalProperties": False,
                },
            },
        }

    async def handle_tool_call(self, request: ChatRequest, response: ChatResponse, tool_context: dict, tool_args: dict) -> dict:
        markdown = tool_args.get('markdown_cell_source')
        ui_cmd_response = await response.run_ui_command('notebook-intelligence:add-markdown-cell-to-notebook', {'markdown': markdown, 'path': tool_context.get('file_path')})
        return {}

class AddCodeCellTool(Tool):
    @property
    def name(self) -> str:
        return "add_code_cell_to_notebook"

    @property
    def title(self) -> str:
        return "Add code cell to notebook"
    
    @property
    def tags(self) -> list[str]:
        return ["default-participant-tool"]
    
    @property
    def description(self) -> str:
        return "This is a tool that adds code cell to a notebook"
    
    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code_cell_source": {
                            "type": "string",
                            "description": "Code to add to the notebook",
                        }
                    },
                    "required": ["code_cell_source"],
                    "additionalProperties": False,
                },
            },
        }

    async def handle_tool_call(self, request: ChatRequest, response: ChatResponse, tool_context: dict, tool_args: dict) -> dict:
        code = tool_args.get('code_cell_source')
        ui_cmd_response = await response.run_ui_command('notebook-intelligence:add-code-cell-to-notebook', {'code': code, 'path': tool_context.get('file_path')})
        return {}

class GithubCopilotChatParticipant(ChatParticipant):
    @property
    def id(self) -> str:
        return "default"
    
    @property
    def name(self) -> str:
        return "GitHub Copilot"

    @property
    def description(self) -> str:
        return "GitHub Copilot"
    
    @property
    def icon_path(self) -> str:
        return COPILOT_ICON_URL
    
    @property
    def commands(self) -> list[ChatCommand]:
        return [
            ChatCommand(name='newNotebook', description='Create a new notebook'),
            ChatCommand(name='newPythonFile', description='Create a new Python file'),
            ChatCommand(name='clear', description='Clears chat history'),
        ]

    @property
    def tools(self) -> list[Tool]:
        return [AddMarkdownCellToNotebookTool(), AddCodeCellTool()]

    @property
    def allowed_context_providers(self) -> set[str]:
        # any context provider can be used
        return set(["*"])

    async def handle_chat_request(self, request: ChatRequest, response: ChatResponse, options: dict = {}) -> None:
        if request.command == 'newNotebook':
            # create a new notebook
            ui_cmd_response = await response.run_ui_command('notebook-intelligence:create-new-notebook-from-py', {'code': ''})
            file_path = ui_cmd_response['path']
            tool_names = [tool.name for tool in self.tools]
            request.chat_history.insert(0, {"role": "system", "content": f"You are an assistant that creates Jupyter notebooks. Use the functions provided to add markdown or code cells to the notebook. Code cells are written in Python. Markdown cells are written in Markdown. Call the functions with either Python or Markdown content. Do not repeat the code in the code cells with markdown explanations. You have only two functions available to you: '{tool_names[0]}' and '{tool_names[1]}'. Do not assume the availibility of any other tools or functions. Make sure to generate at least one code cell and one markdown cell."})
            await self.handle_chat_request_with_tools(request, response, options, tool_context={
                'file_path': file_path
            }, tool_choice='required')
            return
        elif request.command == 'newPythonFile':
            # create a new python file
            messages = [
                {"role": "system", "content": f"You are an assistant that creates Python code. You should return the code directly without any explantion. You should not print message to explain the code or purpose of the code. You should return the code directly, without wrapping it inside ```."},
                {"role": "user", "content": f"Generate code for: {request.prompt}"}
            ]
            generated = completions(messages)
            code = generated['choices'][0]['message']['content']
            ui_cmd_response = await response.run_ui_command('notebook-intelligence:create-new-file', {'code': code })
            file_path = ui_cmd_response['path']
            response.stream(MarkdownData(f"File '{file_path}' created successfully"))
            response.finish()
            return

        messages = [
            {"role": "system", "content": options.get("system_prompt", CopilotPrompts.chat_prompt())},
        ] + request.chat_history

        completions(messages, response=response, cancel_token=request.cancel_token)

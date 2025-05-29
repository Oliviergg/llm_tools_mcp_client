import llm
import inspect
import asyncio
import json
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pathlib import Path

# Load MCP server configurations from a JSON file
def load_mcp_servers_from_json(config_path):
    if not config_path:
        return []
    
    with open(config_path, "r") as f:
        config = json.load(f)
    servers = []
    for entry in config.get("mcpServers", {}).values():
        servers.append(
            StdioServerParameters(
                command=entry["command"],
                args=entry.get("args", []),
                env=entry.get("env", None)
            )
        )
    return servers

server_configurations = load_mcp_servers_from_json(llm.get_key(alias="MCP_SERVERS_CONFIG", env="MCP_SERVERS_CONFIG"))

class FunctionFactory:
    @staticmethod
    def create_function(tool_spec, server_params_for_tool): # Added server_params_for_tool
        name = tool_spec.name
        description = tool_spec.description
        args_schema = tool_spec.inputSchema.get('properties', {})
        
        params = []
        for arg_name, arg_props in args_schema.items():
            is_optional = 'default' in arg_props or ('anyOf' in arg_props and any(t.get('type') == 'null' for t in arg_props['anyOf']))

            if is_optional:
                default_value = arg_props.get('default', None)
                param = inspect.Parameter(arg_name, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=default_value)
            else:
                param = inspect.Parameter(arg_name, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            params.append(param)
        
        async def dynamic_function(*call_args, **call_kwargs):
            try:
                bound_arguments = dynamic_function.__signature__.bind(*call_args, **call_kwargs)
            except TypeError as e:
                # This can happen if the function is called with wrong number/type of arguments
                raise TypeError(f"Argument mismatch for {name}({dynamic_function.__signature__}): {e}") from e
            
            # Apply default values for any arguments that were not provided in the call
            bound_arguments.apply_defaults()
            print(f"DEBUG: bound_arguments: {bound_arguments.arguments}")
            # Use the specific server_params_for_tool for this function
            async with stdio_client(server_params_for_tool) as (read_client, write_client):
                async with ClientSession(read_client, write_client) as session:
                    await session.initialize()
                    print(f"DEBUG: Calling tool {name} from server {server_params_for_tool.command} with arguments: {bound_arguments.arguments}")
                    result = await session.call_tool(name, arguments=bound_arguments.arguments)
                    if hasattr(result, 'content'):
                        return result.content
                    else:
                        return result
                    
        # Set metadata
        dynamic_function.__name__ = name
        dynamic_function.__doc__ = description
        dynamic_function.__signature__ = inspect.Signature(params)
        
        return dynamic_function


# Modified to iterate over server_configurations
async def get_mcp_tools(configs):
    """Connects to multiple MCP servers and retrieves the list of available tools."""
    all_tools_with_server_info = []
    for server_cfg in configs:
        try:
            async with stdio_client(server_cfg) as (read, write):
                async with ClientSession(read, write) as session:
                    server_id_for_log = f"{server_cfg.command} {' '.join(server_cfg.args) if server_cfg.args else ''}".strip()
                    print(f"Initializing MCP session for server: {server_id_for_log}...")
                    await session.initialize()
                    print(f"Connected to MCP server {server_id_for_log}. Fetching tools...")
                    tool_response = await session.list_tools()                    
                    current_server_tools = []
                    if hasattr(tool_response, 'tools') and isinstance(tool_response.tools, list):
                        current_server_tools = tool_response.tools
                    elif isinstance(tool_response, list):
                         current_server_tools = tool_response
                    else:
                        print(f"Unexpected response format from list_tools for server {server_id_for_log}: {type(tool_response)}")
                        print(f"Response content: {tool_response}")

                    for tool_spec in current_server_tools:
                        all_tools_with_server_info.append({'spec': tool_spec, 'server_params': server_cfg})

        except ConnectionRefusedError:
            server_id_for_log = f"{server_cfg.command} {' '.join(server_cfg.args) if server_cfg.args else ''}".strip()
            print(f"Connection refused when trying to connect to MCP server: {server_id_for_log}. Skipping this server.")
        except Exception as e:
            server_id_for_log = f"{server_cfg.command} {' '.join(server_cfg.args) if server_cfg.args else ''}".strip()
            print(f"An error occurred while connecting to or fetching tools from MCP server {server_id_for_log}: {e}. Skipping this server.")
            
    return all_tools_with_server_info

@llm.hookimpl
def register_tools(register):
    """Synchronously initiates dynamic registration of tools from the MCP server."""
    print("Starting synchronous part of dynamic tool registration...")

    async def _async_register_tools_impl(register_llm_tool):
        print("Entering asynchronous part of tool registration...")
        # Pass the global server_configurations list
        tools_with_server_info = await get_mcp_tools(server_configurations)
        
        if not tools_with_server_info:
            print("No tools found or all servers failed to connect.")
            return

        for tool_info in tools_with_server_info: 
            tool_spec = tool_info['spec']
            server_params_for_tool = tool_info['server_params']
            server_id_for_log = f"{server_params_for_tool.command} {' '.join(server_params_for_tool.args) if server_params_for_tool.args else ''}".strip()
            register_llm_tool(FunctionFactory.create_function(tool_spec, server_params_for_tool))        
            print(f"Registered tool {tool_spec.name} from server {server_id_for_log}")

    try:
        asyncio.run(_async_register_tools_impl(register))
    except RuntimeError as e:
        if "cannot be called while another loop is running" in str(e) or \
           "asyncio.run() cannot be called from a running event loop" in str(e):
            print("Asyncio event loop is already running. Attempting to schedule registration.")
            loop = asyncio.get_event_loop()
            if loop.is_running():
                print("Attempting to schedule _async_register_tools_impl on the running event loop.")
                asyncio.ensure_future(_async_register_tools_impl(register), loop=loop)
                print("Task scheduled. Note: Registration might complete after the main synchronous flow.")
            else:
                try:
                    print("Attempting to run on existing event loop with run_until_complete as it's not running.")
                    loop.run_until_complete(_async_register_tools_impl(register))
                except RuntimeError as e_inner: 
                     print(f"Failed to run on existing loop ({e_inner}). Tools may not be registered.")
                     print("WARNING: Tool registration might be incomplete due to event loop issues.")
        else:
            print(f"An unexpected RuntimeError occurred during tool registration: {e}")
            raise
    except Exception as e:
        print(f"A general error occurred during tool registration: {e}")
        raise
        
    print("Finished synchronous part of dynamic tool registration.")
    
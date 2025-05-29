# MCP Client plugin for simonw llm library

Really WIP. Dont use it. 

## How it works
The approach I chose is straightforward, even naive : 
- The plugin successively connects to each of the MCP servers. 
- For each one, it retrieves the list of tools and dynamically creates a function with the appropriate signature.
- These functions are then registered by llm via the register hook 
- then `llm` will introspects the function to integrate it into the tools list.

## Installation 
- Setup your venv, if needed.
- Clone the project
- In the directory, install the package
```
pip install -e .
```

## Configuration
Copy the file mcp_servers_config.json in your working directory. 

It is setup with three mcp server : 
- [playwright-mcp](https://github.com/microsoft/playwright-mcp) that will drive your Chrome Brower
- [Filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) : with the current directory enable
- [Memory](https://github.com/modelcontextprotocol/servers/tree/main/src/memory)


Example : 
Create a file
```
MCP_SERVERS_CONFIG=./mcp_servers_config.json llm -T write_file 'create a file hello.txt with a random sentence inside it'
```

Open a browser on a given page
```
MCP_SERVERS_CONFIG=./mcp_servers_config.json  lllm  -T browser_navigate 'open hacker news'
```

# Limitation
This is still very much a work in progress. It mostly doesn’t work with MCP servers that require persistence.
I hadn’t considered the implications of the “connected” modes inherent to MCP. This leads to problematic behaviors. For example:
- When launching an LLM command while the plugin is configured, the initialization tries to connect to the servers, which slows down execution.
- With Playwright integration, for instance, the Chrome instance that is opened is tied to the MCP connection and is destroyed as soon as the command finishes. For example, you can’t browse a page and save a screenshot because the browser is closed after each call.

Currently, the plugin opens a new connection to the server for each command, which isn’t optimal either.
Perhaps we should consider something like an MCP daemon that would persist connections instead of relying on the library.
But wouldn’t that be somewhat contrary to the `llm` project’s spirit?


## Working example : 
An agent that will use MCP to generate a tailored daily news summary:
```
MCP_SERVERS_CONFIG=./boring_news_config.json llm -T get_categories -T get_article_groups -T get_similar_articles -T get_articles_by_date '
The goal is to create a summary of the news for 2025-05-21.
Use the list of categories of articles for the day to filter the articles.
A label and a link to each article should display the name of the source.
Summarize the news of the day, organizing the articles in this order:
        1.      Scientific information and AI-related news.
        2.      Then geek culture and entertainment news (video games, movies, books).
        3.      Then French news followed by international news.
For international news, mention the war in Ukraine or Gaza only if there are significant developments.
'
```
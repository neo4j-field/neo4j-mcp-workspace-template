# neo4j-mcp-workspace-template
A template repo for end to end Neo4j development using MCP


## MCP Servers 
* Data Modeling MCP Server
* Ingest MCP Server - custom

## Workflow

* Run discovery on sample of source data 

* Generate, Validate, Visualize first graph data model

* Refine data model with user feedback

* Ingest source data according to finalized data model

* Generate Cypher according to use cases defined during discovery

* Validate that graph adequately addresses the use cases 

## Set Up

### Install Google MCP Toolbox ( Optional )

We will be using the MCP Toolbox prebuilt BigQuery MCP server. This library has a collection of prebuilt MCP servers you may use to connect to Google services.

There are many ways to install the MCP Toolbox. Please see the documentation ([Docs](https://docs.cloud.google.com/bigquery/docs/pre-built-tools-with-mcp-toolbox#mcp-configure-your-mcp-client-cursor) / [Github](https://github.com/googleapis/genai-toolbox?tab=readme-ov-file#installing-the-server)) for more details.

Brew is an easy option though if you have access.
```
brew install mcp-toolbox
```
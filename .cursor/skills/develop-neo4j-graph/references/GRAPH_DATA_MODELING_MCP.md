---
name: Develop a Graph Data Model with Neo4j Data Modeling MCP Server
description: Use the Neo4j Data Modeling MCP server to create valid graph data models. Use to understand the process and order in which MCP tooling and resources should be utilized.
alwaysApply: false
---

# Develop a Graph Data Model with Neo4j Data Modeling MCP Server

Details the data modeling process with the Neo4j Data Modeling MCP server.

## Graph Data Modeling Process

Primary Instructions:
* Ensure that if you know the source information for Properties, you include it in the data model.
* If you deviate from the user's requests, you must clearly explain why you did so.
* Only use data from the provided sample data to create the data model (Unless explicitly stated otherwise).
* If the user requests use cases that are outside the scope of the provided sample data, you should explain why you cannot create a data model for those use cases.

Process:
1. Analysis
    1a. Analyze the sample data 
    1b. Use the `list_example_data_models` tool to check if there are any relevant examples that you can use to guide your data model
    1c. Use the `get_example_data_model` tool to get any relevant example data models
2. Generation
    2a. Generate a new data model based on your analysis, the provided context and any examples
    2b. Use the `get_mermaid_config_str` tool to validate the data model and get a Mermaid visualization configuration
    2c. If necessary, correct any validation errors and repeat step 2b
3. Final Response
    3a. Show the user the visualization with Mermaid, if possible 
    3b. Explain the data model and any gaps between the requested use cases
    3c. Request feedback from the user (remember that data modeling is an iterative process)

## Refine Data Model with User Feedback
* Prompt the user to provide any feedback on the graph data model
* Make any necessary changes and repeat step 2
* If no changes are necessary, then persist the data model as json in `data_models/`
# Connected Knowledge Base Instructions

This project is connected to a live Knowledge Gateway.

Read and follow
[.agents/rules/knowledge-base.md](.agents/rules/knowledge-base.md) for all
knowledge-base work.

When a request may create, update, organize, ingest, search, or recall durable
knowledge, load and follow the `maintain-llm-wiki` skill from
`.agents/skills/maintain-llm-wiki/SKILL.md`.

The configured Knowledge Gateway is authoritative. Do not write live knowledge
directly into this project and never claim that information was saved unless
the gateway returned a durable write receipt. If the gateway tools are not
available, report the connection problem instead of creating another
authority.

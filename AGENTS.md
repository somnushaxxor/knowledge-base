# Agent Kit Repository Instructions

This checkout is the source and test repository for a reusable knowledge-base
agent kit. It is not itself a connected knowledge base.

Do not activate the runtime knowledge-base workflow merely because a task is
performed in this repository. In particular, do not load
`skills/maintain-llm-wiki/SKILL.md` or call a Knowledge Gateway unless the user
explicitly asks to test those assets or to work with a separately configured
live knowledge base.

For changes to the standard or distribution kit:

- keep runtime agent behavior in `rules/`, `skills/`, and
  `templates/runtime/`;
- keep the root agent adapters neutral to prevent this source checkout from
  behaving like an installed knowledge-base project;
- run `scripts/validate-repository.sh` after changes;
- never add live knowledge, backup payloads, credentials, or private runtime
  configuration to this repository.

Repository documentation and reusable agent assets are written in English.

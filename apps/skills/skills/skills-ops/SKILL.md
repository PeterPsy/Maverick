---
name: skills-ops
description: Use the Maverick Skills app to create, inspect, update, or delete workspace-owned runtime skills.
---

Use this skill when a task requires managing workspace-owned runtime skills in Maverick.

Rules:

- Use the Skills app official backend, MCP, or CLI surfaces for real operations.
- Treat user-created skills as workspace-owned data under `data/skills/`.
- Do not edit core skill registries or another app's source directly for Skills app CRUD operations.
- Validate skill ids as lowercase kebab-case before saving.

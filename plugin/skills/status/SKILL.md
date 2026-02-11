# Valence Status Dashboard

Show the current state of the knowledge base.

## Instructions

Query the following MCP tools and format the results as a dashboard:

1. **Knowledge Base Overview** — Use `mcp__valence__belief_query` with query "status overview" and limit 1 to get metadata. Then read the `valence://stats` resource for counts.

2. **Recent Activity** — Use `mcp__valence__belief_query` with a broad query like "recent" and limit 5 to show the newest beliefs. Use `mcp__valence__session_list` with limit 3 for recent sessions.

3. **Auto-Capture Stats** — Query beliefs with extraction_method by reading `valence://stats` resource. Show auto vs manual belief counts.

4. **Health Check** — Use `mcp__valence__tension_list` with status "detected" to find unresolved tensions. Use `mcp__valence__pattern_list` with status "fading" to find stale patterns.

## Output Format

Format as a clean dashboard:

```
## Valence Knowledge Base Status

### Overview
- Beliefs: {count} ({active} active, {superseded} superseded)
- Entities: {count} ({types breakdown})
- Sessions: {count} ({completed} completed)
- Patterns: {count} ({established} established)

### Recent Beliefs
1. [{confidence}] {content preview} — {age}
2. ...

### Recent Sessions
1. {project_context} — {status} — {date}
2. ...

### Health
- Unresolved tensions: {count}
- Fading patterns: {count}

### Suggestions
{Based on what you find, suggest actions like:}
- "Run /valence:review-tensions to resolve 3 detected contradictions"
- "No beliefs captured yet — have a conversation and beliefs will be auto-captured"
- "Consider using belief_create to manually capture important decisions"
```

Adapt the suggestions based on actual data. If the knowledge base is empty, say so clearly and suggest getting started.

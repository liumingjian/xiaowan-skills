# Handoff document

<!-- Shared reference. An identical copy lives in the sibling delegate skill
     (delegate-to-cc / delegate-to-codex). Change one, change both. -->

A handoff is a briefing for an agent that does not share this conversation. It receives a
snapshot, holds no authority over the decision, and is gone once it answers. It is not a
session-continuation document written for the next instance of yourself.

This file defines **how to write** one. Where it is saved, how it reaches the other agent, and
what happens to it afterwards belong to the calling skill.

The shape follows `mattpocock-skills:handoff`, but nothing here depends on that skill or on any
plugin being installed. Do not try to invoke it; write the document yourself.

## Headings

Use exactly these, in this order:

```markdown
# Objective
# Why delegated
# Evidence
# Relevant paths
# Constraints
# Deliverable
# Suggested skills
```

## Writing rules

- Make the objective checkable: the receiving agent must be able to tell whether it hit it.
- Under `# Why delegated`, say what you already tried and where your confidence ends. That is
  what stops the other agent from repeating your dead ends.
- Quote errors verbatim. A paraphrased stack trace is not evidence.
- Reference files by project-relative path instead of pasting them; the whole snapshot is sent.
  Point at specs, plans, ADRs, issues, and commits rather than restating them.
- Write down the agreements reached in this conversation that are not yet in any file. This is
  the part of the handoff no other artifact carries.
- Include the environment notes you bought with trial and error - the exact invocation that
  works, at copy-paste precision - and the traps that cost you a cycle.
- Mark unknowns as unknown. A confident guess reads as a finding.
- Redact credentials, tokens, and personal data.
- Under `# Suggested skills`, name only skills the receiving agent can actually run in its
  sandbox, and say why each one. Suggesting a skill it cannot invoke is worse than suggesting
  nothing: it advertises a route that is not there.

## Done when

A fresh agent could reconstruct the problem, and decide for itself whether it is finished,
without this conversation.

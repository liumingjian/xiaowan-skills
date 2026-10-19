# Shipped knowledge. Only the learn branch changes these, through a reviewed PR.

# Placeholders while CALIBRATED is False. `backtest --adopt` (learn branch) rewrites
# CALIBRATED, COEFFICIENTS, REPO_OFFSETS and RULES with values fitted over calibration.tsv.
CALIBRATED = False
COEFFICIENTS = {
    "base": 30000,          # tokens every implementer spends before touching the ticket
    "k_semantic": 0.5,      # tokens per byte of semantically involved file
    "k_mechanical": 1500,   # tokens per mechanically edited file
}

# Offsets in tokens keyed by normalised git remote (host/owner/name). A repo gets one only
# with 5 usable calibration rows, and never the repo with the most rows (the base fits it).
REPO_OFFSETS = {}

# Rules learned from outliers, each citing the calibration rows ("<repo>#<ticket>") it came
# from. Schema (see SKILL.md, Learn):
#   {"id": str, "kind": "term" | "tagging", "enabled": bool, "text": str, "match": glob,
#    "tokens": int (term only: added per footprint file matching `match`),
#    "cites": [row, ...],            # non-empty, each also a key of "rows"
#    "rows": {row: effect | None}}   # every calibration row the rule changes; None = re-explore
# A term effect is {"units": n}; a tagging effect is the row's re-explored footprint,
# {"semantic_bytes": n, "mechanical_files": n}, used instead of the stored columns.
# FOOTPRINT.md applies enabled tagging rules; estimate applies enabled term rules.
RULES = []

# The implementer subagent's context-peak budget, in tokens.
BUDGET = 150000

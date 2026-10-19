# Shipped knowledge. Only the learn branch changes these, through a reviewed PR.

# Fitted over calibration.tsv. `backtest --adopt` (learn branch) rewrites CALIBRATED,
# COEFFICIENTS, REPO_OFFSETS and RULES; CALIBRATED is False only for placeholder values.
CALIBRATED = True
COEFFICIENTS = {
    "base": 59604,  # tokens every implementer spends before touching the ticket
    "k_semantic": 0.3993,  # tokens per byte of semantically involved file
    "k_mechanical": 96,  # tokens per mechanically edited file
}

# Offsets in tokens keyed by normalised git remote (host/owner/name). A repo gets one only
# with 5 usable calibration rows, and never the repo with the most rows (the base fits it).
REPO_OFFSETS = {}

# Rules learned from outliers, each citing the calibration rows it came from.
# Schema: the docstring of rules.py, beside this file.
RULES = []

# The implementer subagent's context-peak budget, in tokens.
BUDGET = 150000

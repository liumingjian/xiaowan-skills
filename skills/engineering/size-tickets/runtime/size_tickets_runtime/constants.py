# Shipped knowledge. Only the learn branch changes these, through a reviewed PR.

# Placeholders while CALIBRATED is False. `backtest --adopt` (learn branch) rewrites
# CALIBRATED and COEFFICIENTS with values fitted over calibration.tsv.
CALIBRATED = False
COEFFICIENTS = {
    "base": 30000,          # tokens every implementer spends before touching the ticket
    "k_semantic": 0.5,      # tokens per byte of semantically involved file
    "k_mechanical": 1500,   # tokens per mechanically edited file
}

# Offsets keyed by normalised git remote; a repo gets one only after 5 calibration rows.
REPO_OFFSETS = {}

# The implementer subagent's context-peak budget, in tokens.
BUDGET = 150000

# Shipped knowledge. Only the learn branch changes these, through a reviewed PR.

# Fitted over calibration.tsv. `backtest --adopt` (learn branch) rewrites CALIBRATED,
# COEFFICIENTS, REPO_OFFSETS and RULES; CALIBRATED is False only for placeholder values.
CALIBRATED = True
COEFFICIENTS = {
    "base": 60913,  # tokens every implementer spends before touching the ticket
    "k_semantic": 0.3859,  # tokens per byte of semantically involved file
    "k_mechanical": 748,  # tokens per mechanically edited file
}

# Offsets in tokens keyed by normalised git remote (host/owner/name). A repo gets one only
# with 5 usable calibration rows, and never the repo with the most rows (the base fits it).
REPO_OFFSETS = {}

# Rules learned from outliers, each citing the calibration rows it came from.
# Schema: the docstring of rules.py, beside this file.
RULES = [
    {'id': 'rename-consumer-tests',
     'kind': 'tagging',
     'enabled': True,
     'text': 'Test files (*.test.*, *.spec.*) are mechanical when the ticket only moves or renames '
             'modules or identifiers that they import or reference. Such tests are updated by '
             'scripted search-and-replace and checked by running the suite, so tag them semantic '
             'only if the ticket changes the behaviour they assert.',
     'match': '*.test.*',
     'cites': ['github.com/liumingjian/reimburse-ai#434'],
     'rows': {'github.com/liumingjian/reimburse-ai#434': {'semantic_bytes': 116982,
                                                          'mechanical_files': 55}}},
]

# The implementer subagent's context-peak budget, in tokens.
BUDGET = 150000

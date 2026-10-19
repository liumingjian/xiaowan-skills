# Engineering

Stable skills for day-to-day code work.

- **[rexec](./rexec/SKILL.md)** - Run durable builds, tests, and other heavy work from `vps-cc` on the paired Mac mini. Model-invoked.
- **[size-tickets](./size-tickets/SKILL.md)** - Estimate each ticket's implementer context peak and tier before a spec's slicing is final. User-invoked.

`rexec` depends on the fixed `vps-cc` SSH alias, dedicated private credentials, and a user background service on one Mac mini. Viewers are independent of execution. Setup and service tooling is provided; installing the skill does not deploy it. See [the reference](./rexec/REFERENCE.md) for setup, recovery, and privacy limits.

`size-tickets` needs `python3` and `git`. Its coefficients are placeholders, and every report is marked uncalibrated, until a `learn` run's backtest adopts fitted ones through a reviewed PR.

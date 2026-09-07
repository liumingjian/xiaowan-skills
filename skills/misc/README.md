# Misc

Useful skills that are kept outside the stable catalog.

- **[rexec](./rexec/SKILL.md)** - Dispatch builds, test suites, and other heavy work from a memory-starved server to a Mac that pulls the job. Model-invoked.

`rexec` is infrastructure-specific: it expects an SSH alias reaching the server from the Mac, and a resident agent started on each Mac. It lives here rather than in the stable catalog because it is useful only once that channel exists.

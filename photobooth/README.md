# photobooth package

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the authoritative component reference,
asyncio design, template system, and capture flow diagrams.

The `Thread` class and `run_as_thread` helper documented in older versions of this file
have been removed. All concurrent operations use `asyncio.create_task` or
`loop.run_in_executor`.

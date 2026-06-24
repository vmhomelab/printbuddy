from __future__ import annotations

import asyncio


async def run_command(argv: list[str], *, timeout_seconds: int) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        return 124, stdout.decode(errors="replace"), "Command timed out"
    return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")

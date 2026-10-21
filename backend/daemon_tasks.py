"""Short-lived owned preview tasks cannot hold the interpreter open on a slow share."""
import asyncio
import threading
from fastapi import HTTPException

_slots=threading.BoundedSemaphore(2)


async def daemon_call(function, *args):
    if not _slots.acquire(blocking=False): raise HTTPException(409,'Two previews are still waiting on files. Wait for them or close and reopen SAP Lens.')
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    def finish(value=None, error=None):
        if result.done(): return
        if error: result.set_exception(error)
        else: result.set_result(value)

    def run():
        try:
            value, error = function(*args), None
        except Exception as exc:
            value, error = None, exc
        _slots.release()
        try: loop.call_soon_threadsafe(finish,value,error)
        except RuntimeError: pass

    threading.Thread(target=run,name='sap-lens-preview',daemon=True).start()
    return await result

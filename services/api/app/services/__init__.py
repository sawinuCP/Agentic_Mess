"""Domain services: business logic + persistence, framework-free (no FastAPI imports).

Routes stay thin: parse request (schemas) → call service → return response.
Sync services are invoked from async routes via ``asyncio.to_thread``.
"""

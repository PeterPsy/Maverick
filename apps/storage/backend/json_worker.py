"""Storage's optional reusable JSON entrypoint; ordinary entrypoints stay available."""

from core.app_sdk.json_worker import serve_json_requests


def handle_payload(payload: dict) -> dict:
    if payload.get("stream_response_protocol"):
        raise ValueError("Storage media streams require the ordinary backend entrypoint.")
    if payload.get("surface") == "mcp":
        from mcp_requests import handle_payload as handle_mcp
        return handle_mcp(payload)
    if payload.get("surface") == "backend":
        from app_backend import handle_payload as handle_backend
        response = handle_backend(payload)
        if response is not None:
            return response
    raise ValueError("Unsupported Storage JSON worker surface.")


if __name__ == "__main__":
    serve_json_requests(handle_payload)

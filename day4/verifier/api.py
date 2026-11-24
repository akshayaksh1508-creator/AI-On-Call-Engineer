"""Optional FastAPI adapter exposing POST /verify/sandbox."""
def create_router(repo_path, allowed_paths=None, forbidden_paths=None, timeout=120, container_image=None):
    try:
        from fastapi import APIRouter, HTTPException
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("Install fastapi and pydantic to enable the HTTP adapter.") from exc
    from day4.verifier.sandbox import SandboxVerifier

    class SandboxRequest(BaseModel):
        patch: str
        test_command: list[str] = Field(min_length=1)
        repro_command: list[str] = Field(min_length=1)

    router = APIRouter()

    @router.post("/verify/sandbox")
    def verify_sandbox(request: SandboxRequest):
        verifier = SandboxVerifier(repo_path, allowed_paths, forbidden_paths, timeout, container_image)
        result = verifier.verify(request.patch, request.test_command, request.repro_command)
        return result.to_dict()

    return router

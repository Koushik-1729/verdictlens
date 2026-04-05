"""
VerdictLens Prompt Hub — pull prompts by name for use in agent code.

Usage::

    import verdictlens as vl

    vl.configure(endpoint="http://localhost:8000", workspace_id="my-workspace")
    prompt = vl.hub.pull("summarize-agent")          # latest version
    prompt_v2 = vl.hub.pull("summarize-agent", version=2)  # specific version

    # Full metadata
    result = vl.hub.pull("summarize-agent", full=True)
    print(result["content"], result["model"], result["temperature"])
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

import httpx

from verdictlens.config import get_config


def pull(
    name: str,
    version: Optional[int] = None,
    workspace_id: Optional[str] = None,
    full: bool = False,
) -> Union[str, Dict[str, Any]]:
    """
    Pull a prompt from VerdictLens Prompt Hub.

    :param name: Prompt name as saved in the Prompt Hub.
    :param version: Specific version number. Omit for latest published version.
    :param workspace_id: Override workspace. Defaults to configured workspace.
    :param full: If True return full metadata dict; otherwise return content string.
    :returns: Prompt content string, or full metadata dict if ``full=True``.
    :raises httpx.HTTPStatusError: If the prompt is not found or request fails.

    Example::

        system_prompt = vl.hub.pull("customer-support-v3")
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_prompt}, ...],
        )
    """
    cfg = get_config()
    base = cfg.endpoint.rstrip("/")
    ws = workspace_id or cfg.workspace_id or "default"

    params: Dict[str, Any] = {}
    if version is not None:
        params["version"] = version

    headers: Dict[str, str] = {"X-VerdictLens-Workspace": ws}
    if cfg.api_key:
        headers["X-VerdictLens-Key"] = cfg.api_key

    url = f"{base}/prompt-hub/{name}/pull"
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data: Dict[str, Any] = resp.json()

    return data if full else data["content"]

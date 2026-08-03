"""Patch pinned Paritok 1.2.7 with request-scoped compression headers."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_paritok_response_headers.py PATH")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    start = source.index("    async def handle_openai")
    end = source.index("    async def handle_responses", start)
    section = source[start:end]

    meter_line = (
        '        _report_tool_savings(body.get("model", ""), tools_orig_tok, tools_comp_tok)\n'
    )
    if section.count(meter_line) != 1:
        raise RuntimeError("unexpected Paritok OpenAI metering block")
    measurement = (
        meter_line
        + """
        compression_original = stats.original_tokens + tools_orig_tok
        compression_compressed = stats.compressed_tokens + tools_comp_tok
        compression_headers = {
            "x-paritok-input-tokens-original": str(compression_original),
            "x-paritok-input-tokens-compressed": str(compression_compressed),
            "x-paritok-tokens-saved": str(
                max(0, compression_original - compression_compressed)
            ),
        }
"""
    )
    section = section.replace(meter_line, measurement, 1)

    old_return = (
        "        return JSONResponse(content=final_body, status_code=status_code, "
        "headers=resp_headers)\n"
    )
    if section.count(old_return) != 1:
        raise RuntimeError("unexpected Paritok OpenAI response block")
    new_return = """        return JSONResponse(
            content=final_body,
            status_code=status_code,
            headers={**resp_headers, **compression_headers},
        )
"""
    section = section.replace(old_return, new_return, 1)
    path.write_text(f"{source[:start]}{section}{source[end:]}", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

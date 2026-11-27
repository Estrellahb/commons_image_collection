#!/usr/bin/env python3
"""Lightweight 4-trial direct model evaluator for ZeroBench (no local/Docker tools)."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = Path(__file__).resolve().parent
for p in (str(PROJECT_ROOT), str(SCRIPT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from review_case import IMAGE_EXTS, parse_author_record_html

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-6.2-sol"
DEFAULT_EFFORT = "max"
LEADING_ZERO_CODE_RE = re.compile(r"^[+-]?0\d+$")
PLAIN_NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
CODE_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_+-]*)\n(.*?)```", re.S)
ANSWER_PREFIX_RE = re.compile(r"^(?:最终答案|标准答案|答案|Final\s+Answer|Answer|Output)\s*[:：]\s*", re.I)


def load_dotenv_file(path: Path) -> dict[str, str]:
    """Parse key=value pairs from a .env file without external dependencies."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, raw_val = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        val = raw_val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            q = val[0]
            val = val[1:-1]
            if q == '"':
                val = val.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        values[key] = val
    return values


def normalize_base_url(raw: str | None) -> str:
    url = (raw or "").strip() or DEFAULT_BASE_URL
    url = url.rstrip("/")
    if not re.search(r"/v\d+$", url):
        url = f"{url}/v1"
    return url


def resolve_openai_config(env_file: Path | None = None, env: dict[str, str] | None = None) -> tuple[str, str]:
    env_map = os.environ if env is None else env
    dotenv = load_dotenv_file(env_file if env_file is not None else (PROJECT_ROOT / ".env"))
    api_key = (env_map.get("OPENAI_API_KEY") or dotenv.get("OPENAI_API_KEY") or "").strip()
    base_url = normalize_base_url(env_map.get("OPENAI_BASE_URL") or dotenv.get("OPENAI_BASE_URL"))
    return api_key, base_url


def detect_image_mime(path: Path, raw_bytes: bytes) -> str:
    if raw_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    if raw_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw_bytes[:2] == b"BM":
        return "image/bmp"
    if raw_bytes[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def resolve_case_inputs(
    *,
    case_path: Path | None = None,
    image_path: Path | None = None,
    prompt_text: str | None = None,
    prompt_file: Path | None = None,
    expected_text: str | None = None,
    expected_file: Path | None = None,
    case_id: str | None = None,
) -> dict:
    resolved_id = case_id
    resolved_image = image_path
    resolved_prompt = prompt_text
    resolved_expected = expected_text

    if prompt_file is not None:
        resolved_prompt = prompt_file.read_text(encoding="utf-8")
    if expected_file is not None:
        resolved_expected = expected_file.read_text(encoding="utf-8")

    if case_path is not None:
        cp = case_path.resolve()
        if not cp.exists():
            raise FileNotFoundError(f"--case does not exist: {cp}")
        case_dir = cp if cp.is_dir() else cp.parent
        html_file = cp if (cp.is_file() and cp.suffix.lower() in {".html", ".htm"}) else (case_dir / "author_record.html")
        if html_file.is_file():
            parsed = parse_author_record_html(html_file)
            resolved_id = resolved_id or parsed.get("id")
            if resolved_prompt is None:
                resolved_prompt = parsed.get("prompt", "")
            if resolved_expected is None:
                resolved_expected = parsed.get("response", "")
            if resolved_image is None:
                imgs = sorted(p for p in case_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
                if len(imgs) == 1:
                    resolved_image = imgs[0]
                elif imgs:
                    for im_meta in parsed.get("images") or []:
                        src = (im_meta.get("src") or "").strip()
                        if src and not src.startswith("data:") and (case_dir / Path(src).name).is_file():
                            resolved_image = case_dir / Path(src).name
                            break
                    if resolved_image is None:
                        resolved_image = imgs[0]
        else:
            author = {}
            for name in ("author.json", "question.json"):
                cand = cp if (cp.is_file() and cp.name == name) else (case_dir / name)
                if cand.is_file():
                    author = json.loads(cand.read_text(encoding="utf-8"))
                    break
            resolved_id = resolved_id or author.get("id") or case_dir.name.removeprefix("authoring_")
            if resolved_prompt is None:
                if isinstance(author.get("prompt"), str):
                    resolved_prompt = author["prompt"]
                else:
                    for pf in ("prompt.txt", "prompt.md", "public/prompt.md"):
                        if (case_dir / pf).is_file():
                            resolved_prompt = (case_dir / pf).read_text(encoding="utf-8")
                            break
            if resolved_expected is None:
                raw_ans = author.get("response", author.get("answer"))
                if raw_ans is not None:
                    resolved_expected = str(raw_ans)
                else:
                    for ef in ("response.txt", "answer.txt"):
                        if (case_dir / ef).is_file():
                            resolved_expected = (case_dir / ef).read_text(encoding="utf-8")
                            break
            if resolved_image is None:
                img_ref = author.get("image_path")
                if isinstance(img_ref, str) and (case_dir / img_ref).is_file():
                    resolved_image = case_dir / img_ref
                else:
                    for pat in ("main.*", "public/image.*", "*"):
                        found = sorted(p for p in case_dir.glob(pat) if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
                        if found:
                            resolved_image = found[0]
                            break

    if resolved_image is None or not resolved_image.is_file():
        raise ValueError(f"Main image not found: {resolved_image}")
    if not isinstance(resolved_prompt, str) or not resolved_prompt.strip():
        raise ValueError("Prompt text is empty or missing")
    if not isinstance(resolved_expected, str) or not resolved_expected.strip():
        raise ValueError("Expected response text is empty or missing")

    return {
        "case_id": resolved_id or resolved_image.stem,
        "image_path": resolved_image.resolve(),
        "prompt": resolved_prompt.strip(),
        "expected": resolved_expected.strip(),
    }


def _strip_outer_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("`", '"', "'"):
        return s[1:-1].strip()
    return s


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    depth_sq = 0
    depth_par = 0
    in_quote: str | None = None
    escape = False
    for ch in text:
        if escape:
            cur.append(ch)
            escape = False
            continue
        if ch == "\\" and in_quote is not None:
            cur.append(ch)
            escape = True
            continue
        if in_quote is not None:
            cur.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            cur.append(ch)
        elif ch == "[":
            depth_sq += 1
            cur.append(ch)
        elif ch == "]":
            depth_sq = max(0, depth_sq - 1)
            cur.append(ch)
        elif ch == "(":
            depth_par += 1
            cur.append(ch)
        elif ch == ")":
            depth_par = max(0, depth_par - 1)
            cur.append(ch)
        elif ch == sep and depth_sq == 0 and depth_par == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return parts


def _parse_plain_decimal(tok: str) -> Decimal | None:
    if LEADING_ZERO_CODE_RE.match(tok):
        return None
    if not PLAIN_NUMBER_RE.match(tok):
        return None
    try:
        d = Decimal(tok)
        return d if d.is_finite() else None
    except InvalidOperation:
        return None


def tokens_equivalent(expected_tok: str, actual_tok: str) -> bool:
    e = expected_tok.strip()
    a = actual_tok.strip()
    if e == a:
        return True

    # Strip symmetric backticks on actual if expected doesn't have them
    if len(a) >= 2 and a[0] == "`" and a[-1] == "`" and not (len(e) >= 2 and e[0] == "`"):
        a = a[1:-1].strip()
        if e == a:
            return True

    # Leading-zero codes (like 010610) MUST match exact string
    if LEADING_ZERO_CODE_RE.match(e) or LEADING_ZERO_CODE_RE.match(a):
        return False

    # Plain numbers (e.g. 3 vs 3.0)
    de = _parse_plain_decimal(e)
    da = _parse_plain_decimal(a)
    if de is not None and da is not None:
        return de == da

    # Bracketed list / tuple comparison e.g. [30,1,"ABC"] vs [30.0, 1, "ABC"]
    if len(e) >= 2 and len(a) >= 2 and ((e[0], e[-1]) == ("[", "]") and (a[0], a[-1]) == ("[", "]") or (e[0], e[-1]) == ("(", ")") and (a[0], a[-1]) == ("(", ")")):
        ep = _split_top_level(e[1:-1], ",")
        ap = _split_top_level(a[1:-1], ",")
        return len(ep) == len(ap) and all(tokens_equivalent(x, y) for x, y in zip(ep, ap))

    # Semicolon-separated list inside a segment
    if ";" in e or ";" in a:
        ep = _split_top_level(e, ";")
        ap = _split_top_level(a, ";")
        if len(ep) > 1 or len(ap) > 1:
            return len(ep) == len(ap) and all(tokens_equivalent(x, y) for x, y in zip(ep, ap))

    # Comma-separated list without brackets
    if "," in e or "," in a:
        ep = _split_top_level(e, ",")
        ap = _split_top_level(a, ",")
        if len(ep) > 1 or len(ap) > 1:
            return len(ep) == len(ap) and all(tokens_equivalent(x, y) for x, y in zip(ep, ap))

    return False


def _parse_kv_block(text: str) -> list[tuple[str, str]] | None:
    items: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for seg in _split_top_level(line, ";"):
            seg = seg.strip()
            if not seg:
                continue
            if "=" not in seg:
                return None
            k, v = seg.split("=", 1)
            k, v = k.strip(), v.strip()
            if not k:
                return None
            items.append((k, v))
    return items if items else None


def _clean_candidate_text(text: str) -> str:
    s = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if s.startswith("```") and s.endswith("```"):
        m = CODE_FENCE_RE.fullmatch(s)
        if m:
            s = m.group(1).strip()
    return "\n".join(line.rstrip() for line in s.splitlines()).strip()


def _candidate_views(expected_clean: str, actual_raw: str) -> list[tuple[str, str]]:
    """Produce ordered (source_tag, text) views of model output to grade against expected."""
    views: list[tuple[str, str]] = []
    seen: set[str] = set()

    def push(tag: str, val: str):
        cleaned = _clean_candidate_text(val)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            views.append((tag, cleaned))

    push("full", actual_raw)
    fences = CODE_FENCE_RE.findall(actual_raw.replace("\r\n", "\n"))
    if fences:
        push("last_code_block", fences[-1])

    exp_lines = [ln.strip() for ln in expected_clean.splitlines() if ln.strip()]
    act_lines = [ln.strip() for ln in _clean_candidate_text(actual_raw).splitlines() if ln.strip()]

    if len(exp_lines) == 1 and act_lines:
        last_line = act_lines[-1]
        push("last_line", last_line)
        stripped = ANSWER_PREFIX_RE.sub("", last_line).strip()
        push("last_line_stripped_prefix", stripped)
        push("last_line_unquoted", _strip_outer_quotes(stripped))
        if "|" in expected_clean:
            for line in reversed(act_lines):
                cand = _strip_outer_quotes(ANSWER_PREFIX_RE.sub("", line).strip())
                if "|" in cand:
                    push("last_pipe_line", cand)
                    break
    elif len(exp_lines) > 1 and len(act_lines) > len(exp_lines):
        push("trailing_lines", "\n".join(act_lines[-len(exp_lines):]))

    return views


def grade_answer(expected: str, actual: str) -> dict:
    """Compare model output text against expected response using strict normalized rules."""
    exp_clean = _clean_candidate_text(expected)
    if not isinstance(actual, str) or not actual.strip():
        return {"matched": False, "method": "empty_actual"}

    views = _candidate_views(exp_clean, actual)
    exp_lines = [ln.strip() for ln in exp_clean.splitlines() if ln.strip()]
    exp_kv = _parse_kv_block(exp_clean) if "=" in exp_clean else None

    for tag, cand in views:
        if cand == exp_clean:
            return {"matched": True, "method": f"exact:{tag}"}

        if len(exp_lines) == 1 and "|" in exp_clean and "|" in cand:
            exp_segs = [s.strip() for s in exp_clean.split("|")]
            cand_segs = [s.strip() for s in cand.split("|")]
            if len(exp_segs) == len(cand_segs) and all(tokens_equivalent(es, cs) for es, cs in zip(exp_segs, cand_segs)):
                return {"matched": True, "method": f"pipe_fields:{tag}"}

        if exp_kv is not None:
            cand_kv = _parse_kv_block(cand)
            if cand_kv is not None and len(cand_kv) == len(exp_kv):
                if all(ek == ck and tokens_equivalent(ev, cv) for (ek, ev), (ck, cv) in zip(exp_kv, cand_kv)):
                    return {"matched": True, "method": f"key_value:{tag}"}
                exp_map = dict(exp_kv)
                cand_map = dict(cand_kv)
                if len(exp_map) == len(exp_kv) and exp_map.keys() == cand_map.keys():
                    if all(tokens_equivalent(exp_map[k], cand_map[k]) for k in exp_map):
                        return {"matched": True, "method": f"key_value_unordered:{tag}"}

        cand_lines = [ln.strip() for ln in cand.splitlines() if ln.strip()]
        if len(exp_lines) == len(cand_lines) and all(tokens_equivalent(el, cl) for el, cl in zip(exp_lines, cand_lines)):
            return {"matched": True, "method": f"normalized_lines:{tag}"}

    return {"matched": False, "method": "mismatch"}


def build_request_spec(
    *,
    api_kind: str,
    base_url: str,
    model: str,
    effort: str,
    prompt: str,
    data_url: str,
) -> tuple[str, dict]:
    if api_kind == "responses":
        return (
            f"{base_url}/responses",
            {
                "model": model,
                "reasoning": {"effort": effort},
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": data_url},
                        ],
                    }
                ],
            },
        )
    if api_kind == "chat":
        return (
            f"{base_url}/chat/completions",
            {
                "model": model,
                "reasoning_effort": effort,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
            },
        )
    raise ValueError(f"Unsupported api_kind: {api_kind}")


def extract_response_text(api_kind: str, payload: dict) -> tuple[str, str | None, str | None]:
    model_returned = payload.get("model")
    if api_kind == "responses":
        effort_returned = (payload.get("reasoning") or {}).get("effort") if isinstance(payload.get("reasoning"), dict) else None
        ot = payload.get("output_text")
        if isinstance(ot, str) and ot.strip():
            return ot, model_returned, effort_returned
        chunks: list[str] = []
        for item in payload.get("output") or []:
            if not isinstance(item, dict):
                continue
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in ("output_text", "text", None):
                    txt = part.get("text")
                    if isinstance(txt, str):
                        chunks.append(txt)
                    elif isinstance(txt, dict) and isinstance(txt.get("value"), str):
                        chunks.append(txt["value"])
        return "\n".join(c for c in chunks if c), model_returned, effort_returned

    effort_returned = payload.get("reasoning_effort") or (
        (payload.get("reasoning") or {}).get("effort") if isinstance(payload.get("reasoning"), dict) else None
    )
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return "", model_returned, effort_returned
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content, model_returned, effort_returned
    if isinstance(content, list):
        chunks = [p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)]
        return "\n".join(chunks), model_returned, effort_returned
    return "", model_returned, effort_returned


def _post_json(url: str, api_key: str, body: dict, timeout: int) -> tuple[int, dict]:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = int(getattr(resp, "status", resp.getcode()))
        data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Response JSON root is not an object")
        return status, data


def run_single_trial(
    *,
    trial_idx: int,
    api_mode: str,
    base_url: str,
    api_key: str,
    model: str,
    effort: str,
    prompt: str,
    data_url: str,
    expected: str,
    timeout: int,
) -> dict:
    started = time.monotonic()
    order = ["responses", "chat"] if api_mode == "auto" else [api_mode]
    last_error = None
    http_status = None

    for idx, kind in enumerate(order):
        url, payload = build_request_spec(
            api_kind=kind,
            base_url=base_url,
            model=model,
            effort=effort,
            prompt=prompt,
            data_url=data_url,
        )
        try:
            http_status, resp_json = _post_json(url, api_key, payload, timeout)
            output_text, model_ret, effort_ret = extract_response_text(kind, resp_json)
            elapsed = round(time.monotonic() - started, 3)
            if not output_text.strip():
                return {
                    "trial": trial_idx,
                    "status": "error",
                    "http_status": http_status,
                    "api_used": kind,
                    "model_requested": model,
                    "model_returned": model_ret,
                    "effort_requested": effort,
                    "effort_returned": effort_ret,
                    "elapsed_seconds": elapsed,
                    "output_text": "",
                    "grade": {"matched": False, "method": "empty_response_text"},
                    "error": "Empty model output text in HTTP 200 payload",
                }
            grade = grade_answer(expected, output_text)
            return {
                "trial": trial_idx,
                "status": "correct" if grade["matched"] else "incorrect",
                "http_status": http_status,
                "api_used": kind,
                "model_requested": model,
                "model_returned": model_ret,
                "effort_requested": effort,
                "effort_returned": effort_ret,
                "elapsed_seconds": elapsed,
                "output_text": output_text,
                "grade": grade,
                "error": None,
            }
        except urllib.error.HTTPError as exc:
            http_status = int(exc.code)
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                err_body = ""
            last_error = f"HTTP {http_status}: {err_body or exc.reason}"
            if api_mode == "auto" and idx == 0 and http_status in (404, 405):
                continue
            break
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            break

    return {
        "trial": trial_idx,
        "status": "error",
        "http_status": http_status,
        "api_used": order[-1],
        "model_requested": model,
        "model_returned": None,
        "effort_requested": effort,
        "effort_returned": None,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "output_text": "",
        "grade": {"matched": False, "method": "request_error"},
        "error": last_error or "Unknown request error",
    }


def evaluate_verdict(trials: list[dict], requested_trials: int) -> tuple[dict, bool | None, str]:
    correct = sum(1 for t in trials if t["status"] == "correct")
    incorrect = sum(1 for t in trials if t["status"] == "incorrect")
    errors = sum(1 for t in trials if t["status"] == "error")
    completed_valid = correct + incorrect
    counts = {
        "correct": correct,
        "incorrect": incorrect,
        "error": errors,
        "completed_valid": completed_valid,
    }
    if incorrect >= 1:
        return counts, True, "qualified"
    if completed_valid < requested_trials:
        return counts, None, "inconclusive_errors"
    return counts, False, "too_easy_all_correct"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", type=Path, default=None, help="Case directory or author_record.html")
    ap.add_argument("--image", type=Path, default=None, help="Explicit image path")
    ap.add_argument("--prompt", default=None, help="Explicit prompt string")
    ap.add_argument("--prompt-file", type=Path, default=None, help="Explicit prompt file")
    ap.add_argument("--expected", default=None, help="Explicit expected answer string")
    ap.add_argument("--expected-file", type=Path, default=None, help="Explicit expected answer file")
    ap.add_argument("--case-id", default=None, help="Optional case ID override")
    ap.add_argument("--out", type=Path, default=None, help="Output JSON summary path")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--effort", default=DEFAULT_EFFORT)
    ap.add_argument("--trials", type=int, default=4)
    ap.add_argument("--api", choices=("auto", "responses", "chat"), default="auto")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--env-file", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true", help="Validate parsing, image encoding, and payloads without network requests")
    args = ap.parse_args(argv)

    if args.trials < 1:
        ap.error("--trials must be >= 1")
    if args.concurrency < 1:
        ap.error("--concurrency must be >= 1")
    if args.timeout < 1:
        ap.error("--timeout must be >= 1")

    resolved = resolve_case_inputs(
        case_path=args.case,
        image_path=args.image,
        prompt_text=args.prompt,
        prompt_file=args.prompt_file,
        expected_text=args.expected,
        expected_file=args.expected_file,
        case_id=args.case_id,
    )
    img_bytes = resolved["image_path"].read_bytes()
    mime = detect_image_mime(resolved["image_path"], img_bytes)
    b64_img = base64.b64encode(img_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64_img}"

    api_key, base_url = resolve_openai_config(args.env_file)

    if args.dry_run:
        primary_kind = "responses" if args.api in ("auto", "responses") else "chat"
        preview_url, preview_payload = build_request_spec(
            api_kind=primary_kind,
            base_url=base_url,
            model=args.model,
            effort=args.effort,
            prompt=resolved["prompt"],
            data_url=f"data:{mime};base64,<{len(b64_img)}_chars>",
        )
        summary = {
            "schema_version": "1.0",
            "dry_run": True,
            "case_id": resolved["case_id"],
            "image_path": str(resolved["image_path"]),
            "image_mime": mime,
            "image_bytes": len(img_bytes),
            "prompt_characters": len(resolved["prompt"]),
            "expected_response": resolved["expected"],
            "model": args.model,
            "reasoning_effort": args.effort,
            "api_mode": args.api,
            "base_url": base_url,
            "api_key_configured": bool(api_key),
            "requested_trials": args.trials,
            "concurrency": args.concurrency,
            "timeout_seconds": args.timeout,
            "preview_endpoint": preview_url,
            "preview_payload": preview_payload,
        }
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if not api_key:
        err = {
            "ok": False,
            "error": "missing_api_key",
            "message": "OPENAI_API_KEY is not configured in environment or .env",
            "base_url": base_url,
        }
        print(json.dumps(err, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    trials: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(args.concurrency, args.trials)) as pool:
        futures = [
            pool.submit(
                run_single_trial,
                trial_idx=i,
                api_mode=args.api,
                base_url=base_url,
                api_key=api_key,
                model=args.model,
                effort=args.effort,
                prompt=resolved["prompt"],
                data_url=data_url,
                expected=resolved["expected"],
                timeout=args.timeout,
            )
            for i in range(1, args.trials + 1)
        ]
        for fut in as_completed(futures):
            trials.append(fut.result())

    trials.sort(key=lambda t: t["trial"])
    counts, qualified, verdict = evaluate_verdict(trials, args.trials)
    summary = {
        "schema_version": "1.0",
        "dry_run": False,
        "case_id": resolved["case_id"],
        "image_path": str(resolved["image_path"]),
        "image_mime": mime,
        "image_bytes": len(img_bytes),
        "expected_response": resolved["expected"],
        "model": args.model,
        "reasoning_effort": args.effort,
        "api_mode": args.api,
        "base_url": base_url,
        "api_key_configured": True,
        "requested_trials": args.trials,
        "counts": counts,
        "difficulty_qualified": qualified,
        "verdict": verdict,
        "trials": trials,
    }
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

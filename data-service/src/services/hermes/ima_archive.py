from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|credential|authorization)", re.IGNORECASE)


class HermesImaArchiveService:
    def __init__(
        self,
        *,
        archive_root: str | Path,
        skill_dir: str | Path,
        knowledge_base_id: str,
        enabled: bool,
        upload_enabled: bool,
    ) -> None:
        self.archive_root = Path(archive_root)
        self.skill_dir = Path(skill_dir)
        self.knowledge_base_id = knowledge_base_id.strip()
        self.enabled = enabled
        self.upload_enabled = upload_enabled

    @classmethod
    def from_env(cls) -> "HermesImaArchiveService":
        archive_enabled_raw = os.getenv("HERMES_IMA_ARCHIVE_ENABLED", "").strip().lower()
        configured = bool(
            os.getenv("IMA_REFERENCE_SOURCE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
            and os.getenv("IMA_OPENAPI_CLIENTID", "").strip()
            and os.getenv("IMA_OPENAPI_APIKEY", "").strip()
            and os.getenv("IMA_DEFAULT_KNOWLEDGE_BASE_ID", "").strip()
        )
        enabled = configured if not archive_enabled_raw else archive_enabled_raw in {"1", "true", "yes", "on"}
        upload_raw = os.getenv("HERMES_IMA_ARCHIVE_UPLOAD_ENABLED", "true").strip().lower()
        return cls(
            archive_root=os.getenv("HERMES_IMA_ARCHIVE_ROOT", "/app/.artifacts/hermes/ima-archive"),
            skill_dir=os.getenv("IMA_SKILL_DIR", "/app/skills/ima-skill"),
            knowledge_base_id=os.getenv("IMA_DEFAULT_KNOWLEDGE_BASE_ID", ""),
            enabled=enabled,
            upload_enabled=upload_raw in {"1", "true", "yes", "on"},
        )

    async def archive(
        self,
        *,
        source: str,
        title: str,
        content_markdown: str | None = None,
        payload: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        prompt: str | None = None,
        result_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "skipped", "reason": "ima_archive_disabled"}
        payload = payload if isinstance(payload, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        now = datetime.now().astimezone()
        day = now.strftime("%Y-%m-%d")
        day_dir = self.archive_root / day
        day_dir.mkdir(parents=True, exist_ok=True)
        safe_title = _slug(title or result_type or source or "hermes-output")
        digest = hashlib.sha256(
            json.dumps(_redact(payload), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:10]
        filename = f"{now.strftime('%H%M%S')}-{_slug(source or 'hermes')}-{safe_title}-{digest}.md"
        path = day_dir / filename
        markdown = _render_markdown(
            generated_at=now.isoformat(),
            source=source,
            title=title,
            tenant_id=tenant_id,
            prompt=prompt,
            result_type=result_type,
            content_markdown=content_markdown,
            payload=payload,
            metadata=metadata,
        )
        path.write_text(markdown, encoding="utf-8")

        result: dict[str, Any] = {
            "status": "saved",
            "path": str(path),
            "date": day,
            "filename": filename,
        }
        if not self.upload_enabled:
            result["ima"] = {"status": "skipped", "reason": "ima_upload_disabled"}
            return result
        try:
            result["ima"] = await self._upload_file(path, filename, day)
            if result["ima"].get("status") == "synced":
                result["status"] = "synced"
        except Exception as exc:  # noqa: BLE001 - archive must never break user/cron output.
            result["ima"] = {"status": "failed", "reason": str(exc)}
        return result

    async def _upload_file(self, path: Path, filename: str, day: str) -> dict[str, Any]:
        if not self.knowledge_base_id:
            return {"status": "skipped", "reason": "IMA_DEFAULT_KNOWLEDGE_BASE_ID_missing"}
        ima_api = self.skill_dir / "ima_api.cjs"
        cos_upload = self.skill_dir / "knowledge-base" / "scripts" / "cos-upload.cjs"
        preflight = self.skill_dir / "knowledge-base" / "scripts" / "preflight-check.cjs"
        for required in (ima_api, cos_upload, preflight):
            if not required.exists():
                return {"status": "skipped", "reason": f"missing_skill_file:{required}"}

        preflight_result = await self._run_json("node", str(preflight), "--file", str(path))
        media_type = int(preflight_result.get("media_type") or 7)
        content_type = str(preflight_result.get("content_type") or "text/markdown")
        file_size = int(preflight_result.get("file_size") or path.stat().st_size)
        folder_id = await self._find_date_folder(day)
        check_body: dict[str, Any] = {
            "params": [{"name": filename, "media_type": media_type}],
            "knowledge_base_id": self.knowledge_base_id,
        }
        if folder_id:
            check_body["folder_id"] = folder_id
        await self._ima_api("openapi/wiki/v1/check_repeated_names", check_body)

        create_resp = await self._ima_api(
            "openapi/wiki/v1/create_media",
            {
                "file_name": filename,
                "file_size": file_size,
                "content_type": content_type,
                "knowledge_base_id": self.knowledge_base_id,
                "file_ext": "md",
            },
        )
        create_data = _response_data(create_resp)
        media_id = create_data.get("media_id") or create_data.get("id")
        credential = create_data.get("cos_credential") or create_data.get("credential") or {}
        if not media_id or not isinstance(credential, dict):
            raise RuntimeError("IMA create_media response missing media_id or cos_credential")

        upload_args = [
            "node",
            str(cos_upload),
            "--file",
            str(path),
            "--secret-id",
            _credential_value(credential, "secret_id", "tmp_secret_id", "secretId"),
            "--secret-key",
            _credential_value(credential, "secret_key", "tmp_secret_key", "secretKey"),
            "--token",
            _credential_value(credential, "token", "session_token"),
            "--bucket",
            _credential_value(credential, "bucket_name", "bucket"),
            "--region",
            _credential_value(credential, "region"),
            "--cos-key",
            _credential_value(credential, "cos_key", "key"),
            "--content-type",
            content_type,
            "--timeout",
            "300000",
        ]
        start_time = _credential_value(credential, "start_time", "startTime", default="")
        expired_time = _credential_value(credential, "expired_time", "expiredTime", default="")
        if start_time:
            upload_args.extend(["--start-time", str(start_time)])
        if expired_time:
            upload_args.extend(["--expired-time", str(expired_time)])
        await self._run_text(*upload_args)

        add_body: dict[str, Any] = {
            "media_type": media_type,
            "media_id": media_id,
            "title": filename,
            "knowledge_base_id": self.knowledge_base_id,
            "file_info": {
                "cos_key": _credential_value(credential, "cos_key", "key"),
                "file_size": file_size,
                "file_name": filename,
            },
        }
        if folder_id:
            add_body["folder_id"] = folder_id
        add_resp = await self._ima_api("openapi/wiki/v1/add_knowledge", add_body)
        code = add_resp.get("code")
        if code not in (0, "0", None):
            raise RuntimeError(f"IMA add_knowledge failed: code={code} msg={add_resp.get('msg')}")
        return {
            "status": "synced",
            "media_id": media_id,
            "date_folder": "matched" if folder_id else "not_found_root_upload",
        }

    async def _find_date_folder(self, day: str) -> str | None:
        if os.getenv("HERMES_IMA_ARCHIVE_USE_DATE_FOLDER", "true").strip().lower() not in {"1", "true", "yes", "on"}:
            return None
        try:
            result = await self._ima_api(
                "openapi/wiki/v1/search_knowledge",
                {"query": day, "knowledge_base_id": self.knowledge_base_id, "cursor": "", "limit": 20},
            )
        except Exception:
            return None
        items = (_response_data(result).get("info_list") or []) if isinstance(_response_data(result), dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("title") or item.get("kb_name") or "").strip()
            folder_id = str(item.get("folder_id") or item.get("media_id") or "").strip()
            if name == day and folder_id.startswith("folder_"):
                return folder_id
        return None

    async def _ima_api(self, api_path: str, body: dict[str, Any]) -> dict[str, Any]:
        raw = await self._run_text("node", str(self.skill_dir / "ima_api.cjs"), api_path, json.dumps(body, ensure_ascii=False))
        parsed = json.loads(raw or "{}")
        code = parsed.get("code")
        if code not in (0, "0", None):
            raise RuntimeError(f"IMA API failed for {api_path}: code={code} msg={parsed.get('msg')}")
        return parsed

    async def _run_json(self, *args: str) -> dict[str, Any]:
        raw = await self._run_text(*args)
        return json.loads(raw or "{}")

    async def _run_text(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", "replace").strip() or stdout.decode("utf-8", "replace").strip()
            raise RuntimeError(err[:1000])
        return stdout.decode("utf-8", "replace").strip()


def _render_markdown(
    *,
    generated_at: str,
    source: str,
    title: str,
    tenant_id: str | None,
    prompt: str | None,
    result_type: str | None,
    content_markdown: str | None,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    lines = [
        f"# {title or result_type or source or 'Hermes Output'}",
        "",
        f"- generated_at: {generated_at}",
        f"- source: {source or 'unknown'}",
        f"- result_type: {result_type or payload.get('result_type') or 'unknown'}",
    ]
    if tenant_id:
        lines.append(f"- tenant_id: {tenant_id}")
    if metadata:
        lines.append(f"- metadata: `{json.dumps(_redact(metadata), ensure_ascii=False, sort_keys=True, default=str)}`")
    if prompt:
        lines.extend(["", "## 用户输入", "", str(prompt).strip()])
    reply = content_markdown or str(payload.get("reply_text") or "").strip()
    if reply:
        lines.extend(["", "## 返回内容", "", reply])
    lines.extend(
        [
            "",
            "## 结构化记录",
            "",
            "```json",
            json.dumps(_redact(payload), ensure_ascii=False, indent=2, sort_keys=True, default=str),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if SENSITIVE_KEY_RE.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff._-]+", "-", str(value).strip())
    text = re.sub(r"-+", "-", text).strip("-._")
    return (text or "hermes")[:80]


def _response_data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def _credential_value(credential: dict[str, Any], *keys: str, default: str | None = None) -> str:
    for key in keys:
        value = credential.get(key)
        if value not in (None, ""):
            return str(value)
    if default is not None:
        return default
    raise RuntimeError(f"IMA COS credential missing {'/'.join(keys)}")

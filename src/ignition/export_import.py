"""Export/import IGNITION session data for backup and moving between machines."""

from __future__ import annotations

import gzip
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from ignition import __version__
from ignition.atomic_io import atomic_write_json, atomic_write_text, safe_read_json
from ignition import repo_identity as repo_identity_mod
from ignition import session as session_mod
from ignition.paths import exports_dir, receipt_dir, session_dir
from ignition.schema import CURRENT_SESSION_SCHEMA_VERSION, migrate_receipt, migrate_session
from ignition.utils import utc_now_iso

EXPORT_BUNDLE_VERSION = 1


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _session_in_days_window(data: dict[str, Any], days: int | None) -> bool:
    if days is None or days <= 0:
        return True
    st = _parse_iso(data.get("started_at"))
    if st is None:
        return True
    if st.tzinfo is None:
        st = st.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return st >= cutoff


def _max_activity_iso(d: dict[str, Any]) -> str:
    keys = (
        "stopped_at",
        "ended_at",
        "stale_closed_at",
        "started_at",
        "last_checkpoint_at",
        "last_resumed_at",
    )
    parts = [d.get(k) for k in keys if isinstance(d.get(k), str) and d.get(k)]
    return max(parts) if parts else ""


def _collect_receipt_rel_paths(repo_root: Path, cfg_receipt: str | None, sessions: list[dict[str, Any]]) -> dict[str, Path]:
    rdir = receipt_dir(repo_root, cfg_receipt)
    out: dict[str, Path] = {}
    for s in sessions:
        for key in ("receipt_json", "receipt_md"):
            p = s.get(key)
            if not p:
                continue
            pp = Path(p)
            try:
                if pp.is_file() and rdir in pp.parents:
                    rel = pp.relative_to(rdir)
                    out[str(rel).replace("\\", "/")] = pp
            except ValueError:
                continue
        link = s.get("linkage") or {}
        if not isinstance(link, dict):
            continue
        for lst_key in ("recommend_receipt_paths", "snapshot_receipt_paths"):
            lst = link.get(lst_key)
            if not isinstance(lst, list):
                continue
            for item in lst:
                pp = Path(str(item))
                try:
                    if pp.is_file() and rdir in pp.parents:
                        rel = pp.relative_to(rdir)
                        out[str(rel).replace("\\", "/")] = pp
                except ValueError:
                    continue
    return out


def build_export_bundle(
    repo_root: Path,
    cfg_session: str | None,
    cfg_receipt: str | None,
    *,
    all_repos: bool = False,
    days: int | None = None,
) -> dict[str, Any]:
    rr = str(repo_root.resolve())
    sessions_out: list[dict[str, Any]] = []
    for path in session_mod.iter_session_json_paths(repo_root, cfg_session):
        data = session_mod.load_session_soft(path)
        if data is None:
            continue
        if not all_repos and data.get("repo_root") and data["repo_root"] != rr:
            continue
        if not _session_in_days_window(data, days):
            continue
        sessions_out.append(migrate_session(dict(data)))

    receipts: dict[str, Any] = {}
    for rel, rpath in _collect_receipt_rel_paths(repo_root, cfg_receipt, sessions_out).items():
        raw = safe_read_json(rpath)
        if raw is None:
            continue
        receipts[rel] = migrate_receipt(raw)

    rid = repo_identity_mod.compute_repo_identity(repo_root)
    return {
        "export_schema_version": EXPORT_BUNDLE_VERSION,
        "tool_version": __version__,
        "record_schema_version": CURRENT_SESSION_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "repo_root": rr,
        "repo_identity": rid,
        "sessions": sessions_out,
        "receipts": receipts,
    }


def export_to_path(
    repo_root: Path,
    cfg_session: str | None,
    cfg_receipt: str | None,
    dest: Path,
    *,
    all_repos: bool = False,
    days: int | None = None,
    fmt: str = "json",
    compress: bool = False,
) -> Path:
    if fmt not in ("json", "jsonl", "markdown-bundle"):
        raise ValueError(f"Unsupported export format: {fmt}")

    bundle = build_export_bundle(
        repo_root,
        cfg_session,
        cfg_receipt,
        all_repos=all_repos,
        days=days,
    )
    exports_dir(repo_root).mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        text = json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"
        if compress:
            dest = dest.with_suffix(dest.suffix + ".gz") if not str(dest).endswith(".gz") else dest
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_bytes(gzip.compress(text.encode("utf-8")))
            tmp.replace(dest)
        else:
            atomic_write_text(dest, text)
        return dest

    if fmt == "jsonl":
        lines: list[str] = []
        meta = {k: v for k, v in bundle.items() if k not in ("sessions", "receipts")}
        lines.append(json.dumps({"type": "meta", **meta}, ensure_ascii=False))
        for s in bundle["sessions"]:
            lines.append(json.dumps({"type": "session", "data": s}, ensure_ascii=False))
        for rel, content in bundle["receipts"].items():
            lines.append(json.dumps({"type": "receipt", "relative": rel, "content": content}, ensure_ascii=False))
        text = "\n".join(lines) + "\n"
        if compress:
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_bytes(gzip.compress(text.encode("utf-8")))
            tmp.replace(dest)
        else:
            atomic_write_text(dest, text)
        return dest

    # markdown-bundle: zip with json under bundle/ plus .md copies where present
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "bundle.json",
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
        )
        for rel, rpath in _collect_receipt_rel_paths(repo_root, cfg_receipt, bundle["sessions"]).items():
            if rel.endswith(".md") and rpath.is_file():
                zf.writestr(f"markdown/{rel}", rpath.read_text(encoding="utf-8"))
    data = buf.getvalue()
    out_zip = dest if dest.suffix == ".zip" else dest.with_suffix(".zip")
    if compress:
        out_path = Path(str(out_zip) + ".gz")
        tmp = out_path.with_name(out_path.name + ".tmp")
        tmp.write_bytes(gzip.compress(data))
        tmp.replace(out_path)
        return out_path
    tmp = out_zip.with_name(out_zip.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(out_zip)
    return out_zip


def default_export_filename(fmt: str, compress: bool) -> str:
    safe = utc_now_iso().replace(":", "").replace("+00:00", "Z")[:20]
    if fmt == "markdown-bundle":
        ext = ".zip.gz" if compress else ".zip"
    elif fmt == "jsonl":
        ext = ".jsonl.gz" if compress else ".jsonl"
    else:
        ext = ".json.gz" if compress else ".json"
    return f"ignition-export-{safe}{ext}"


@dataclass
class ImportResult:
    sessions_imported: int
    sessions_skipped: int
    receipts_imported: int
    receipts_skipped: int
    warnings: list[str]


def import_bundle_path(
    repo_root: Path,
    cfg_session: str | None,
    cfg_receipt: str | None,
    bundle_path: Path,
) -> ImportResult:
    warnings: list[str] = []
    raw_bytes = bundle_path.read_bytes()
    name = bundle_path.name

    if name.endswith(".zip.gz"):
        try:
            raw_bytes = gzip.decompress(raw_bytes)
        except OSError:
            return ImportResult(0, 0, 0, 0, ["Could not decompress .zip.gz export."])
        with zipfile.ZipFile(BytesIO(raw_bytes), "r") as zf:
            if "bundle.json" not in zf.namelist():
                return ImportResult(0, 0, 0, 0, ["Zip bundle missing bundle.json"])
            raw_text = zf.read("bundle.json").decode("utf-8")
    elif name.endswith(".zip"):
        with zipfile.ZipFile(BytesIO(raw_bytes), "r") as zf:
            if "bundle.json" not in zf.namelist():
                return ImportResult(0, 0, 0, 0, ["Zip bundle missing bundle.json"])
            raw_text = zf.read("bundle.json").decode("utf-8")
    else:
        if name.endswith(".gz"):
            try:
                raw_bytes = gzip.decompress(raw_bytes)
            except OSError:
                warnings.append("gzip decompress failed; trying raw bytes as UTF-8.")
        try:
            raw_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return ImportResult(0, 0, 0, 0, ["Could not decode export file as UTF-8."])

    bundle: dict[str, Any] | None = None
    if raw_text.lstrip().startswith("{"):
        try:
            bundle = json.loads(raw_text)
        except json.JSONDecodeError:
            bundle = None
    if bundle is None:
        # jsonl: first line meta + body
        lines = [ln for ln in raw_text.splitlines() if ln.strip()]
        sessions: list[dict[str, Any]] = []
        receipts: dict[str, Any] = {}
        meta: dict[str, Any] = {}
        for i, ln in enumerate(lines):
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if i == 0 and obj.get("type") == "meta":
                meta = obj
                continue
            if obj.get("type") == "session":
                sessions.append(obj.get("data") or {})
            elif obj.get("type") == "receipt":
                rel = obj.get("relative")
                if rel:
                    receipts[str(rel)] = obj.get("content") or {}
        if meta or sessions:
            bundle = {
                "export_schema_version": meta.get("export_schema_version", EXPORT_BUNDLE_VERSION),
                "tool_version": meta.get("tool_version"),
                "sessions": sessions,
                "receipts": receipts,
            }

    if not bundle or "sessions" not in bundle:
        return ImportResult(0, 0, 0, 0, ["Unrecognized export format (need JSON bundle or jsonl)."])

    sdir = session_dir(repo_root, cfg_session)
    rdir = receipt_dir(repo_root, cfg_receipt)
    sdir.mkdir(parents=True, exist_ok=True)
    rdir.mkdir(parents=True, exist_ok=True)

    si = sk = ri = rk = 0
    for sess in bundle.get("sessions") or []:
        if not isinstance(sess, dict):
            continue
        m = migrate_session(dict(sess))
        sid = m.get("session_id") or ""
        if not sid:
            warnings.append("Skipped session with no session_id")
            sk += 1
            continue
        dest = session_mod.session_file_path(repo_root, cfg_session, sid)
        incoming_ts = _max_activity_iso(m)
        if dest.is_file():
            local = session_mod.load_session_soft(dest)
            if local is not None:
                local_ts = _max_activity_iso(local)
                if local_ts and incoming_ts and local_ts >= incoming_ts:
                    sk += 1
                    continue
        atomic_write_json(dest, m)
        si += 1

    for rel, content in (bundle.get("receipts") or {}).items():
        if not isinstance(content, dict):
            continue
        rd = migrate_receipt(dict(content))
        rpath = rdir / rel
        incoming_ts = _max_activity_iso(rd)
        if rpath.is_file():
            prev = safe_read_json(rpath)
            if prev:
                prev_m = migrate_receipt(prev)
                pt = _max_activity_iso(prev_m)
                if pt and incoming_ts and pt >= incoming_ts:
                    rk += 1
                    continue
        rpath.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(rpath, rd)
        ri += 1

    return ImportResult(si, sk, ri, rk, warnings)


def run_prune(repo_root: Path, *, dry_run: bool = False) -> dict[str, int]:
    """Remove only obvious disposable artifacts (conservative)."""
    counts = {"tmp_removed": 0, "empty_removed": 0}
    idata = repo_root / "ignition_data"
    exp = exports_dir(repo_root)
    if idata.is_dir():
        for p in idata.rglob("*.tmp"):
            if not p.is_file():
                continue
            counts["tmp_removed"] += 1
            if not dry_run:
                try:
                    p.unlink()
                except OSError:
                    pass
    if exp.is_dir():
        for p in exp.rglob("*"):
            if not p.is_file():
                continue
            try:
                if p.stat().st_size == 0 and p.suffix in (".json", ".jsonl", ".md", ".zip"):
                    counts["empty_removed"] += 1
                    if not dry_run:
                        try:
                            p.unlink()
                        except OSError:
                            pass
            except OSError:
                continue
    return counts

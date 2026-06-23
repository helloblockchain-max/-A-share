from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
WEB_DIR = ROOT_DIR / "web"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ashare_indicator_monitor.service import DashboardService  # noqa: E402


def resolve_output_dir(raw_output: str) -> Path:
    """解析并校验输出目录，避免误删项目外文件。"""

    output = Path(raw_output)
    if not output.is_absolute():
        output = ROOT_DIR / output
    output = output.resolve()
    if output == ROOT_DIR or not output.is_relative_to(ROOT_DIR):
        raise ValueError(f"输出目录必须位于项目目录内，当前为：{output}")
    return output


def prepare_output_dir(output_dir: Path) -> None:
    """重建静态站点输出目录。"""

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "static").mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """用 UTF-8 写出网页读取的数据快照。"""

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_static_site(output_dir: Path, force: bool = True) -> dict[str, Any]:
    """生成 GitHub Pages 可直接托管的静态网页产物。"""

    service = DashboardService()
    payload = service.get_dashboard(force=force)
    payload["deployment"] = {
        "mode": "github_pages_static",
        "schedule": "Asia/Shanghai 08:45, 09:15",
        "note": "该 JSON 由 GitHub Actions 定时生成，网页端只读取静态快照。",
    }

    prepare_output_dir(output_dir)
    shutil.copy2(WEB_DIR / "index.html", output_dir / "index.html")
    shutil.copy2(WEB_DIR / "style.css", output_dir / "static" / "style.css")
    shutil.copy2(WEB_DIR / "app.js", output_dir / "static" / "app.js")
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    write_json(output_dir / "dashboard.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 A股指标检测 GitHub Pages 静态网页")
    parser.add_argument("--output", default="dist", help="静态站点输出目录，默认 dist")
    parser.add_argument("--no-force", action="store_true", help="不强制刷新底层数据，仅用于本地快速调试")
    args = parser.parse_args()

    output_dir = resolve_output_dir(args.output)
    payload = build_static_site(output_dir=output_dir, force=not args.no_force)
    summary = {
        "output": str(output_dir),
        "score": payload.get("total_score"),
        "status": payload.get("status"),
        "as_of": payload.get("as_of"),
        "generated_at": payload.get("generated_at"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

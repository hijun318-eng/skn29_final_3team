from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
UI_PATH = Path(__file__).with_name("local_console.html")
NO_SHOW_DIR = Path(__file__).with_name("reservation_no_show")
DEMAND_DIR = Path(__file__).with_name("room_demand_forecast")
MANUALS_DIR = Path(os.getenv("RAG_MANUALS_DIR", ROOT / "data" / "rag" / "manuals")).resolve()
MANUAL_ID_PATTERN = re.compile(r"SOP-[A-Z]+-\d+")
sys.path[:0] = [str(NO_SHOW_DIR), str(DEMAND_DIR)]

from no_show_ml.config import ProjectConfig  # noqa: E402
from no_show_ml.service import NoShowToolService, ToolRequest  # noqa: E402
from room_demand_ml.service import ForecastRequest, RoomDemandForecastService  # noqa: E402


class LocalToolConsole:
    """로컬 저장 모델과 pgvector 검색을 같은 HTTP 경계에서 실행한다."""

    def __init__(self) -> None:
        self.no_show_config = ProjectConfig.default()
        self.no_show = NoShowToolService(self.no_show_config)
        self.demand = RoomDemandForecastService()

    def examples(self) -> dict[str, object]:
        inference = self.no_show.repository._frame.head(20)
        reservations = [
            {
                "reservation_id": str(row.reservation_id),
                "feature_as_of": self._seoul_timestamp(row.prediction_cutoff_at),
            }
            for row in inference.itertuples(index=False)
        ]
        demand_row = self.demand.forecast.iloc[0]
        return {
            "reservations": reservations,
            "demand": {
                "property_id": str(demand_row["property_id"]),
                "feature_as_of": self.demand.metadata["as_of_date"],
            },
            "rag_questions": [
                "객실 소음 민원 대응 절차를 알려줘",
                "체크인 전에 객실 준비 상태를 어떻게 확인하나요?",
                "직원 응대 불만이 접수되면 어떻게 처리하나요?",
            ],
        }

    def health(self) -> dict[str, object]:
        components = {
            "rag_runtime": (ROOT / ".venv" / "Scripts" / "python.exe").is_file()
            and bool(os.getenv("RAG_DATABASE_URL")),
            "no_show_model": self.no_show.model_path.is_file(),
            "demand_model": (self.demand.artifact_dir / "room_demand_model.joblib").is_file(),
        }
        return {
            "status": "READY" if all(components.values()) else "NOT_READY",
            "mode": "LOCAL_SYNTHETIC_POC",
            "components": components,
        }

    def search_manuals(self, query: str = "") -> dict[str, object]:
        normalized = query.strip().casefold()
        documents = []
        for path in sorted(MANUALS_DIR.glob("*.pdf")):
            match = MANUAL_ID_PATTERN.search(path.name)
            if not match:
                continue
            manual_id = match.group()
            title = self._manual_title(path, manual_id)
            if normalized and normalized not in f"{manual_id} {title} {path.name}".casefold():
                continue
            documents.append(
                {
                    "manual_id": manual_id,
                    "title": title,
                    "version": self._manual_version(path),
                    "url": f"/api/manuals/{manual_id}",
                }
            )
        return {"query": query, "count": len(documents), "documents": documents[:50]}

    def manual_pdf(self, manual_id: str) -> Path:
        if not MANUAL_ID_PATTERN.fullmatch(manual_id):
            raise LookupError("매뉴얼을 찾을 수 없습니다.")
        matches = [path for path in MANUALS_DIR.glob(f"*{manual_id}_*.pdf")]
        if len(matches) != 1 or MANUALS_DIR not in matches[0].resolve().parents:
            raise LookupError("매뉴얼을 찾을 수 없습니다.")
        return matches[0]

    @staticmethod
    def _manual_title(path: Path, manual_id: str) -> str:
        title = path.stem.split(f"{manual_id}_", 1)[-1]
        return re.sub(r"_업무숙지본_v\d+(?:\.\d+)*$", "", title).replace("_", " ")

    @staticmethod
    def _manual_version(path: Path) -> str:
        match = re.search(r"_v(\d+(?:\.\d+)*)\.pdf$", path.name, re.IGNORECASE)
        return match.group(1) if match else "UNKNOWN"

    def search_rag(self, body: dict[str, object]) -> dict[str, object]:
        query = self._required_text(body, "query", 2, 500)
        role = str(body.get("role", "MANAGER")).strip().upper()
        if role not in {"STAFF", "MANAGER", "SYSTEM_ADMIN"}:
            raise ValueError("role은 STAFF, MANAGER, SYSTEM_ADMIN 중 하나여야 합니다.")
        python = ROOT / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            raise RuntimeError("RAG 가상환경을 찾을 수 없습니다.")
        if not os.getenv("RAG_DATABASE_URL"):
            raise RuntimeError("RAG_DATABASE_URL이 설정되지 않았습니다.")
        command = [
            str(python), "-m", "src.rag.vector_cli", "--root", str(ROOT),
            "search", query, "--role", role, "--top-k", "3",
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError("RAG 검색 실행에 실패했습니다. 서버 로그를 확인하세요.")
        return json.loads(completed.stdout)

    def predict_no_show(self, body: dict[str, object]) -> dict[str, object]:
        request = ToolRequest(
            reservation_id=self._required_text(body, "reservation_id", 1, 100),
            feature_as_of=self._required_text(body, "feature_as_of", 10, 50),
            feature_set_version=self.no_show_config.feature_set_version,
            input_schema_version=self.no_show.input_schema_version,
        )
        return self.no_show.execute(request)

    def predict_demand(self, body: dict[str, object]) -> dict[str, object]:
        request = ForecastRequest(
            property_id=self._required_text(body, "property_id", 1, 100),
            feature_as_of=self._required_text(body, "feature_as_of", 10, 10),
            feature_set_version=self.demand.feature_set_version,
            input_schema_version=self.demand.input_schema_version,
        )
        return self.demand.execute(request)

    @staticmethod
    def _required_text(
        body: dict[str, object], name: str, minimum: int, maximum: int
    ) -> str:
        value = body.get(name)
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
            raise ValueError(f"{name} 입력 길이가 올바르지 않습니다.")
        return value.strip()

    @staticmethod
    def _seoul_timestamp(value: object) -> str:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("Asia/Seoul")
        else:
            timestamp = timestamp.tz_convert("Asia/Seoul")
        return timestamp.isoformat()


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "AnswerviceLocalConsole/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send(UI_PATH.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/examples":
            self._json(200, self.server.console.examples())
        elif path == "/api/health":
            self._json(200, self.server.console.health())
        elif path == "/api/manuals":
            query = parse_qs(parsed.query).get("query", [""])[0]
            self._json(200, self.server.console.search_manuals(query))
        elif path.startswith("/api/manuals/"):
            try:
                pdf = self.server.console.manual_pdf(path.rsplit("/", 1)[-1])
                self._send(pdf.read_bytes(), "application/pdf")
            except LookupError as error:
                self._json(404, {"error": "DOCUMENT_NOT_FOUND", "message": str(error)})
        else:
            self._json(404, {"error": "NOT_FOUND"})

    def do_POST(self) -> None:  # noqa: N802
        routes = {
            "/api/rag": self.server.console.search_rag,
            "/api/no-show": self.server.console.predict_no_show,
            "/api/demand": self.server.console.predict_demand,
        }
        action = routes.get(urlparse(self.path).path)
        if action is None:
            self._json(404, {"error": "NOT_FOUND"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32_768:
                raise ValueError("요청 크기가 올바르지 않습니다.")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("JSON 객체만 허용됩니다.")
            self._json(200, action(body))
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"error": "INVALID_INPUT", "message": str(error)})
        except subprocess.TimeoutExpired:
            self._json(504, {"error": "TIMEOUT", "message": "RAG 검색이 30초를 초과했습니다."})
        except Exception as error:
            print(f"{type(error).__name__}: {error}", file=sys.stderr)
            self._json(500, {"error": "EXECUTION_FAILED", "message": str(error)})

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def _json(self, status: int, payload: object) -> None:
        self._send(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def _send(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(data)


class ConsoleServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], console: LocalToolConsole):
        super().__init__(address, ConsoleHandler)
        self.console = console


def main() -> None:
    parser = argparse.ArgumentParser(description="Answervice 로컬 RAG·ML 질문 화면")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ConsoleServer(("127.0.0.1", args.port), LocalToolConsole())
    url = f"http://127.0.0.1:{args.port}"
    print(f"Answervice 로컬 질문 화면: {url}")
    print("종료: Ctrl+C")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

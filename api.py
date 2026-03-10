import sys
import json
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from src.query.engine import query_knowledge_base


class QueryHandler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path != "/query":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        question = body.get("question", "").strip()

        if not question:
            self._json(400, {"error": "question is required"})
            return

        try:
            result = query_knowledge_base(question)
            source = ""
            if "Source:" in result:
                for line in result.split("\n"):
                    if line.strip().startswith("Source:"):
                        source = line.replace("Source:", "").strip()
                        break
            self._json(200, {"answer": result, "source": source})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[API] {format % args}")


if __name__ == "__main__":
    server = HTTPServer(("localhost", 8000), QueryHandler)
    print("[API] Running on http://localhost:8000")
    print("[API] Press Ctrl+C to stop.")
    server.serve_forever()

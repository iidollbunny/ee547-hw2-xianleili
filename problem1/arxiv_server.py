#!/usr/bin/env python3
import sys
import os
import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# Load data from JSON files at startup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "sample_data")

PAPERS_FILE = os.path.join(DATA_DIR, "papers.json")
CORPUS_FILE = os.path.join(DATA_DIR, "corpus_analysis.json")

try:
    with open(PAPERS_FILE, "r", encoding="utf-8") as f:
        papers_data = json.load(f)
except Exception:
    papers_data = []

try:
    with open(CORPUS_FILE, "r", encoding="utf-8") as f:
        corpus_data = json.load(f)
except Exception:
    corpus_data = {}

# Build dictionary for quick lookup by arxiv_id
papers_index = {p.get("arxiv_id"): p for p in papers_data}


class ArxivRequestHandler(BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        # Send JSON response with headers
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _send_error(self, status, message):
        # Send error message as JSON
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode("utf-8"))

    def do_GET(self):
        # Handle GET requests for all endpoints
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/papers":
                # Return list of all papers (summary only)
                result = [
                    {
                        "arxiv_id": p.get("arxiv_id"),
                        "title": p.get("title"),
                        "authors": p.get("authors", []),
                        "categories": p.get("categories", []),
                    }
                    for p in papers_data
                ]
                self._send_json(result)

            elif path.startswith("/papers/"):
                # Return full paper details
                arxiv_id = path.split("/")[-1]
                if arxiv_id in papers_index:
                    self._send_json(papers_index[arxiv_id])
                else:
                    self._send_error(404, "Paper ID not found")

            elif path == "/search":
                # Search papers by title and abstract
                if "q" not in query:
                    self._send_error(400, "Missing search query")
                    return

                q = query["q"][0].lower().strip()
                if not q:
                    self._send_error(400, "Empty search query")
                    return

                terms = q.split()
                results = []

                for p in papers_data:
                    text_title = p.get("title", "").lower()
                    text_abs = p.get("abstract", "").lower()

                    matches_in = []
                    score = 0

                    for term in terms:
                        count_t = text_title.count(term)
                        count_a = text_abs.count(term)
                        if count_t > 0:
                            matches_in.append("title")
                            score += count_t
                        if count_a > 0:
                            matches_in.append("abstract")
                            score += count_a

                    if score > 0:
                        results.append({
                            "arxiv_id": p.get("arxiv_id"),
                            "title": p.get("title"),
                            "match_score": score,
                            "matches_in": list(set(matches_in))
                        })

                self._send_json({"query": q, "results": results})

            elif path == "/stats":
                # Return global corpus statistics
                self._send_json(corpus_data)

            else:
                # Invalid endpoint
                self._send_error(404, "Invalid endpoint")

        except Exception as e:
            # Internal server error
            self._send_error(500, f"Server error: {str(e)}")


def run(port=8080):
    # Start HTTP server on given port
    server = HTTPServer(("", port), ArxivRequestHandler)
    print(f"[{datetime.now().isoformat()}] ArXiv server running on port {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down server...")
        server.server_close()


if __name__ == "__main__":
    # Accept port from command line or use default
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("Invalid port, must be integer")
            sys.exit(1)
    else:
        port = 8080

    run(port)

"""Deterministic OpenAI-compatible HTTP fixture, not a learned personalization model."""
import json
import re
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def respond(messages):
    system = "\n".join(str(m.get("content", "")) for m in messages if m["role"] == "system")
    match = re.search(r'PERSONA_JSON=(\{[^\n]+\})', system)
    if not match:
        raise ValueError("Persona missing from Hermes model request")
    persona = json.loads(match[1])
    start = max(i for i, m in enumerate(messages) if m["role"] == "user")
    turns = messages[start:]
    query = str(messages[start]["content"])
    query = re.sub(r"<memory-context>.*?</memory-context>", "", query, flags=re.DOTALL).strip()
    results = [json.loads(m["content"]) for m in turns if m["role"] == "tool"]
    if not results:
        calls = [("persona_recall", {"query": query})]
    elif len(results) == 1:
        confirmed = [r for r in results[0]["result"] if r["confirmed"]]
        focus = next((r["response"].split("focus=")[1].split()[0]
                      for r in confirmed if "focus=" in r["response"]), "delivery")
        calls = [("mock_rag", {"query": "프로젝트 계획 " + focus, "tag": focus}),
                 ("mock_environment", {"project": persona["project"]})]
    else:
        documents, environment = results[-2]["result"], results[-1]["result"]
        evidence = " ".join(f'[{d["id"]}] {d["text"]}' for d in documents)
        summary = f'{environment["project"]}: {environment["constraint"]}. {evidence}'
        if persona["format"] == "table":
            text = f'| 프로젝트 | 권고 및 근거 |\n|---|---|\n| {environment["project"]} | {summary} |'
        elif persona["format"] == "bullets":
            text = "- " + summary
        else:
            text = "단계별 안내: 먼저 프로젝트 환경을 확인하세요. " + summary
        return {"role": "assistant", "content": text}, "stop"
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"call-{len(results)}-{i}", "type": "function",
         "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
        for i, (name, args) in enumerate(calls)]}, "tool_calls"


@contextmanager
def mock_endpoint(responder=respond):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if not self.path.endswith("/chat/completions") or "messages" not in request:
                # Hermes can probe auxiliary endpoints; this fixture only serves Chat Completions.
                self.send_error(400, "Mock endpoint supports Chat Completions only")
                return
            message, finish = responder(request["messages"])
            base = {"id": "chatcmpl-prototype", "created": 1, "model": "persona-mock"}
            if request.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                delta = dict(message)
                if "tool_calls" in delta:
                    delta["tool_calls"] = [dict(tc, index=i) for i, tc in enumerate(delta["tool_calls"])]
                for value, reason in [(delta, None), ({}, finish)]:
                    chunk = dict(base, object="chat.completion.chunk",
                                 choices=[{"index": 0, "delta": value, "finish_reason": reason}])
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                body = json.dumps(dict(base, object="chat.completion", choices=[
                    {"index": 0, "message": message, "finish_reason": finish}],
                    usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

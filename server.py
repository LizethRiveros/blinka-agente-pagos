"""Servidor local: python server.py  ->  http://localhost:8765"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from blinka import runner
from blinka.engine import norm_name

ROOT = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()
STATE = {"rules": runner.load_rules(), "batch": None}


def validate_rules(r):
    for k in ("max_per_payment_usd", "approval_threshold_usd", "period_budget_usd",
              "amount_tolerance_pct", "max_days_overdue"):
        if not isinstance(r.get(k), (int, float)) or r[k] < 0:
            raise ValueError("%s debe ser un número ≥ 0" % k)
    names = set()
    for b in r.get("allowed_beneficiaries", []):
        if not b.get("name") or b.get("currency") not in r["fx_to_usd"] or not b.get("agreed_amount", 0) > 0:
            raise ValueError("beneficiario inválido: %s" % b.get("name"))
        if norm_name(b["name"]) in names:
            raise ValueError("beneficiario repetido: %s" % b["name"])
        names.add(norm_name(b["name"]))


def snapshot():
    b = STATE["batch"]
    return {"rules": STATE["rules"], "results": b["results"] if b else [],
            "summary": runner.summarize(b, STATE["rules"]) if b else None}


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

    def do_GET(self):
        if self.path == "/":
            with open(os.path.join(ROOT, "ui.html"), "rb") as f:
                return self.send(200, f.read(), "text/html")
        if self.path == "/api/state":
            with LOCK:
                return self.send(200, snapshot())
        if self.path == "/api/export.csv":
            with LOCK:
                if not STATE["batch"]:
                    return self.send(409, {"error": "primero procesa las facturas"})
                body = ("\ufeff" + runner.export_csv(STATE["batch"])).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="decisiones.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if self.path.startswith("/api/invoice/"):
            name = os.path.basename(self.path[len("/api/invoice/"):])
            ctype = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg"}.get(os.path.splitext(name)[1].lower(), "text/plain")
            try:
                with open(os.path.join(runner.DATA, "invoices", name), "rb") as f:
                    return self.send(200, f.read(), ctype)
            except OSError:
                return self.send(404, {"error": "no existe"})
        self.send(404, {"error": "no existe"})

    def do_POST(self):
        try:
            data = self.body()
            with LOCK:
                if self.path == "/api/rules":
                    validate_rules(data)
                    STATE["rules"], STATE["batch"] = data, None
                    with open(os.path.join(runner.DATA, "rules.json"), "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                elif self.path == "/api/run":
                    STATE["batch"] = runner.run_batch(STATE["rules"])
                elif self.path == "/api/review" and STATE["batch"]:
                    runner.review(STATE["batch"], data["file"], data["action"])
                else:
                    return self.send(404, {"error": "no existe"})
                return self.send(200, snapshot())
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            self.send(400, {"error": str(e)})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    print("Blinka agente de pagos en http://localhost:%d" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

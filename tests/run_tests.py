"""Edge-case tests for the plugin's scripts. Run: python run_tests.py"""
import base64, http.server, io, json, os, shutil, subprocess, sys, tempfile, threading

S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "sentinelqa", "skills", "qa-functional", "scripts")
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
ENV = dict(os.environ, PYTHONIOENCODING="cp1252")   # simulate a default Windows console
results = []


def run(script, *args, cwd=None, env=ENV):
    r = subprocess.run([sys.executable, os.path.join(S, script), *args], cwd=cwd, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "\n     " + detail[-600:]))


def w(path, text, bom=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="").write(text)


def png(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(PNG)


root = tempfile.mkdtemp(prefix="sqa-tests-")
try:
    # ---------------- report-html ----------------
    c = os.path.join(root, "qa", "ABC-1")
    for n in ("04-evidence/a.png", "04 evidence/b c.png", "04-evidence/c d.png", "04-evidence/e.png",
              "04-evidence/f.png", "04-evidence/g.png"):
        png(os.path.join(c, n))
    w(os.path.join(c, "05-report.md"),
      "# Title here\n\n![a](04-evidence/a.png)\n\n![b](<04 evidence/b c.png>)\n\n"
      "Inline ![c](04-evidence/c%20d.png) in text\n\n![e](04-evidence/e.png \"a title\")\n\n"
      "<img src=\"04-evidence/f.png\">\n\n- step 1\n- Evidence: `g.png`\n\n| a | b |\n|---|---|\n| x | y |\n", bom=True)
    rc, out = run("report-html.py", os.path.join(c, "05-report.md"))
    doc = io.open(os.path.join(c, "ABC-1-QA-Report.html"), encoding="utf-8").read() if rc == 0 else ""
    check("html: all 6 image forms embedded, exit 0", rc == 0 and doc.count("data:image/png;base64") == 6, out)
    check("html: BOM file keeps its <h1>", "<h1>Title here</h1>" in doc, doc[:400])
    check("html: charset meta first in head", doc.startswith('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'))
    check("html: no non-data <img>", 'src="04' not in doc)
    w(os.path.join(c, "bad.md"), "# T\n\n![x](04-evidence/missing.png)\n")
    rc, out = run("report-html.py", os.path.join(c, "bad.md"), "--name", "bad")
    check("html: missing image -> exit 1", rc == 1 and "image not found" in out, out)
    w(os.path.join(c, "bad2.md"), "# T\n\n![x](04-evidence/a.png\n")      # broken syntax
    rc, out = run("report-html.py", os.path.join(c, "bad2.md"), "--name", "bad2")
    check("html: broken image syntax -> exit 1", rc == 1, out)

    # ---------------- case-file-audit ----------------
    def case(name, intake, decisions, evidence=True, report=True):
        d = os.path.join(root, "cases", name)
        w(os.path.join(d, "00-intake.yml"), intake)
        w(os.path.join(d, "01-requirement.md"), "rules")
        w(os.path.join(d, "02-plan.md"), "plan")
        w(os.path.join(d, "03-pass1.md"), "pass1")
        if report:
            w(os.path.join(d, "05-report.md"), "report, no bugs")
        w(os.path.join(d, "06-decisions.md"), decisions)
        if evidence:
            for k in range(3):
                png(os.path.join(d, "04-evidence", "e%d.png" % k))
        return d

    good_intake = ("run_context:\n  deployed_site: \"http://qa.example\"\n  build_deployed: \"2.1.0\"\n"
                   "  build_confirmed_how: \"GET /version plus a negative control\"\n  test_account: \"shopper\"\n"
                   "capability_level: 3\n")
    gate = lambda g, outcome, extra="": ("\n## Gate %s\n### Round 1 - 2026-11-08 10:00 - %s\n- **Reviewer:** Tester\n%s"
                                         % (g, outcome, extra))
    tmpl = io.open(os.path.join(S, "..", "templates", "decisions-log.md"), encoding="utf-8").read()

    d = case("tmpl", good_intake, tmpl)
    rc, out = run("case-file-audit.py", d, "--pre-s3")
    check("audit: unfilled decisions template does NOT pass", rc == 1 and "C4" in out, out)

    d = case("rejB", good_intake, gate("A", "APPROVED") + gate("B", "REJECTED"))
    rc, out = run("case-file-audit.py", d, "--pre-s3")
    check("audit: Gate B REJECTED blocks execution", rc == 1 and "not APPROVED" in out, out)

    d = case("appendB", good_intake, gate("A", "APPROVED") + "\n## Gate B\nAwaiting decision.\n" + gate("B", "APPROVED"))
    rc, out = run("case-file-audit.py", d, "--pre-s3")
    check("audit: awaiting entry then appended APPROVED passes", rc == 0, out)

    d = case("rejthenapp", good_intake, gate("A", "APPROVED") + gate("B", "REJECTED") + gate("B", "APPROVED"))
    rc, out = run("case-file-audit.py", d, "--pre-s3")
    check("audit: REJECTED then later APPROVED passes", rc == 0, out)

    d = case("notadefect", good_intake, gate("A", "APPROVED") + gate("B", "APPROVED") + gate("C", "NOT A DEFECT"))
    rc, out = run("case-file-audit.py", d)
    check("audit: Gate C 'NOT A DEFECT' passes", rc == 0, out)

    d = case("nogatec", good_intake, gate("A", "APPROVED") + gate("B", "APPROVED") + "\n## Gate C\nawaiting\n")
    rc, out = run("case-file-audit.py", d)
    check("audit: Gate C with no decision still fails", rc == 1 and "Gate C" in out, out)

    lvl2 = good_intake.replace("capability_level: 3", "capability_level: 2")
    d = case("level2", lvl2, gate("A", "APPROVED") + gate("B", "APPROVED") + gate("C", "NOT A DEFECT"), evidence=False)
    rc, out = run("case-file-audit.py", d)
    check("audit: Level-2 run without evidence passes (warning)", rc == 0 and "warn C2" in out, out)

    d = case("level3noev", good_intake, gate("A", "APPROVED") + gate("B", "APPROVED") + gate("C", "NOT A DEFECT"), evidence=False)
    rc, out = run("case-file-audit.py", d)
    check("audit: Level-3 run without evidence still fails", rc == 1 and "C2" in out, out)

    ph = good_intake.replace("GET /version plus a negative control", "<footer / build endpoint / fingerprint — say which>")
    d = case("placeholder", ph, gate("A", "APPROVED") + gate("B", "APPROVED"))
    rc, out = run("case-file-audit.py", d, "--pre-s3")
    check("audit: em-dash placeholder in intake is caught", rc == 1 and "build_confirmed_how" in out, out)

    d = case("কেস-১", good_intake, gate("A", "APPROVED") + gate("B", "APPROVED"))   # Bangla folder name
    rc, out = run("case-file-audit.py", d, "--pre-s3")
    check("audit: non-English folder name, cp1252 console, no crash", rc == 0 and "Traceback" not in out, out)

    # ---------------- report-audit (screenshot forms + no-execution) ----------------
    def rep(body):
        d = os.path.join(root, "ra", str(abs(hash(body))))
        png(os.path.join(d, "04-evidence", "TC-01.png"))
        w(os.path.join(d, "r.md"), body)
        return run("report-audit.py", os.path.join(d, "r.md"), os.path.join(d, "04-evidence"))

    case_body = ("\n### TC-01 · thing\n\n**Steps to reproduce**:\n\n1. Do x\n\n**Expected:** y\n**Actual:** y\n"
                 "**Evidence:** %s\n\n## 9b. Evidence index\n\n| File | Shows |\n|---|---|\n| %s | x |\n")
    rc, out = rep("# R" + case_body % ("![TC-01](04-evidence/TC-01.png)", "TC-01.png"))
    check("report-audit: Markdown image link counts as the screenshot", "R9b-i" not in out and "never referenced: TC-01.png" not in out, out)
    rc, out = rep("# R" + case_body.replace("## 9b. Evidence index", "### 9b. Evidence index") % ("`TC-01.png`", "`TC-01.png`"))
    check("report-audit: the template heading '9b. Evidence index' is recognised", "no Evidence index" not in out, out)
    rc, out = rep("# R" + case_body.replace("## 9b. Evidence index", "## 9b. Evidence") % ("`TC-01.png`", "`TC-01.png`"))
    check("report-audit: a report with no evidence index still fails", "no Evidence index" in out, out)
    rc, out = rep("# R" + case_body % ("`TC-01.png`", "`TC-01.png`"))
    check("report-audit: backticked name counts as the screenshot", "R9b-i" not in out, out)
    rc, out = rep("# R\n\nNo execution evidence — analysis only.\n\n### TC-01 · thing\n\n**Steps attempted**:\n\n1. none\n\n"
                  "**Expected:** y\n**Actual:** Not Executed - blocked by no environment\n**Evidence:** none\n")
    check("report-audit: 'No execution evidence' run is not failed for missing screenshots", "has NO screenshot" not in out and "NO screenshot at all" not in out, out)
    # ---------------- report-audit R9g: a case heading is one plain sentence ----------------
    good = "TC-01 · Applying coupon SAVE10 to a $100.00 order reduces the total to $90.00 — PASS"
    def r9g(heading):
        return rep("# R" + case_body.replace("TC-01 · thing", heading) % ("`TC-01.png`", "`TC-01.png`"))[1]
    check("report-audit R9g: a label heading fails", "R9g" in r9g("TC-01 · thing") and "is a label" in r9g("TC-01 · thing"), r9g("TC-01 · thing"))
    check("report-audit R9g: a one-sentence heading passes", "R9g" not in r9g(good), r9g(good))
    q = "TC-01 · Does coupon SAVE10 reduce the total of a $100.00 order to $90.00? — PASS"
    check("report-audit R9g: a question heading fails", "question/arrow form" in r9g(q), r9g(q))
    a = "TC-01 · Coupon SAVE10 applied to a $100.00 order -> total becomes $90.00 — PASS"
    check("report-audit R9g: an arrow heading fails", "question/arrow form" in r9g(a), r9g(a))

    # ---------------- jira-attachments (unicode name over cp1252 console) ----------------
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path.startswith("/rest/api/3/issue/ABC-1"):
                b = json.dumps({"fields": {"attachment": [{"filename": "résumé → ফাইল.sql",
                                                           "size": 2, "mimeType": "text/plain",
                                                           "content": "http://127.0.0.1:%d/f" % srv.server_port}]}}).encode()
            else:
                b = b"ok"
            self.send_response(200); self.end_headers(); self.wfile.write(b)
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(ENV, JIRA_EMAIL="a@b.c", JIRA_API_TOKEN="t0ken")
    rc, out = run("jira-attachments.py", "ABC-1", "--site", "http://127.0.0.1:%d" % srv.server_port,
                  "--out", os.path.join(root, "att"), env=env)
    check("jira-attachments: unicode attachment name, cp1252 console, no crash", rc == 0 and "Traceback" not in out, out)
    check("jira-attachments: token never printed", "t0ken" not in out)
    srv.shutdown()
finally:
    shutil.rmtree(root, ignore_errors=True)

bad = [n for n, ok in results if not ok]
print("\n%d/%d passed" % (len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)

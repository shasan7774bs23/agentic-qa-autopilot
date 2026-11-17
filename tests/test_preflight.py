"""Tests for the start-of-run check (match situations A-E and `preflight`). Temp SENTINELQA_HOME only."""
import http.server, io, json, os, shutil, subprocess, sys, tempfile, threading

S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "sentinelqa", "skills", "qa-functional", "scripts", "sentinelqa-setup.py")
root = tempfile.mkdtemp(prefix="sqa-pre-")
SECRET = "Sup3r-S3cret-Value!"
ENV = dict(os.environ, SENTINELQA_HOME=os.path.join(root, "home"), SENTINELQA_SETTINGS_FILE=os.path.join(root, "s.json"),
           QA_SHOP_USER="shopper@example.com", QA_SHOP_PASS=SECRET)
ENV.pop("QA_MISSING_PASS", None)
results = []
hits = []


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append((self.server.server_port, self.path))
        self.send_response(200 if self.path != "/broken" else 503)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def serve():
    s = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


qa, prod = serve(), serve()


def run(*args):
    r = subprocess.run([sys.executable, S, *args], env=ENV, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def js(*args):
    rc, out = run(*args)
    try:
        return rc, json.loads(out), out
    except ValueError:
        return rc, {}, out


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "\n     " + str(detail)[-900:]))


shop = os.path.join(root, "work", "shop")
os.makedirs(os.path.join(shop, "src"))
other = os.path.join(root, "work", "other")
os.makedirs(other)
creds = os.path.join(root, "private", "test-accounts.json")
os.makedirs(os.path.dirname(creds))
io.open(creds, "w", encoding="utf-8").write(json.dumps({"admin": {"user": "a@example.com", "password": SECRET},
                                                        "accounts": [{"role": "auditor", "password": SECRET}]}))
inrepo = os.path.join(shop, "accounts.env")
os.makedirs(os.path.join(shop, ".git"))
io.open(inrepo, "w", encoding="utf-8").write("SUPPORT_PASS=" + SECRET + "\n")

profile = {"tester": {"name": "T"}, "projects": [
    {"name": "Shop", "ticket_prefixes": ["SHOP"], "repo_paths": [shop.replace("\\", "/")],
     "source_code": {"available": True},
     "environments": [{"name": "QA", "url": "http://127.0.0.1:%d/" % qa.server_port},
                      {"name": "Prod", "url": "http://127.0.0.1:%d/" % prod.server_port, "production": True},
                      {"name": "Broken", "url": "http://127.0.0.1:%d/broken" % qa.server_port},
                      {"name": "Down", "url": "http://127.0.0.1:9/"}],
     "accounts": [{"role": "Shopper", "credential_location": "env:QA_SHOP_USER,QA_SHOP_PASS"},
                  {"role": "Admin", "credential_location": "file:%s#admin" % creds.replace("\\", "/")},
                  {"role": "Auditor", "credential_location": "file:%s#auditor" % creds.replace("\\", "/")},
                  {"role": "Manager", "credential_location": "file:%s#manager" % creds.replace("\\", "/")},
                  {"role": "Clerk", "credential_location": "env:QA_MISSING_PASS"},
                  {"role": "Support", "credential_location": "file:%s#SUPPORT_PASS" % inrepo.replace("\\", "/")},
                  {"role": "Owner", "credential_location": "1Password vault QA"}]},
    {"name": "Moved", "ticket_prefixes": ["MOV"], "repo_paths": [os.path.join(root, "gone").replace("\\", "/")]},
    {"name": "NoCode", "ticket_prefixes": ["NC"], "source_code": {"available": False},
     "environments": [{"name": "UAT", "url": "http://127.0.0.1:%d/" % qa.server_port}]},
]}
imp = os.path.join(root, "import.json")

try:
    rc, d, out = js("preflight", "--ticket", "SHOP-1", "--cwd", shop)
    check("E: no profile -> one 'run /qa-setup' ask", d.get("situation") == "E" and len(d.get("ask", [])) == 1, out)

    io.open(imp, "w", encoding="utf-8").write(json.dumps(profile))
    rc, out = run("import", imp)
    check("profile with credential LOCATIONS imports (not refused as a secret)", rc == 0, out)

    rc, d, out = js("match", "--ticket", "SHOP-7", "--cwd", os.path.join(shop, "src"))
    check("A: session open inside the project folder", d.get("situation") == "A", out)
    rc, d, out = js("match", "--ticket", "SHOP-7", "--cwd", other)
    check("B: ticket's project lives elsewhere -> open_in that folder",
          d.get("situation") == "B" and os.path.normcase(os.path.normpath(d.get("open_in", ""))) == os.path.normcase(os.path.normpath(shop)), out)
    rc, d, out = js("match", "--ticket", "MOV-2", "--cwd", other)
    check("C: saved folder no longer exists -> ask where it is now", d.get("situation") == "C" and "no longer exist" in d.get("advice", ""), out)
    rc, d, out = js("match", "--ticket", "NEW-3", "--cwd", other)
    check("D: unknown project -> no_match, ask its block once", d.get("status") == "no_match" and d.get("situation") == "D", out)
    rc, d, out = js("match", "--ticket", "NC-4", "--cwd", other)
    check("A: project recorded as 'no source code' is not asked about a folder", d.get("situation") == "A", out)

    hits.clear()
    rc, d, out = js("preflight", "--ticket", "SHOP-7", "--cwd", shop)
    p = d["projects"][0]
    env = {e["name"]: e for e in p["environments"]}
    acc = {a["role"]: a for a in p["accounts"]}
    check("preflight output never contains a credential value", SECRET not in out and "shopper@example.com" not in out, out)
    check("QA environment probed and answers", env["QA"]["status"] == "ok", env)
    check("production is NEVER contacted", env["Prod"]["status"] == "skipped" and not any(h[0] == prod.server_port for h in hits), (env["Prod"], hits))
    check("5xx environment reported as an ask", env["Broken"]["status"] == "error" and any("Broken" in a for a in d["ask"]), d["ask"])
    check("unreachable environment reported as an ask (VPN hint)", env["Down"]["status"] == "error" and any("VPN" in a for a in d["ask"]), d["ask"])
    check("env-var login present -> ok", acc["Shopper"]["status"] == "ok", acc["Shopper"])
    check("missing env var -> ask, mentions restart", acc["Clerk"]["status"] == "missing" and "restart" in acc["Clerk"]["detail"], acc["Clerk"])
    check("credentials file key found (object key)", acc["Admin"]["status"] == "ok", acc["Admin"])
    check("credentials file key found (list item with role)", acc["Auditor"]["status"] == "ok", acc["Auditor"])
    check("credentials file without that role -> ask", acc["Manager"]["status"] == "missing", acc["Manager"])
    check("credentials file inside a git repo -> warning", "inside a git repository" in acc["Support"]["detail"], acc["Support"])
    check("vault location -> manual, asked once", acc["Owner"]["status"] == "manual" and any("Owner" in a for a in d["ask"]), acc["Owner"])
    check("situation A carried into preflight; status needs-answers", d.get("situation") == "A" and d["status"] == "needs-answers", out)

    rc, d, out = js("preflight", "--ticket", "SHOP-7", "--cwd", shop, "--env", "QA", "--roles", "Shopper,Admin")
    check("only the ticket's env + roles checked -> nothing to ask", d.get("status") == "ok" and not d["ask"], out)
    rc, d, out = js("preflight", "--ticket", "SHOP-7", "--cwd", shop, "--env", "QA", "--roles", "Shopper,Approver")
    check("a role the ticket needs but nobody saved -> one ask", len(d["ask"]) == 1 and "approver" in d["ask"][0], out)
    rc, d, out = js("preflight", "--ticket", "SHOP-7", "--cwd", other, "--env", "QA", "--roles", "Shopper")
    check("B in preflight -> the ask says where to open Claude Code", d.get("situation") == "B" and any("open" in a.lower() for a in d["ask"]), out)
    rc, d, out = js("preflight", "--ticket", "NEW-1", "--cwd", other)
    check("D in preflight -> one ask for the new project's block", d.get("situation") == "D" and len(d["ask"]) == 1, out)
    hits.clear()
    rc, d, out = js("preflight", "--no-probe")
    check("all-projects check (setup) flags the vanished folder; --no-probe contacts nothing",
          any("Moved" in a and "does not exist" in a for a in d["ask"]) and not hits, out)

    rc, out = run("add-rules")
    allow = json.load(io.open(os.path.join(root, "s.json"), encoding="utf-8"))["permissions"]["allow"]
    check("add-rules grants Read on the credentials file (login at run time without a prompt)",
          any(r.startswith("Read(") and r.endswith("test-accounts.json)") for r in allow), [r for r in allow if "accounts" in r])
finally:
    qa.shutdown(); prod.shutdown()
    shutil.rmtree(root, ignore_errors=True)

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

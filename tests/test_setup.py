"""Tests for sentinelqa-setup.py. Everything runs in a temp SENTINELQA_HOME and a temp settings file."""
import io, json, os, shutil, subprocess, sys, tempfile

S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "sentinelqa", "skills", "qa-functional", "scripts", "sentinelqa-setup.py")
root = tempfile.mkdtemp(prefix="sqa-setup-")
ENV = dict(os.environ, SENTINELQA_HOME=os.path.join(root, "home"), PYTHONIOENCODING="cp1252")
SETTINGS = os.path.join(root, "claude", "settings.json")
results = []
BS = chr(92)


def run(*args, stdin=None):
    r = subprocess.run([sys.executable, S, *args], input=stdin, env=ENV, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "\n     " + detail[-700:]))


repo = os.path.join(root, "src", "shop")
os.makedirs(repo)
ext = os.path.join(root, "QA-cases", "Billing")
proj = {
    "tester": {"name": "Tester-T"},
    "projects": [
        {"name": "Shop-Web", "ticket_prefixes": ["shop"], "repo_paths": [repo],
         "jira_site": "example.atlassian.net", "source_code": {"available": True, "path": repo},
         "environments": [{"name": "QA", "url": "https://qa.shop.example/checkout", "build_check": "GET /version"},
                          {"name": "Prod", "url": "https://shop.example", "production": True}],
         "accounts": [{"role": "Shopper", "credential_location": "1Password vault 'QA' / env SHOP_QA_USER"}]},
        {"name": "Billing", "ticket_prefixes": ["BIL"], "repo_paths": [os.path.join(root, "src", "billing")],
         "repo_write_policy": "read-only", "case_root": ext,
         "source_code": {"available": False}, "environments": [{"name": "UAT", "url": "http://uat.bill.example:8080"}]},
    ],
}

try:
    rc, out = run("doctor")
    check("doctor runs and reports every prerequisite", rc == 0 and "Node.js" in out and "Git" in out
          and "Project profile" in out and "RESULT" in out, out)
    rc, out = run("doctor", "--json")
    check("doctor --json is valid JSON", rc == 0 and json.loads(out)["checks"], out)

    rc, out = run("match", "--cwd", repo)
    check("match with no profile -> no_profile", json.loads(out)["status"] == "no_profile", out)

    rc, out = run("import", "-", stdin=json.dumps(proj))
    check("import a 2-project profile", rc == 0 and "total projects: 2" in out, out)
    prof = json.load(io.open(os.path.join(root, "home", "projects.json"), encoding="utf-8"))
    check("prefixes normalised and mapped for the report shelf",
          prof["ticket_prefixes"] == {"SHOP": "Shop-Web", "BIL": "Billing"}, json.dumps(prof["ticket_prefixes"]))
    check("default case root for a writable repo is qa", prof["projects"][0]["case_root"] == "qa")
    check("read-only project ledger sits next to its case files, outside the repo", os.path.normpath(prof["projects"][1]["ledger"]) == os.path.normpath(os.path.join(ext, "known-findings.md")), prof["projects"][1]["ledger"])

    rc, out = run("import", "--json", json.dumps({"name": "Inline", "ticket_prefixes": ["INL"]}))
    check("import --json (single-argument form) works", rc == 0 and "added: Inline" in out, out)
    rc, out = run("import")
    check("import with no source prints usage", rc == 2 and "usage" in out, out)
    rc, out = run("match", "--cwd", os.path.join(repo, "sub", "dir"))
    m = json.loads(out)
    check("match by working folder (subfolder of the repo)", m["status"] == "match" and m["project"]["name"] == "Shop-Web", out)
    rc, out = run("match", "--cwd", root, "--ticket", "BIL-42")
    m = json.loads(out)
    check("match by ticket prefix when the folder is unknown", m["status"] == "match" and m["project"]["name"] == "Billing", out)
    rc, out = run("match", "--cwd", root, "--ticket", "ZZZ-1")
    check("unknown project -> no_match with the project list", json.loads(out)["status"] == "no_match", out)

    rc, out = run("import", "-", stdin=json.dumps({"name": "Shop-Web", "ticket_prefixes": ["SHOP"],
                                                  "accounts": [{"role": "Admin", "password": "hunter2"}]}))
    check("refuses a password field", rc == 2 and "REFUSED" in out, out)
    rc, out = run("import", "-", stdin=json.dumps({"name": "X", "ticket_prefixes": ["X"],
                                                  "notes": "use token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123"}))
    check("refuses a token-looking value", rc == 2 and "REFUSED" in out, out)
    rc, out = run("import", "-", stdin=json.dumps({"name": "Dup", "ticket_prefixes": ["SHOP"]}))
    check("refuses a prefix already owned by another project", rc == 2 and "one project only" in out, out)
    rc, out = run("import", "-", stdin=json.dumps({"name": "RO", "ticket_prefixes": ["RO"], "repo_write_policy": "read-only",
                                                  "case_root": "qa"}))
    check("refuses an in-repo case root for a read-only repo", rc == 2 and "OUTSIDE the repo" in out, out)
    rc, out = run("import", "-", stdin=json.dumps({"name": "Shop-Web", "ticket_prefixes": ["SHOP"], "repo_paths": [repo],
                                                  "environments": [{"name": "QA2", "url": "https://qa2.shop.example"}]}))
    prof = json.load(io.open(os.path.join(root, "home", "projects.json"), encoding="utf-8"))
    check("re-import updates a project in place, keeps the others",
          rc == 0 and len(prof["projects"]) == 3 and prof["projects"][0]["environments"][0]["name"] == "QA2", out)
    check("previous profile kept as a backup", any(f.startswith("projects.json.sentinelqa-backup")
                                                    for f in os.listdir(os.path.join(root, "home"))))
    run("import", "-", stdin=json.dumps(proj))      # restore both envs for the rules test

    os.makedirs(os.path.dirname(SETTINGS))
    io.open(SETTINGS, "w", encoding="utf-8").write(json.dumps({"model": "opus", "permissions": {"allow": ["Bash(ls *)"],
                                                                                               "defaultMode": "default"}}))
    rc, out = run("add-rules", "--settings", SETTINGS)
    s = json.load(io.open(SETTINGS, encoding="utf-8"))
    allow = s["permissions"]["allow"]
    check("add-rules keeps existing settings and rules", rc == 0 and s["model"] == "opus" and "Bash(ls *)" in allow
          and s["permissions"]["defaultMode"] == "default", out)
    check("add-rules adds the base rules", "Edit(qa/**)" in allow and "Bash(python *sentinelqa*)" in allow, str(allow)[:400])
    ext_rule = "Edit(//%s/**)" % ext.replace("\\", "/").replace(":", "", 1)[0].lower() + ext.replace("\\", "/")[2:] + "/**)"
    check("add-rules allows the external case folder of a read-only project",
          any(r.startswith("Edit(//") and r.endswith("QA-cases/Billing/**)") for r in allow), str([r for r in allow if "QA-cases" in r]))
    check("add-rules adds curl for test hosts only, never production",
          "Bash(curl *https://qa.shop.example/*)" in allow and "Bash(curl *http://uat.bill.example:8080/*)" in allow
          and not any("shop.example.com" in r for r in allow if "curl" in r), str([r for r in allow if "curl" in r]))
    check("add-rules records the decision", json.load(io.open(os.path.join(root, "home", "state.json")))["permission_rules"] == "added")
    n = len(allow)
    rc, out = run("add-rules", "--settings", SETTINGS)
    check("add-rules is idempotent", rc == 0 and len(json.load(io.open(SETTINGS, encoding="utf-8"))["permissions"]["allow"]) == n, out)
    io.open(SETTINGS, "w", encoding="utf-8").write("{broken json")
    rc, out = run("add-rules", "--settings", SETTINGS)
    check("add-rules refuses to touch a broken settings file", rc == 2 and io.open(SETTINGS).read() == "{broken json", out)

    # ---- review round 2 ----
    gb = "/" + repo[0].lower() + repo[2:].replace("\\", "/")          # Git Bash form of the repo path
    run("import", "--json", json.dumps({"name": "Shop-Web", "ticket_prefixes": ["SHOP"], "repo_paths": [gb]}))
    rc, out = run("match", "--cwd", repo)
    check("repo path saved in Git Bash form (/c/...) still matches", json.loads(out).get("status") == "match", out + " | " + gb)
    run("import", "-", stdin=json.dumps(proj))
    rc, out = run("match", "--cwd", repo, "--ticket", "BIL-9")
    m = json.loads(out)
    check("ticket prefix wins when folder and ticket disagree", m["project"]["name"] == "Billing" and "ticket decides" in m["reason"], out)
    rc, out = run("import", "--json", json.dumps({"name": "Q", "ticket_prefixes": ["Q"],
        "gotchas": ["Reset password: link expires after 10 min", "pwd=field is masked"], "sso_bypass": True,
        "accounts": [{"role": "Admin", "credential_location": "1Password vault 'QA' / env SHOP_TOKEN_NAME"}]}))
    check("normal text mentioning password/bypass/token names is accepted", rc == 0, out)
    rc, out = run("import", "--json", json.dumps({"name": "Q2", "ticket_prefixes": ["Q2"], "gotchas": ["login with password=Hunter2xyz"]}))
    check("an actual password=value is still refused", rc == 2, out)
    rc, out = run("import", "--json", json.dumps({"name": "Bad", "ticket_prefixes": ["BAD"], "environments": "https://x"}))
    check("malformed environments (a string) is refused, not a crash", rc == 2 and "must be a list" in out and "Traceback" not in out, out)
    rc, out = run("import", "--json", json.dumps({"name": "UNC", "ticket_prefixes": ["UNC"], "repo_write_policy": "read-only",
                                                 "case_root": BS*2 + "srv" + BS + "share" + BS + "qa"}))
    check("network-share case root is refused with a message", rc == 2 and "network-share" in out, out)
    f = os.path.join(root, "import.json")
    io.open(f, "w", encoding="utf-8").write(json.dumps({"name": "FileImp", "ticket_prefixes": ["FIM"],
        "repo_paths": ["C:" + BS + "new" + BS + "temp"], "repo_write_policy": "read-only", "case_root": "C:" + BS + "QA cases" + BS + "FileImp"}))
    rc, out = run("import", f)
    prof = json.load(io.open(os.path.join(root, "home", "projects.json"), encoding="utf-8"))
    fi = [x for x in prof["projects"] if x["name"] == "FileImp"][0]
    check("import from a file keeps Windows backslash paths intact", rc == 0 and fi["repo_paths"] == ["C:" + BS + "new" + BS + "temp"]
          and fi["case_root"] == "C:" + BS + "QA cases" + BS + "FileImp", out + json.dumps(fi))
    run("import", "--json", json.dumps({"name": "FileImp", "ticket_prefixes": ["FIX"], "repo_paths": ["C:/x"],
                                        "repo_write_policy": "read-only", "case_root": "C:/QA/FileImp"}))
    prof = json.load(io.open(os.path.join(root, "home", "projects.json"), encoding="utf-8"))
    check("a removed prefix disappears from the report-shelf map", "FIM" not in prof["ticket_prefixes"] and prof["ticket_prefixes"].get("FIX") == "FileImp",
          json.dumps(prof["ticket_prefixes"]))
    run("import", "--json", json.dumps({"name": "Apps", "ticket_prefixes": ["APP"], "environments": [
        {"name": "UAT", "url": "https://apps.example.com:8443/uat"}, {"name": "Prod", "url": "https://apps.example.com/prod", "production": True},
        {"name": "Same", "url": "https://apps.example.com/test"}]}))
    io.open(SETTINGS, "w", encoding="utf-8").write(json.dumps({"permissions": None}))
    rc, out = run("add-rules", "--settings", SETTINGS)
    allow = json.load(io.open(SETTINGS, encoding="utf-8"))["permissions"]["allow"]
    curl = [r for r in allow if "apps.example.com" in r]
    check("add-rules handles \"permissions\": null", rc == 0 and len(allow) > 50, out)
    check("curl rule is scoped to scheme://host:port of the test env", "Bash(curl *https://apps.example.com:8443/*)" in curl, str(curl))
    check("no curl rule can reach production (same origin skipped)", not any(r in ("Bash(curl *https://apps.example.com/*)",
          "Bash(curl *https://apps.example.com)") for r in curl) and "production uses the same address" in out, str(curl) + out)
    rc, out = run("state", "rules", "declined")
    check("state records a decline", rc == 0 and json.load(io.open(os.path.join(root, "home", "state.json")))["permission_rules"] == "declined", out)
    rc, out = run("show")
    check("show prints the profile without anything secret", rc == 0 and "Shop-Web" in out and "PRODUCTION" in out, out)
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

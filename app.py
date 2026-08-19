from flask import Flask, jsonify, request, render_template, session, redirect, send_from_directory
import json, os, time, uuid, threading, shutil

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "jobsnearme2025secret")

SCRAPED = "scraped.json"
STORE = "store.json"
PUBLISHED = "published.json"
UPLOADS = "uploads"
PASS = os.environ.get("ADMIN_PASS", "1234")

lock = threading.Lock()
# Prevent cache for dynamic routes to avoid stale data
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0 

os.makedirs(UPLOADS, exist_ok=True)

def read_json(path):
    """Reads JSON with Lock to prevent corruption"""
    if not os.path.exists(path):
        write_json(path, [])
        return []
    
    # ⭐ LOCK FOR READING TOO TO PREVENT CORRUPTION DURING WRITE
    with lock: 
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"❌ Error reading {path}: {e}")
            write_json(path, [])
            return []

def write_json(path, data):
    """Writes JSON safely with Atomic Rename"""
    with lock:
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Remove old file if exists to ensure rename works smoothly
            if os.path.exists(path):
                # Optional: Copy permissions/metadata if needed, but usually rename suffices
                pass
            
            # Atomic Move
            if os.path.exists(tmp):
                os.replace(tmp, path) # Use replace instead of rename for safety on Windows too
                print(f"✅ Saved to {path} at {time.strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"❌ Error writing {path}: {e}")
            if os.path.exists(tmp):
                os.remove(tmp)

def fix_job(j):
    if not isinstance(j, dict):
        return None

    j.setdefault("id", uuid.uuid4().hex[:8])
    j.setdefault("title", "Untitled")
    j.setdefault("details", "")
    j.setdefault("image", "")
    j.setdefault("apply_link", "")
    j.setdefault("link", "")
    j.setdefault("link2", "")
    j.setdefault("link3", "")
    j.setdefault("location", "India")
    j.setdefault("deadline", "")
    j.setdefault("source", "manual")
    j.setdefault("status", "scraped")
    
    # Preserve created_at if it exists to track origin time
    if "created_at" not in j:
        j["created_at"] = time.time()
        
    j.setdefault("edited", False)

    cat = j.get("category", "assam")
    if cat not in ("assam", "india", "private"):
        cat = "assam"
    j["category"] = cat
    j["job_type"] = j.get("job_type", cat)

    img = (j.get("image") or "").strip()
    if img:
        if img.startswith("//"):
            j["image"] = "https:" + img
    return j

def is_admin():
    return session.get("admin") is True

# ===== PAGES =====
@app.route("/")
def page_home():
    return render_template("index.html")

@app.route("/job-page")
def page_job():
    return render_template("job.html")

@app.route("/contact")
def page_contact():
    return "<h2 style='font-family:sans-serif'>Contact</h2><p>Email: admin@jobsnearme.com</p>"

@app.route("/admin")
def page_admin():
    if is_admin():
        return render_template("admin.html")
    return render_template("login.html")

@app.route("/admin/login", methods=["POST"])
def do_login():
    b = request.get_json(silent=True) or {}
    if b.get("password") == PASS:
        session["admin"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "Wrong password"}), 403

@app.route("/admin/logout")
def do_logout():
    session.pop("admin", None)
    return redirect("/")

@app.route("/uploads/<path:name>")
def serve_upload(name):
    return send_from_directory(UPLOADS, name)

# ===== IMAGE UPLOAD =====
@app.route("/upload-image", methods=["POST"])
def do_upload():
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 401

    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty"}), 400

    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
        return jsonify({"error": "Bad format"}), 400

    filename = uuid.uuid4().hex[:10] + "." + ext
    f.save(os.path.join(UPLOADS, filename))
    return jsonify({"ok": True, "url": "/uploads/" + filename})

# ===== USER JOBS =====
@app.route("/jobs")
def api_jobs():
    data = read_json(PUBLISHED)
    out = []
    for j in data:
        j = fix_job(j)
        if j and j.get("status") == "published":
            out.append(j)

    out.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return jsonify({"data": out})

# ===== ADMIN JOBS =====
@app.route("/admin/jobs")
def api_admin_jobs():
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 401

    sc = [fix_job(j) for j in read_json(SCRAPED)]
    st = [fix_job(j) for j in read_json(STORE)]
    pb = [fix_job(j) for j in read_json(PUBLISHED)]

    sc = [x for x in sc if x]
    st = [x for x in st if x]
    pb = [x for x in pb if x]

    sc.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    st.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    pb.sort(key=lambda x: x.get("created_at", 0), reverse=True)

    return jsonify({"scraped": sc, "store": st, "published": pb})

# ===== ADD JOB =====
@app.route("/add-job", methods=["POST"])
def api_add():
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 401

    b = request.get_json(silent=True) or {}
    title = (b.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title required"}), 400

    cat = b.get("category", "assam")
    if cat not in ("assam", "india", "private"):
        cat = "assam"

    loc_map = {"assam": "Assam", "india": "All India", "private": "All India"}

    job = fix_job({
        "id": uuid.uuid4().hex[:8],
        "title": title,
        "details": b.get("details", ""),
        "image": b.get("image", ""),
        "apply_link": b.get("apply_link", ""),
        "link": b.get("apply_link", ""),
        "link2": b.get("link2", ""),
        "link3": b.get("link3", ""),
        "category": cat,
        "location": b.get("location") or loc_map.get(cat, "India"),
        "deadline": b.get("deadline", ""),
        "status": "scraped",
        "source": "manual",
        "created_at": time.time(),
        "edited": True
    })

    data = read_json(SCRAPED)
    data.append(job)
    write_json(SCRAPED, data)
    return jsonify({"ok": True, "id": job["id"]})

# ===== ACTION API =====
@app.route("/api/action", methods=["POST"])
def api_action():
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 401

    b = request.get_json(silent=True) or {}
    action = (b.get("action") or "").strip()
    jid = str(b.get("id", "")).strip()
    
    if not jid:
        return jsonify({"error": "No ID"}), 400

    # MOVE scraped -> store
    if action == "move":
        sc = read_json(SCRAPED)
        st = read_json(STORE)

        # Find job in scraped
        job = next((j for j in sc if str(j.get("id")) == jid), None)
        
        if not job:
            return jsonify({"error": "Not found"}), 404
        
        # Check if already in store to avoid duplicates
        if any(str(s.get("id")) == jid for s in st):
             return jsonify({"ok": True, "message": "Already in store"})

        # Create new entry for store
        copy_job = json.loads(json.dumps(job))
        copy_job["status"] = "stored"
        copy_job["created_at"] = time.time() # Reset creation time for tracking
        copy_job = fix_job(copy_job)
        st.append(copy_job)
        write_json(STORE, st)
        
        # ❗ CRITICAL FIX: Remove from Scraped so it doesn't get fetched again or override edits
        new_sc = [j for j in sc if str(j.get("id")) != jid]
        write_json(SCRAPED, new_sc)
        
        return jsonify({"ok": True})

    # PUBLISH store -> published (or fallback scraped)
    if action == "publish":
        job = None
        store_data = read_json(STORE)
        job = next((j for j in store_data if str(j.get("id")) == jid), None)

        if not job:
            sc = read_json(SCRAPED)
            job = next((j for j in sc if str(j.get("id")) == jid), None)

        if not job:
            return jsonify({"error": "Not found"}), 404

        job = json.loads(json.dumps(job))
        job["status"] = "published"
        job["published_at"] = time.time()
        job = fix_job(job)

        pub = read_json(PUBLISHED)
        pub = [p for p in pub if str(p.get("id")) != jid]
        pub.append(job)
        write_json(PUBLISHED, pub)

        return jsonify({"ok": True, "total": len(pub)})

    # UNPUBLISH published -> store
    if action == "unpublish":
        pub = read_json(PUBLISHED)
        job = None
        new_pub = []
        for p in pub:
            if str(p.get("id")) == jid:
                job = json.loads(json.dumps(p))
            else:
                new_pub.append(p)

        if not job:
            return jsonify({"error": "Not found"}), 404

        job["status"] = "stored"
        job["published_at"] = None
        job = fix_job(job)

        # Move back to STORE, remove if exists there first
        st = read_json(STORE)
        st = [s for s in st if str(s.get("id")) != jid]
        st.append(job)

        write_json(PUBLISHED, new_pub)
        write_json(STORE, st)
        return jsonify({"ok": True})

    # DELETE from all
    if action == "delete":
        deleted = False
        for fp in [SCRAPED, STORE, PUBLISHED]:
            data = read_json(fp)
            new_data = [j for j in data if str(j.get("id")) != jid]
            if len(new_data) < len(data):
                deleted = True
                write_json(fp, new_data)
        return jsonify({"ok": deleted})

    # UPDATE (edit modal)
    if action == "update":
        updates = b.get("data", {}) or {}
        keys = ["title", "details", "image", "apply_link", "link2", "link3",
                "category", "deadline", "location"]

        # Search in priority order: PUBLISHED > STORE > SCRAPED
        # Ensures edited data in 'stored' or 'published' isn't ignored
        target_files = [PUBLISHED, STORE, SCRAPED] 
        
        for fp in target_files:
            data = read_json(fp)
            found = False
            for j in data:
                if str(j.get("id")) == jid:
                    for k in keys:
                        if k in updates:
                            j[k] = updates[k]
                    if "category" in updates:
                        j["job_type"] = updates["category"]
                    j["edited"] = True
                    found = True
                    break
            if found:
                write_json(fp, data)
                return jsonify({"ok": True})

        return jsonify({"error": "Not found"}), 404

    return jsonify({"error": "Unknown action"}), 400


# ===== BULK =====
@app.route("/api/bulk", methods=["POST"])
def api_bulk():
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 401

    b = request.get_json(silent=True) or {}
    action = b.get("action", "")

    if action == "move-all":
        sc = read_json(SCRAPED)
        st = read_json(STORE)
        existing_ids = set(str(s.get("id")) for s in st)

        moved = 0
        sc_to_remove = []
        
        for j in sc:
            jid = str(j.get("id"))
            if jid not in existing_ids:
                copy = json.loads(json.dumps(j))
                copy["status"] = "stored"
                copy["created_at"] = time.time()
                copy = fix_job(copy)
                st.append(copy)
                existing_ids.add(jid)
                moved += 1
                sc_to_remove.append(jid)
        
        write_json(STORE, st)
        write_json(SCRAPED, [j for j in sc if str(j.get("id")) not in sc_to_remove])
        return jsonify({"ok": True, "moved": moved})

    if action == "publish-all":
        st = read_json(STORE)
        pub = read_json(PUBLISHED)
        existing_ids = set(str(p.get("id")) for p in pub)

        added = 0
        for j in st:
            jid = str(j.get("id"))
            if jid not in existing_ids:
                copy = json.loads(json.dumps(j))
                copy["status"] = "published"
                copy["published_at"] = time.time()
                copy = fix_job(copy)
                pub.append(copy)
                existing_ids.add(jid)
                added += 1

        write_json(PUBLISHED, pub)
        return jsonify({"ok": True, "published": added, "total": len(pub)})

    return jsonify({"error": "Unknown"}), 400


# ===== JOB DETAIL JSON =====
@app.route("/job/<path:jid>")
def api_detail(jid):
    jid = str(jid).strip()
    # Check in priority order
    for fp in [PUBLISHED, STORE, SCRAPED]:
        data = read_json(fp)
        for j in data:
            if str(j.get("id")) == jid:
                return jsonify(fix_job(j))
    return jsonify({"error": "Not found"}), 404


# ===== SCRAPER NOW =====
@app.route("/admin/scrape-now", methods=["POST"])
def do_scrape():
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        from scraper import scrape_all
        threading.Thread(target=scrape_all, daemon=True).start()
        return jsonify({"ok": True, "message": "Scraper started!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/scrape-status")
def scrape_status():
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 401
    data = read_json(SCRAPED)

    sources = {}
    for j in data:
        s = j.get("source", "?")
        sources[s] = sources.get(s, 0) + 1

    last = max([j.get("created_at", 0) for j in data]) if data else 0
    return jsonify({"total": len(data), "sources": sources, "last": last})


if __name__ == "__main__":
    for f in [SCRAPED, STORE, PUBLISHED]:
        if not os.path.exists(f):
            write_json(f, [])

    PORT = int(os.environ.get("PORT", 5000))
    print(f"🚀 Starting on port {PORT}")

    def auto_scrape():
        time.sleep(60)
        while True:
            try:
                from scraper import scrape_all
                scrape_all()
            except Exception as e:
                print(f"❌ Auto scrape: {e}")
            time.sleep(1800)

    threading.Thread(target=auto_scrape, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
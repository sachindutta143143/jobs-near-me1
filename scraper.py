import requests, json, time, os, hashlib, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9"
}

SCRAPED_FILE = "scraped.json"

# ===== STABLE ID FIX: only LINK =====
def make_id(link: str) -> str:
    raw = (link or "").strip().encode("utf-8", errors="ignore")
    return hashlib.md5(raw).hexdigest()[:14]

def load_old():
    if not os.path.exists(SCRAPED_FILE):
        return []
    try:
        with open(SCRAPED_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except:
        return []

def save_jobs(new_jobs):
    print("💾 Saving jobs to database...")
    old = load_old()
    
    # Create map for quick lookup
    existing_map = {}
    for j in old:
        existing_map[str(j["id"])] = j

    added = 0
    
    for j in new_jobs:
        jid = str(j["id"])
        
        if jid not in existing_map:
            # New Job
            old.append(j)
            added += 1
        else:
            # Existing Job FOUND in Scraped List
            oj = existing_map[jid]
            
            # ⭐ CRITICAL PROTECTION START
            # Agar job edit kiya gaya hai, toh scrape ka data OVERWRITE NAI karega.
            # Not only skip details, but skip merging entirely.
            if oj.get("edited"):
                # Keep the OLD version exactly as it is
                continue 
            
            # Agar edited nahi hai, toh safe merging (details/image fill karo)
            # lekin title/status/source ko hamesha original rakhna hi behtar hai
            # kyunki admin ne manual settings set ki thi
            safe_fill = [
                ("details", j.get("details")),
                ("image", j.get("image")),
                ("apply_link", j.get("apply_link")),
                ("title", j.get("title"))
            ]
            
            for key, val in safe_fill:
                if not oj.get(key) and val:
                    oj[key] = val
            
            # Created_at hamesha preserve karo, naya scrape time set mat karo
            oj.setdefault("created_at", j.get("created_at", time.time()))
            # ⭐ CRITICAL PROTECTION END

    # Sort desc
    old.sort(key=lambda x: x.get("created_at", 0), reverse=True)

    with open(SCRAPED_FILE, "w", encoding="utf-8") as f:
        json.dump(old, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved: {added} new | Total: {len(old)}")

# ... (Rest of functions stay similar below) ...

def is_job(title):
    t = (title or "").lower()
    bad = ["admit", "result", "answer key", "syllabus", "login", "download", "certificate"]
    if any(b in t for b in bad):
        return False
    good = ["recruitment", "vacancy", "job", "apply", "post", "bharti", "notification", "walk-in", "opening", "hiring"]
    return any(g in t for g in good) or len(t) > 35

def detect_cat(title):
    t = (title or "").lower()
    if "private" in t or "company" in t or "startup" in t:
        return "private"
    if "all india" in t or "central" in t or "ssc" in t or "upsc" in t or "railway" in t or "bank" in t:
        return "india"
    return "assam"

def detect_loc(title, default="India"):
    t = (title or "").lower()
    states = {
        "assam": "Assam", "delhi": "Delhi", "mumbai": "Mumbai", "kolkata": "Kolkata",
        "bihar": "Bihar", "guwahati": "Guwahati", "bangalore": "Bangalore",
        "chennai": "Chennai", "hyderabad": "Hyderabad", "pune": "Pune",
        "rajasthan": "Rajasthan", "gujarat": "Gujarat", "kerala": "Kerala",
        "maharashtra": "Maharashtra", "karnataka": "Karnataka"
    }
    for k, v in states.items():
        if k in t:
            return v
    return default

def get_page(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  ❌ {url}: {e}")
    return None

def get_image(soup, base=""):
    try:
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]

        for img in soup.find_all("img", limit=10):
            src = img.get("src") or img.get("data-src") or ""
            if not src:
                continue
            if any(x in src.lower() for x in ["logo", "icon", "avatar", "1x1", "pixel", "emoji", "gravatar"]):
                continue

            if src.startswith("//"):
                return "https:" + src
            if src.startswith("/"):
                return urljoin(base, src)
            if not src.startswith("http"):
                return urljoin(base, src)
            return src
    except:
        pass
    return ""

def get_details(soup):
    try:
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()
        c = (
            soup.find("article") or
            soup.find("div", class_="entry-content") or
            soup.find("div", class_="post-content") or
            soup.find("div", class_=re.compile("post|entry|job")) or
            soup.find("main") or
            soup.body
        )
        if not c:
            return ""
        text = c.get_text("\n")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return "\n".join(lines)[:4000]
    except:
        return ""

def get_apply(soup, page_url):
    try:
        for a in soup.find_all("a", href=True):
            txt = (a.get_text() or "").lower()
            href = str(a["href"])
            if any(k in txt for k in ["apply online", "apply now", "apply here", "click here to apply"]) or \
               any(k in href.lower() for k in ["apply", "registration", "form"]):
                return urljoin(page_url, href)
    except:
        pass
    return ""

def scrape_blog_site(url, source, default_loc="India", default_cat="india"):
    print(f"\n🌐 Scraping: {source} ({url})")
    jobs = []

    soup = get_page(url)
    if not soup:
        return jobs

    articles = soup.find_all("article", limit=25)
    if not articles:
        articles = soup.find_all("div", class_=re.compile("post|entry|job"), limit=25)

    links_done = set()

    for art in articles:
        try:
            a = art.find("a", href=True)
            title_tag = art.find(["h2", "h3", "h4"]) or a
            if not a or not title_tag:
                continue

            title = (title_tag.get_text(strip=True) if hasattr(title_tag, "get_text") else a.get_text(strip=True))
            link = str(a.get("href", "")).strip()

            if not title or not link or len(title) < 15:
                continue
            if not link.startswith("http"):
                link = urljoin(url, link)

            if link in links_done:
                continue
            links_done.add(link)

            if not is_job(title):
                continue

            detail_soup = get_page(link)
            details = ""
            img = ""
            apply_link = ""

            if detail_soup:
                details = get_details(detail_soup)
                img = get_image(detail_soup, link)
                apply_link = get_apply(detail_soup, link)

            cat = detect_cat(title)
            if cat == "assam" and default_cat != "assam":
                cat = default_cat

            jobs.append({
                "id": make_id(link),   
                "title": title,
                "details": details,
                "image": img,
                "link": link,
                "apply_link": apply_link or link,
                "link2": "",
                "link3": "",
                "location": detect_loc(title, default_loc),
                "category": cat,
                "job_type": cat,
                "source": source,
                "status": "scraped",
                "created_at": time.time(),
                "edited": False,
                "deadline": "",
            })

            time.sleep(0.5)

        except:
            continue

    print(f"  ✅ {len(jobs)} jobs from {source}")
    return jobs

def scrape_link_list(url, source, default_loc="All India", default_cat="india"):
    print(f"\n🌐 Scraping List: {source} ({url})")
    jobs = []

    soup = get_page(url)
    if not soup:
        return jobs

    links_done = set()

    for a in soup.find_all("a", href=True):
        try:
            title = (a.get_text(strip=True) or "")
            href = str(a.get("href", "")).strip()
            if not title or len(title) < 20:
                continue
            if not href or href.startswith("#") or "javascript" in href.lower():
                continue

            link = href if href.startswith("http") else urljoin(url, href)

            if link in links_done:
                continue
            links_done.add(link)

            skip = ["home", "about", "contact", "privacy", "disclaimer", "sitemap", "login"]
            if any(s in title.lower() for s in skip):
                continue

            if not is_job(title):
                continue

            cat = detect_cat(title)
            if cat == "assam" and default_cat != "assam":
                cat = default_cat

            jobs.append({
                "id": make_id(link),  
                "title": title,
                "details": "",
                "image": "",
                "link": link,
                "apply_link": link,
                "link2": "",
                "link3": "",
                "location": detect_loc(title, default_loc),
                "category": cat,
                "job_type": cat,
                "source": source,
                "status": "scraped",
                "created_at": time.time(),
                "edited": False,
                "deadline": "",
            })
        except:
            continue

    print(f"  ✅ {len(jobs)} jobs from {source}")
    return jobs

def scrape_all():
    print("\n" + "=" * 60)
    print(f"🚀 SCRAPER STARTED — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    all_jobs = []

    # Sites list
    try:
        all_jobs += scrape_blog_site("https://www.assamcareer.com", "AssamCareer", "Assam", "assam")
    except Exception as e:
        print("❌ AssamCareer:", e)

    time.sleep(1)

    try:
        all_jobs += scrape_blog_site("https://jobassam.in", "JobAssam", "Assam", "assam")
    except Exception as e:
        print("❌ JobAssam:", e)

    time.sleep(1)

    try:
        all_jobs += scrape_link_list("https://www.sarkariresult.com/latestjob.php", "SarkariResult", "All India", "india")
    except Exception as e:
        print("❌ SarkariResult:", e)

    time.sleep(1)

    # unique by id
    uniq = {}
    for j in all_jobs:
        uniq[str(j["id"])] = j
    final = list(uniq.values())

    print(f"\n🔥 Unique scraped: {len(final)}")

    save_jobs(final)
    print("✅ SCRAPER DONE")
    print("=" * 60)

if __name__ == "__main__":
    scrape_all()
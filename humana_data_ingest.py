import os
import re
import json
import hashlib
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

CLAIMS_PAYMENT_URL = "https://provider.humana.com/coverage-claims/claims-payment-policies"
SAVE_DIR = "humana_policies/claims_payment_policies"
METADATA_FILE = "humana_policies_metadata.json"
CHANGES_FILE = "humana_policies_changes.json"
os.makedirs(SAVE_DIR, exist_ok=True)

# =======================
# HELPERS
# =======================

def clean_policy_title(raw_title: str) -> str:
    """Clean title to be filesystem-safe"""
    title = raw_title.replace("(opens in new window)", "").strip()
    title = re.sub(r'[<>:"/\\|?*]', '_', title)
    return "_".join(title.split())

def clean_date(raw_date: str) -> str:
    """Convert 7/9/2025 -> 2025-07-09"""
    try:
        dt = datetime.strptime(raw_date.strip(), "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return raw_date.replace("/", "-")

def make_safe_filename(title):
    """
    Extreme safe filename: only 30 chars + hash ensures uniqueness
    """
    short_title = title[:30].strip()  # Only 30 chars from title
    title_hash = hashlib.md5(title.encode()).hexdigest()[:8]  # 8-char unique hash
    return f"{short_title}_{title_hash}.pdf"

def lazy_scroll_until_no_new_policies(page, max_attempts=60, wait_after_scroll=12000):
    """
    Scrolls dynamically until no new policies load.
    Stops only when:
    - policy count doesn't increase AND
    - DOM height doesn't increase
    """
    print("➡️ Starting dynamic scroll...")
    last_count = 0
    last_height = 0
    
    for i in range(max_attempts):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(wait_after_scroll)
        
        sections = page.query_selector_all("div.ClaimsPaymentPolicies_resultSection__uBNjE")
        new_count = len(sections)
        new_height = page.evaluate("document.body.scrollHeight")
        
        print(f"➡️ Scroll {i+1}/{max_attempts} → {new_count} policies | DOM height={new_height}")
        
        if new_count == last_count and new_height == last_height:
            print("✅ No new policies loaded → stopping scroll")
            break
        
        last_count = new_count
        last_height = new_height
    
    return len(page.query_selector_all("div.ClaimsPaymentPolicies_resultSection__uBNjE"))

def load_previous_metadata():
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, "r") as f:
            return {entry["title"]: entry for entry in json.load(f)}
    return {}

# =======================
# MAIN SCRAPER
# =======================

def scrape_claims_payment():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        print("➡️ Opening Claims Payment Policies page...")
        page.goto(CLAIMS_PAYMENT_URL)
        page.wait_for_timeout(8000)

        # Dynamically load all policies
        total_loaded = lazy_scroll_until_no_new_policies(page)
        print(f"✅ Total policies loaded in DOM: {total_loaded}")

        sections = page.query_selector_all("div.ClaimsPaymentPolicies_resultSection__uBNjE")
        policy_entries = []

        for section in sections:
            link_elem = section.query_selector("a")
            title_elem = section.query_selector("h4")
            date_elem = section.query_selector("p")

            if link_elem and title_elem:
                href = link_elem.get_attribute("href")
                raw_title = title_elem.inner_text().strip()
                clean_title_val = clean_policy_title(raw_title)

                publish_date = ""
                if date_elem:
                    raw_date_text = date_elem.inner_text().replace("Published Date:", "").strip()
                    publish_date = clean_date(raw_date_text)

                if href and "chronicleID" in href:
                    policy_entries.append({
                        "url": href,
                        "title": clean_title_val,
                        "publish_date": publish_date,
                        "filename": make_safe_filename(clean_title_val)
                    })

        browser.close()

    print(f"📄 Found {len(policy_entries)} policies")

    # Load old metadata for comparison
    old_metadata = load_previous_metadata()
    new_metadata = {entry["title"]: entry for entry in policy_entries}

    # Save updated metadata
    with open(METADATA_FILE, "w") as f:
        json.dump(policy_entries, f, indent=2)
    print(f"✅ Full metadata saved to {METADATA_FILE}")

    downloaded, skipped, updated = 0, 0, 0
    changes_report = {"new_policies": [], "updated_policies": []}

    for policy in policy_entries:
        url = policy["url"]
        title = policy["title"]
        publish_date = policy["publish_date"]
        filename = policy["filename"]
        filepath = os.path.join(SAVE_DIR, filename)

        needs_download = False

        # If never downloaded before → NEW policy
        if title not in old_metadata:
            print(f"🆕 New policy detected: {title}")
            needs_download = True
            changes_report["new_policies"].append(policy)
        else:
            # If publish date changed → UPDATED policy
            old_date = old_metadata[title]["publish_date"]
            if old_date != publish_date:
                print(f"🔄 Policy updated: {title} (old: {old_date}, new: {publish_date}) → re-downloading")
                needs_download = True
                updated += 1
                changes_report["updated_policies"].append({
                    "title": title,
                    "old_date": old_date,
                    "new_date": publish_date,
                    "url": url,
                    "filename": filename
                })

        # If file missing → force download
        if not os.path.exists(filepath):
            needs_download = True

        if needs_download:
            try:
                print(f"📥 Downloading {filename}...")
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                print(f"✅ Saved: {filename}")
                downloaded += 1
            except Exception as e:
                print(f"⚠️ Failed to download {filename}: {e}")
        else:
            print(f"✅ Already up-to-date: {filename}")
            skipped += 1

    # Save changes report
    with open(CHANGES_FILE, "w") as f:
        json.dump(changes_report, f, indent=2)
    print(f"✅ Changes report saved to {CHANGES_FILE}")

    print(f"\n🎯 Done! New Downloads: {downloaded}, Updated: {updated}, Skipped: {skipped}")

if __name__ == "__main__":
    scrape_claims_payment()

"""
UHC Policy Scraper - Pure Scraping (No ChromaDB)
Downloads UHC policies and RPUB updates
"""

import os
import requests
import asyncio
from playwright.async_api import async_playwright
import datetime
import json
from pathlib import Path

# =========================
# CONFIG
# =========================
UHC_PARENT_URL = "https://www.uhcprovider.com/en/policies-protocols/commercial-policies/commercial-medical-drug-policies.html"
RPUB_BASE_URL = "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-reimbursement/rpub/UHC-COMM-RPUB-{}-{}.pdf"
SAVE_DIR = "uhc_policies"
METADATA_FILE = "uhc_policies_metadata.json"

# Create directories
os.makedirs(f"{SAVE_DIR}/policies", exist_ok=True)
os.makedirs(f"{SAVE_DIR}/rpub_updates", exist_ok=True)

class UHCPolicyScraper:
    def __init__(self, download_folder=SAVE_DIR):
        self.download_folder = download_folder
        self.policies_folder = os.path.join(download_folder, "policies")
        self.rpub_folder = os.path.join(download_folder, "rpub_updates")
        self.metadata_file = os.path.join(download_folder, METADATA_FILE)
        
        # Load existing metadata
        self.metadata = self.load_metadata()
        
        # Track downloads in this session
        self.session_stats = {
            "policies_downloaded": 0,
            "rpub_downloaded": 0,
            "policies_skipped": 0,
            "rpub_skipped": 0,
            "errors": []
        }
    
    def load_metadata(self):
        """Load existing download metadata"""
        if os.path.exists(self.metadata_file):
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        return {
            "last_updated": None,
            "downloaded_files": {},
            "stats": {
                "total_policies": 0,
                "total_rpub": 0
            }
        }
    
    def save_metadata(self):
        """Save download metadata"""
        self.metadata["last_updated"] = datetime.datetime.now().isoformat()
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)
    
    def is_already_downloaded(self, url, file_type):
        """Check if file is already downloaded"""
        return url in self.metadata["downloaded_files"]
    
    def download_pdf(self, url, folder, file_type="policy"):
        """Download PDF and return success status"""
        filename = url.split("/")[-1]
        filepath = os.path.join(folder, filename)
        
        # Check if already downloaded
        if self.is_already_downloaded(url, file_type):
            print(f"⏩ Already downloaded: {filename}")
            if file_type == "policy":
                self.session_stats["policies_skipped"] += 1
            else:
                self.session_stats["rpub_skipped"] += 1
            return True
        
        # Check if file exists locally
        if os.path.exists(filepath):
            print(f"⏩ File exists locally: {filename}")
            self.mark_as_downloaded(url, filename, file_type)
            return True
        
        try:
            print(f"⬇️ Downloading: {filename}")
            resp = requests.get(url, timeout=30)
            
            if resp.status_code == 200:
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                
                print(f"✅ Downloaded: {filename}")
                self.mark_as_downloaded(url, filename, file_type)
                
                if file_type == "policy":
                    self.session_stats["policies_downloaded"] += 1
                else:
                    self.session_stats["rpub_downloaded"] += 1
                
                return True
            else:
                error_msg = f"Failed to download {url} - HTTP {resp.status_code}"
                print(f"❌ {error_msg}")
                self.session_stats["errors"].append(error_msg)
                return False
                
        except Exception as e:
            error_msg = f"Error downloading {url}: {e}"
            print(f"⚠️ {error_msg}")
            self.session_stats["errors"].append(error_msg)
            return False
    
    def mark_as_downloaded(self, url, filename, file_type):
        """Mark file as downloaded in metadata"""
        self.metadata["downloaded_files"][url] = {
            "filename": filename,
            "type": file_type,
            "downloaded_at": datetime.datetime.now().isoformat(),
            "file_size": os.path.getsize(os.path.join(
                self.policies_folder if file_type == "policy" else self.rpub_folder, 
                filename
            )) if os.path.exists(os.path.join(
                self.policies_folder if file_type == "policy" else self.rpub_folder, 
                filename
            )) else 0
        }
        
        # Update stats
        if file_type == "policy":
            self.metadata["stats"]["total_policies"] = len([
                f for f in self.metadata["downloaded_files"].values() 
                if f["type"] == "policy"
            ])
        else:
            self.metadata["stats"]["total_rpub"] = len([
                f for f in self.metadata["downloaded_files"].values() 
                if f["type"] == "rpub"
            ])
    
    async def fetch_uhc_policy_links(self):
        """Scrape UHC policy links from the main page"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            print(f"🌐 Loading {UHC_PARENT_URL}...")
            await page.goto(UHC_PARENT_URL, wait_until="networkidle")
            
            # Extract all PDF links
            pdf_links = await page.evaluate("""
                Array.from(document.querySelectorAll('a[href$=".pdf"]')).map(a => a.href);
            """)
            
            await browser.close()
            return list(set(pdf_links))  # Remove duplicates
    
    def download_all_policies(self):
        """Download all UHC policy PDFs"""
        print("\n=== 📋 UHC MEDICAL/DRUG POLICIES ===")
        
        try:
            pdf_links = asyncio.run(self.fetch_uhc_policy_links())
            print(f"🔍 Found {len(pdf_links)} UHC Policy PDFs")
            
            for idx, link in enumerate(pdf_links, 1):
                print(f"[{idx}/{len(pdf_links)}] Processing: {link}")
                self.download_pdf(link, self.policies_folder, "policy")
            
            print(f"✅ Policy download complete!")
            
        except Exception as e:
            error_msg = f"Error fetching policy links: {e}"
            print(f"❌ {error_msg}")
            self.session_stats["errors"].append(error_msg)
    
    def download_rpub_for_year(self, year):
        """Download RPUB updates for a specific year"""
        months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        
        year_downloaded = 0
        
        for month in months:
            url = RPUB_BASE_URL.format(month, year)
            
            # Check if file exists before downloading
            resp = requests.head(url)
            if resp.status_code == 200:
                print(f"✅ Found RPUB: {month} {year}")
                if self.download_pdf(url, self.rpub_folder, "rpub"):
                    year_downloaded += 1
            else:
                print(f"⏩ No RPUB for {month} {year}")
        
        return year_downloaded
    
    def download_rpub_updates(self, start_year=2025):
        """Download RPUB updates from start_year to current year"""
        print(f"\n=== 📰 RPUB UPDATES ({start_year}+) ===")
        
        current_year = datetime.datetime.now().year
        total_rpub_downloaded = 0
        
        for year in range(start_year, current_year + 1):
            print(f"\n--- Checking RPUB for {year} ---")
            year_count = self.download_rpub_for_year(year)
            total_rpub_downloaded += year_count
            print(f"📊 Downloaded {year_count} RPUB files for {year}")
        
        print(f"✅ RPUB download complete! Total: {total_rpub_downloaded}")
        return total_rpub_downloaded
    
    def run_full_scrape(self):
        """Run complete scraping of policies and RPUB updates"""
        print("🚀 Starting UHC Policy Scraper...")
        
        start_time = datetime.datetime.now()
        
        # Download policies
        self.download_all_policies()
        
        # Download RPUB updates
        self.download_rpub_updates()
        
        # Save metadata
        self.save_metadata()
        
        # Print session summary
        end_time = datetime.datetime.now()
        duration = end_time - start_time
        
        print(f"\n{'='*50}")
        print("📊 SCRAPING SESSION SUMMARY")
        print(f"{'='*50}")
        print(f"⏱️ Duration: {duration}")
        print(f"📋 Policies downloaded: {self.session_stats['policies_downloaded']}")
        print(f"📋 Policies skipped: {self.session_stats['policies_skipped']}")
        print(f"📰 RPUB downloaded: {self.session_stats['rpub_downloaded']}")
        print(f"📰 RPUB skipped: {self.session_stats['rpub_skipped']}")
        print(f"❌ Errors: {len(self.session_stats['errors'])}")
        
        if self.session_stats['errors']:
            print(f"\n⚠️ Error details:")
            for error in self.session_stats['errors'][:5]:  # Show first 5 errors
                print(f"   • {error}")
        
        total_downloaded = (self.session_stats['policies_downloaded'] + 
                          self.session_stats['rpub_downloaded'])
        
        print(f"\n🎉 Total files downloaded this session: {total_downloaded}")
        print(f"📁 Files saved to: {self.download_folder}")
        
        return {
            "downloaded": total_downloaded,
            "policies": self.session_stats['policies_downloaded'],
            "rpub": self.session_stats['rpub_downloaded'],
            "errors": len(self.session_stats['errors'])
        }
    
    def get_stats(self):
        """Get current statistics"""
        return {
            "total_files": len(self.metadata["downloaded_files"]),
            "policies": self.metadata["stats"]["total_policies"],
            "rpub": self.metadata["stats"]["total_rpub"],
            "last_updated": self.metadata["last_updated"]
        }

# =========================
# MAIN EXECUTION
# =========================
def main():
    scraper = UHCPolicyScraper()
    
    # Show current stats
    stats = scraper.get_stats()
    if stats["total_files"] > 0:
        print(f"📊 Current database: {stats['policies']} policies, {stats['rpub']} RPUB files")
        print(f"📅 Last updated: {stats['last_updated']}")
    
    # Run scraping
    results = scraper.run_full_scrape()
    
    return results

if __name__ == "__main__":
    main()
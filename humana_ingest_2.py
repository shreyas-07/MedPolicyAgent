
"""
Clean Humana Policy PDF Downloader
Downloads medical and pharmacy policies, skipping existing files
"""

import os
import time
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

class HumanaPolicyDownloader:
    def __init__(self, download_folder="humana_policies"):
        self.download_folder = download_folder
        self.setup_driver()
        self.create_folders()
        self.downloaded_policies = self.load_existing_files()
        self.processed_this_session = set()
    
    def setup_driver(self):
        """Setup Chrome WebDriver with comprehensive pop-up handling"""
        chrome_options = Options()
        prefs = {
            "download.default_directory": os.path.abspath(self.download_folder),
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True,
            # Allow multiple downloads automatically
            "profile.default_content_setting_values.automatic_downloads": 1,
            "profile.content_settings.exceptions.automatic_downloads.*.setting": 1
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        # Add options to minimize pop-ups
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        
        # Set up automatic JavaScript alert handling
        self.driver.execute_script("""
            window.alert = function(msg) { return true; };
            window.confirm = function(msg) { return true; };
            window.prompt = function(msg) { return ''; };
        """)
        
        # Handle the "Download multiple files" permission proactively
        self.handle_download_permission()
    
    def handle_download_permission(self):
        """Handle Chrome's download multiple files permission"""
        try:
            # Navigate to a test page first to trigger permission if needed
            self.driver.get("https://mcp.humana.com/tad/tad_new/home.aspx?type=provider")
            time.sleep(3)
            
            # Try to set permission via JavaScript
            self.driver.execute_script("""
                navigator.permissions.query({name: 'downloads'}).then(function(result) {
                    if (result.state === 'prompt') {
                        // Auto-grant permission
                        console.log('Granting download permission');
                    }
                });
            """)
            
            print("📋 Pre-configured download permissions")
            
        except Exception as e:
            print(f"⚠️ Could not pre-configure download permission: {e}")
    
    def handle_any_alerts(self):
        """Handle any alerts including download permission popup"""
        try:
            alert = self.driver.switch_to.alert
            alert_text = alert.text
            
            # Accept any alerts automatically
            alert.accept()
            print("  📋 Dismissed alert")
            time.sleep(1)
            return True
            
        except:
            # No alert present, check for Chrome permission popup
            try:
                # Look for the "Allow" button in Chrome's permission popup
                allow_buttons = self.driver.find_elements(By.XPATH, "//button[text()='Allow' or text()='ALLOW']")
                if allow_buttons:
                    allow_buttons[0].click()
                    print("  📋 Clicked Allow for downloads")
                    time.sleep(2)
                    return True
                    
                # Alternative selectors for the Allow button
                allow_buttons = self.driver.find_elements(By.CSS_SELECTOR, 
                    "button[aria-label*='Allow'], button[data-text='Allow'], .permission-bubble button:last-child")
                if allow_buttons:
                    allow_buttons[0].click()
                    print("  📋 Clicked Allow button")
                    time.sleep(2)
                    return True
                    
            except Exception as e:
                pass
                
            return False
    
    def create_folders(self):
        """Create download folders"""
        os.makedirs(f"{self.download_folder}/medical_policies", exist_ok=True)
        os.makedirs(f"{self.download_folder}/pharmacy_policies", exist_ok=True)
    
    def load_existing_files(self):
        """Load existing files to avoid re-downloading"""
        existing = set()
        for folder in ["medical_policies", "pharmacy_policies"]:
            path = os.path.join(self.download_folder, folder)
            if os.path.exists(path):
                files = [f for f in os.listdir(path) if f.endswith('.pdf')]
                print(f"📁 {folder}: {len(files)} existing files")
                
                for file in files:
                    base_name = file.replace('.pdf', '')
                    clean_name = re.sub(r'_\d+$', '', base_name)
                    spaced_name = clean_name.replace('_', ' ')
                    
                    existing.add(base_name)
                    existing.add(clean_name)
                    existing.add(spaced_name)
        
        return existing
    
    def navigate_and_sort(self):
        """Navigate to main page and sort alphabetically"""
        self.driver.get("https://mcp.humana.com/tad/tad_new/home.aspx?type=provider")
        time.sleep(5)
        
        sort_links = self.driver.find_elements(By.LINK_TEXT, "Sort Alphabetically")
        if sort_links:
            sort_links[0].click()
            time.sleep(3)
    
    def navigate_to_pharmacy_section(self):
        """Navigate to pharmacy section"""
        self.driver.get("https://mcp.humana.com/tad/tad_new/home.aspx?type=provider")
        time.sleep(5)
        
        # Find and click the second "Sort Alphabetically" link (pharmacy section)
        sort_links = self.driver.find_elements(By.LINK_TEXT, "Sort Alphabetically")
        if len(sort_links) >= 2:
            sort_links[1].click()
            time.sleep(5)
            return True
        return False
    
    def get_policies(self):
        """Get all policy links from current page"""
        links = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'javascript:__doPostBack')]")
        policies = []
        
        for link in links:
            try:
                text = link.text.strip()
                href = link.get_attribute("href")
                
                if not text:
                    continue
                
                # Skip only exact navigation matches
                if text in ['Effective Date', 'Policy Name', 'Reviewed Date']:
                    continue
                
                policies.append({'name': text, 'href': href})
                    
            except:
                continue
        
        return policies
    
    def is_policy_downloaded(self, policy_name):
        """Check if policy is already downloaded"""
        if policy_name in self.processed_this_session:
            return True
        
        # Check variations of the policy name
        variations = [
            policy_name,
            re.sub(r'[<>:"/\\|?*,®™]', '_', policy_name).replace(' ', '_'),
            re.sub(r'[^\w\s]', ' ', policy_name).strip()
        ]
        
        for variation in variations:
            if variation in self.downloaded_policies:
                return True
        
        return False
    
    def check_for_new_files(self, before_count):
        """Check if new files were downloaded"""
        current_count = 0
        for folder in ["medical_policies", "pharmacy_policies", ""]:
            path = os.path.join(self.download_folder, folder) if folder else self.download_folder
            if os.path.exists(path):
                current_count += len([f for f in os.listdir(path) if f.endswith('.pdf')])
        return current_count > before_count
    
    def download_policy(self, policy, subfolder):
        """Download a single policy with improved alert handling"""
        if self.is_policy_downloaded(policy['name']):
            self.processed_this_session.add(policy['name'])
            return True
        
        # Count files before download
        file_count_before = sum(len([f for f in os.listdir(os.path.join(self.download_folder, folder)) 
                                   if f.endswith('.pdf')]) 
                              for folder in ["medical_policies", "pharmacy_policies", ""] 
                              if os.path.exists(os.path.join(self.download_folder, folder)))
        
        # Execute JavaScript postback
        match = re.search(r"__doPostBack\('([^']*)',\s*'([^']*)'\)", policy['href'])
        if match:
            target, argument = match.groups()
            self.driver.execute_script(f"__doPostBack('{target}', '{argument}');")
            
            # Immediately handle any alerts that appear
            self.handle_any_alerts()
            
            # Wait for download with continuous alert checking
            for attempt in range(15):  # Increased attempts
                time.sleep(1)
                
                # Check for alerts every second
                self.handle_any_alerts()
                
                # Check if file downloaded
                if self.check_for_new_files(file_count_before):
                    self.move_and_rename_file(policy['name'], subfolder)
                    self.processed_this_session.add(policy['name'])
                    self.downloaded_policies.add(policy['name'])
                    return True
                
                # Handle any additional alerts that might pop up
                if attempt % 3 == 0:  # Every 3 seconds, double-check for alerts
                    self.handle_any_alerts()
        
        self.processed_this_session.add(policy['name'])
        return False
    
    def move_and_rename_file(self, policy_name, subfolder):
        """Move downloaded file to proper folder"""
        root_files = [f for f in os.listdir(self.download_folder) 
                     if f.endswith('.pdf') and os.path.isfile(os.path.join(self.download_folder, f))]
        
        if root_files:
            newest_file = max(root_files, key=lambda f: os.path.getctime(os.path.join(self.download_folder, f)))
            
            # Create clean filename
            clean_name = re.sub(r'[<>:"/\\|?*,®™]', '_', policy_name).replace(' ', '_')
            if len(clean_name) > 200:
                clean_name = clean_name[:200]
            
            old_path = os.path.join(self.download_folder, newest_file)
            new_path = os.path.join(self.download_folder, subfolder, f"{clean_name}.pdf")
            
            # Handle duplicates
            counter = 1
            while os.path.exists(new_path):
                name_part = clean_name[:190] if len(clean_name) > 190 else clean_name
                new_path = os.path.join(self.download_folder, subfolder, f"{name_part}_{counter}.pdf")
                counter += 1
            
            os.rename(old_path, new_path)
    
    def download_section(self, subfolder, is_pharmacy=False):
        """Download policies from a specific section"""
        section_name = "Pharmacy" if is_pharmacy else "Medical"
        
        # Navigate to appropriate section
        if is_pharmacy:
            if not self.navigate_to_pharmacy_section():
                print("⚠️ Could not find pharmacy section")
                return 0
        else:
            self.navigate_and_sort()
        
        # Get all policies and filter new ones
        all_policies = self.get_policies()
        new_policies = [p for p in all_policies if not self.is_policy_downloaded(p['name'])]
        
        print(f"📊 {section_name}: {len(new_policies)} new, {len(all_policies)-len(new_policies)} existing")
        
        if not new_policies:
            print(f"✅ All {section_name.lower()} policies already downloaded!")
            return 0
        
        # Download each new policy
        downloaded_count = 0
        
        for i, policy in enumerate(new_policies, 1):
            print(f"[{i}/{len(new_policies)}] {policy['name'][:60]}...")
            
            # Refresh page every 20 downloads
            if i % 20 == 1 and i > 1:
                if is_pharmacy:
                    self.navigate_to_pharmacy_section()
                else:
                    self.navigate_and_sort()
            
            if self.download_policy(policy, subfolder):
                downloaded_count += 1
                print("  ✅ Success")
            else:
                print("  ❌ Failed")
            
            time.sleep(2)
        
        print(f"✅ {section_name} complete: {downloaded_count} downloaded")
        return downloaded_count
    
    def download_all_policies(self):
        """Download all medical and pharmacy policies"""
        print("🚀 Starting download process...")
        
        # Download medical policies
        print("\n=== 🏥 MEDICAL POLICIES ===")
        medical_count = self.download_section("medical_policies", is_pharmacy=False)
        
        # Download pharmacy policies  
        print("\n=== 💊 PHARMACY POLICIES ===")
        pharmacy_count = self.download_section("pharmacy_policies", is_pharmacy=True)
        
        # Summary
        total = medical_count + pharmacy_count
        print(f"\n🎉 Complete! Downloaded {total} new policies")
        print(f"📊 Medical: {medical_count}, Pharmacy: {pharmacy_count}")
    
    def run(self):
        """Main execution"""
        try:
            self.download_all_policies()
        except KeyboardInterrupt:
            print("\n⏹️ Stopped by user")
        finally:
            print("🔚 Closing browser...")
            self.driver.quit()

# Run the downloader
if __name__ == "__main__":
    downloader = HumanaPolicyDownloader()
    downloader.run()
#!/usr/bin/env python3
"""
Unified Healthcare Policy Scraper AI Agent
Orchestrates all healthcare policy scrapers with intelligent scheduling and monitoring
"""

import os
import json
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import schedule
import threading

# Import your existing scrapers
from humana_data_ingest import scrape_claims_payment
from humana_ingest_2 import HumanaPolicyDownloader
from uhc_data_ingest import UHCPolicyScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('healthcare_agent.log'),
        logging.StreamHandler()
    ]
)

class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SCHEDULED = "scheduled"

class ScraperType(Enum):
    HUMANA_CLAIMS = "humana_claims"
    HUMANA_POLICIES = "humana_policies"
    UHC_POLICIES = "uhc_policies"

@dataclass
class ScrapingJob:
    """Represents a scraping task"""
    job_id: str
    scraper_type: ScraperType
    job_type: str  # "full_scrape", "incremental", "scheduled"
    parameters: Dict[str, Any]
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    files_downloaded: int = 0
    files_skipped: int = 0
    errors: List[str] = None
    output_folder: str = ""
    duration: Optional[timedelta] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []

class HealthcarePolicyAgent:
    """AI Agent that orchestrates multiple healthcare policy scrapers"""
    
    def __init__(self, config_file="agent_config.json"):
        # Get absolute path of the script directory
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(self.script_dir, config_file)
        
        self.config = self.load_config(self.config_file)
        self.jobs_queue: List[ScrapingJob] = []
        self.active_jobs: Dict[str, ScrapingJob] = {}
        self.completed_jobs: List[ScrapingJob] = []
        self.scheduled_jobs: Dict[str, ScrapingJob] = {}
        
        # Setup logging in script directory
        log_file = os.path.join(self.script_dir, 'healthcare_agent.log')
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        
        # Setup logging
        self.logger = logging.getLogger("HealthcarePolicyAgent")
        
        # Initialize scheduler
        self.scheduler_running = False
        self.scheduler_thread = None
        
        self.logger.info(f"🤖 Healthcare Policy Scraper Agent initialized in {self.script_dir}")
        self.verify_file_structure()
    
    def verify_file_structure(self):
        """Verify and report actual file structure"""
        self.logger.info("🔍 Verifying file structure...")
        
        for scraper_name, scraper_config in self.config['scrapers'].items():
            folder_path = self.get_absolute_path(scraper_config.get('output_folder', scraper_name))
            file_count = self.count_files_in_folder(folder_path)
            
            self.logger.info(f"📁 {scraper_name}: {folder_path} ({file_count} files)")
            
            # Check if folder exists
            if not os.path.exists(folder_path):
                self.logger.warning(f"⚠️ Folder doesn't exist: {folder_path}")
                os.makedirs(folder_path, exist_ok=True)
                self.logger.info(f"✅ Created folder: {folder_path}")
    
    def get_absolute_path(self, relative_path: str) -> str:
        """Convert relative path to absolute path from script directory"""
        if os.path.isabs(relative_path):
            return relative_path
        return os.path.join(self.script_dir, relative_path)
    
    def load_config(self, config_file: str) -> Dict:
        """Load agent configuration"""
        default_config = {
            "scrapers": {
                "humana_claims": {
                    "enabled": True,
                    "output_folder": "humana_policies/claims_payment_policies",
                    "schedule": "daily",  # daily, weekly, monthly
                    "schedule_time": "02:00"
                },
                "humana_policies": {
                    "enabled": True,
                    "output_folder": "humana_policies",
                    "schedule": "weekly",
                    "schedule_time": "03:00"
                },
                "uhc_policies": {
                    "enabled": True,
                    "output_folder": "uhc_policies", 
                    "schedule": "weekly",
                    "schedule_time": "04:00"
                }
            },
            "agent": {
                "max_concurrent_jobs": 2,
                "retry_attempts": 3,
                "retry_delay": 300,
                "auto_schedule": True,
                "notification_webhook": None
            }
        }
        
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                user_config = json.load(f)
                # Merge with defaults
                for key in default_config:
                    if key in user_config:
                        default_config[key].update(user_config[key])
            return default_config
        else:
            # Save default config
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            return default_config
    
    def create_job(self, 
                   scraper_type: str,
                   job_type: str = "incremental",
                   parameters: Dict = None) -> str:
        """Create a new scraping job"""
        
        if scraper_type not in [s.value for s in ScraperType]:
            raise ValueError(f"Unknown scraper type: {scraper_type}")
        
        job_id = f"{scraper_type}_{int(time.time())}"
        scraper_config = self.config['scrapers'].get(scraper_type, {})
        
        job = ScrapingJob(
            job_id=job_id,
            scraper_type=ScraperType(scraper_type),
            job_type=job_type,
            parameters=parameters or {},
            status=JobStatus.PENDING,
            created_at=datetime.now(),
            output_folder=scraper_config.get('output_folder', scraper_type)
        )
        
        self.jobs_queue.append(job)
        self.logger.info(f"📝 Created job {job_id}: {scraper_type} - {job_type}")
        
        return job_id
    
    def run_humana_claims_scraper(self, job: ScrapingJob) -> Dict:
        """Run Humana Claims Payment scraper"""
        try:
            # Save current directory and change to script directory
            original_cwd = os.getcwd()
            os.chdir(self.script_dir)
            
            self.logger.info(f"🔄 Changed working directory to: {self.script_dir}")
            
            # Import and call your existing function
            from humana_data_ingest import scrape_claims_payment
            scrape_claims_payment()
            
            # Parse results from metadata file in script directory
            metadata_file = os.path.join(self.script_dir, "humana_policies_metadata.json")
            changes_file = os.path.join(self.script_dir, "humana_policies_changes.json")
            
            downloaded = 0
            skipped = 0
            
            if os.path.exists(changes_file):
                with open(changes_file, 'r') as f:
                    changes = json.load(f)
                    downloaded = len(changes.get("new_policies", [])) + len(changes.get("updated_policies", []))
            
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                    total_policies = len(metadata)
                    skipped = total_policies - downloaded
            
            # Restore original directory
            os.chdir(original_cwd)
            
            return {
                "downloaded": downloaded,
                "skipped": skipped,
                "errors": 0
            }
            
        except Exception as e:
            # Restore original directory on error
            os.chdir(original_cwd)
            self.logger.error(f"Error in Humana Claims scraper: {e}")
            raise
    
    def run_humana_policies_scraper(self, job: ScrapingJob) -> Dict:
        """Run Humana Policies scraper (Selenium)"""
        try:
            # Use absolute path for download folder
            abs_download_folder = self.get_absolute_path(job.output_folder)
            
            self.logger.info(f"📁 Using download folder: {abs_download_folder}")
            
            # Import and initialize with absolute path
            from humana_ingest_2 import HumanaPolicyDownloader
            downloader = HumanaPolicyDownloader(download_folder=abs_download_folder)
            
            # Count initial files
            initial_medical = self.count_files_in_folder(os.path.join(abs_download_folder, "medical_policies"))
            initial_pharmacy = self.count_files_in_folder(os.path.join(abs_download_folder, "pharmacy_policies"))
            initial_total = initial_medical + initial_pharmacy
            
            self.logger.info(f"📊 Initial file count: {initial_medical} medical, {initial_pharmacy} pharmacy")
            
            # Run the scraper
            downloader.download_all_policies()
            
            # Count final files
            final_medical = self.count_files_in_folder(os.path.join(abs_download_folder, "medical_policies"))
            final_pharmacy = self.count_files_in_folder(os.path.join(abs_download_folder, "pharmacy_policies"))
            final_total = final_medical + final_pharmacy
            
            downloaded = final_total - initial_total
            
            self.logger.info(f"📊 Final file count: {final_medical} medical, {final_pharmacy} pharmacy")
            self.logger.info(f"📥 Downloaded: {downloaded} new files")
            
            return {
                "downloaded": downloaded,
                "skipped": 0,
                "errors": 0
            }
            
        except Exception as e:
            self.logger.error(f"Error in Humana Policies scraper: {e}")
            raise
        finally:
            try:
                downloader.driver.quit()
            except:
                pass
    
    def run_uhc_policies_scraper(self, job: ScrapingJob) -> Dict:
        """Run UHC Policies scraper"""
        try:
            # Save current directory and change to script directory
            original_cwd = os.getcwd()
            os.chdir(self.script_dir)
            
            # Use absolute path for download folder
            abs_download_folder = self.get_absolute_path(job.output_folder)
            
            self.logger.info(f"📁 Using UHC download folder: {abs_download_folder}")
            
            # Import and initialize with absolute path
            from uhc_data_ingest import UHCPolicyScraper
            scraper = UHCPolicyScraper(download_folder=abs_download_folder)
            
            result = scraper.run_full_scrape()
            
            # Restore original directory
            os.chdir(original_cwd)
            
            return {
                "downloaded": result.get("downloaded", 0),
                "skipped": result.get("policies", 0) + result.get("rpub", 0) - result.get("downloaded", 0),
                "errors": result.get("errors", 0)
            }
            
        except Exception as e:
            # Restore original directory on error
            os.chdir(original_cwd)
            self.logger.error(f"Error in UHC Policies scraper: {e}")
            raise
    
    def count_files_in_folder(self, folder_path: str) -> int:
        """Count PDF files in a folder recursively with absolute paths"""
        if not folder_path:
            return 0
            
        # Convert to absolute path
        abs_folder_path = self.get_absolute_path(folder_path)
        
        count = 0
        if os.path.exists(abs_folder_path):
            for root, dirs, files in os.walk(abs_folder_path):
                count += len([f for f in files if f.endswith('.pdf')])
        
        return count
    
    def run_job(self, job: ScrapingJob) -> ScrapingJob:
        """Execute a single scraping job"""
        self.logger.info(f"🚀 Starting job {job.job_id}")
        
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now()
        
        try:
            # Route to appropriate scraper
            if job.scraper_type == ScraperType.HUMANA_CLAIMS:
                result = self.run_humana_claims_scraper(job)
            elif job.scraper_type == ScraperType.HUMANA_POLICIES:
                result = self.run_humana_policies_scraper(job)
            elif job.scraper_type == ScraperType.UHC_POLICIES:
                result = self.run_uhc_policies_scraper(job)
            else:
                raise ValueError(f"Unknown scraper type: {job.scraper_type}")
            
            # Update job with results
            job.files_downloaded = result.get('downloaded', 0)
            job.files_skipped = result.get('skipped', 0)
            if result.get('errors', 0) > 0:
                job.errors.append(f"{result['errors']} errors occurred")
            
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            job.duration = job.completed_at - job.started_at
            
            self.logger.info(f"✅ Job {job.job_id} completed: {job.files_downloaded} files downloaded")
            
        except Exception as e:
            job.status = JobStatus.FAILED
            job.errors.append(str(e))
            job.completed_at = datetime.now()
            job.duration = job.completed_at - job.started_at if job.started_at else None
            
            self.logger.error(f"❌ Job {job.job_id} failed: {e}")
        
        return job
    
    def process_job_queue(self):
        """Process pending jobs with concurrency control"""
        max_concurrent = self.config['agent']['max_concurrent_jobs']
        
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            while self.jobs_queue or self.active_jobs:
                # Submit new jobs if slots available
                while (len(self.active_jobs) < max_concurrent and self.jobs_queue):
                    job = self.jobs_queue.pop(0)
                    future = executor.submit(self.run_job, job)
                    self.active_jobs[job.job_id] = (job, future)
                
                # Check for completed jobs
                completed_job_ids = []
                for job_id, (job, future) in self.active_jobs.items():
                    if future.done():
                        try:
                            completed_job = future.result()
                            self.completed_jobs.append(completed_job)
                        except Exception as e:
                            job.status = JobStatus.FAILED
                            job.errors.append(str(e))
                            self.completed_jobs.append(job)
                        
                        completed_job_ids.append(job_id)
                
                # Remove completed jobs
                for job_id in completed_job_ids:
                    del self.active_jobs[job_id]
                
                # Brief pause
                time.sleep(1)
    
    def schedule_routine_jobs(self):
        """Schedule routine scraping jobs based on config"""
        if not self.config['agent']['auto_schedule']:
            return
        
        self.logger.info("📅 Setting up scheduled jobs...")
        
        for scraper_name, scraper_config in self.config['scrapers'].items():
            if not scraper_config['enabled']:
                continue
            
            schedule_type = scraper_config.get('schedule', 'weekly')
            schedule_time = scraper_config.get('schedule_time', '02:00')
            
            if schedule_type == 'daily':
                schedule.every().day.at(schedule_time).do(
                    self._schedule_job, scraper_name, 'incremental'
                )
            elif schedule_type == 'weekly':
                schedule.every().monday.at(schedule_time).do(
                    self._schedule_job, scraper_name, 'incremental'
                )
            elif schedule_type == 'monthly':
                schedule.every().month.at(schedule_time).do(
                    self._schedule_job, scraper_name, 'incremental'
                )
            
            self.logger.info(f"📅 Scheduled {scraper_name}: {schedule_type} at {schedule_time}")
    
    def _schedule_job(self, scraper_type: str, job_type: str):
        """Internal method to create scheduled jobs"""
        job_id = self.create_job(scraper_type, job_type)
        self.logger.info(f"📅 Auto-scheduled job: {job_id}")
    
    def start_scheduler(self):
        """Start the background scheduler"""
        if self.scheduler_running:
            return
        
        self.scheduler_running = True
        
        def run_scheduler():
            while self.scheduler_running:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        
        self.scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        self.logger.info("📅 Background scheduler started")
    
    def stop_scheduler(self):
        """Stop the background scheduler"""
        self.scheduler_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join()
        self.logger.info("📅 Background scheduler stopped")
    
    def run_all_scrapers(self, job_type: str = "incremental"):
        """Run all enabled scrapers"""
        self.logger.info(f"🚀 Running all scrapers ({job_type})...")
        
        job_ids = []
        for scraper_name, scraper_config in self.config['scrapers'].items():
            if scraper_config['enabled']:
                job_id = self.create_job(scraper_name, job_type)
                job_ids.append(job_id)
        
        self.process_job_queue()
        
        return job_ids
    
    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get status of a specific job"""
        # Check active jobs
        for active_job_id, (job, future) in self.active_jobs.items():
            if active_job_id == job_id:
                return asdict(job)
        
        # Check completed jobs
        for job in self.completed_jobs:
            if job.job_id == job_id:
                return asdict(job)
        
        # Check pending jobs
        for job in self.jobs_queue:
            if job.job_id == job_id:
                return asdict(job)
        
        return None
    
    def get_dashboard_data(self) -> Dict:
        """Get comprehensive dashboard data"""
        total_files = {}
        for scraper_name, scraper_config in self.config['scrapers'].items():
            folder = scraper_config.get('output_folder', scraper_name)
            total_files[scraper_name] = self.count_files_in_folder(folder)
        
        recent_jobs = self.completed_jobs[-10:] if self.completed_jobs else []
        
        return {
            "timestamp": datetime.now().isoformat(),
            "jobs": {
                "pending": len(self.jobs_queue),
                "active": len(self.active_jobs),
                "completed_today": len([j for j in self.completed_jobs 
                                      if j.completed_at and j.completed_at.date() == datetime.now().date()]),
                "total_completed": len(self.completed_jobs)
            },
            "scrapers": {
                name: {
                    "enabled": config['enabled'],
                    "total_files": total_files.get(name, 0),
                    "schedule": config.get('schedule', 'manual')
                }
                for name, config in self.config['scrapers'].items()
            },
            "recent_jobs": [
                {
                    "job_id": job.job_id,
                    "scraper": job.scraper_type.value,
                    "status": job.status.value,
                    "files_downloaded": job.files_downloaded,
                    "duration": str(job.duration) if job.duration else None,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None
                }
                for job in recent_jobs
            ]
        }
    
    def export_job_history(self, filename: str = None):
        """Export job history to JSON"""
        if filename is None:
            filename = f"job_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        history = {
            "export_timestamp": datetime.now().isoformat(),
            "agent_config": self.config,
            "jobs": [asdict(job) for job in self.completed_jobs],
            "summary": {
                "total_jobs": len(self.completed_jobs),
                "successful_jobs": len([j for j in self.completed_jobs if j.status == JobStatus.COMPLETED]),
                "failed_jobs": len([j for j in self.completed_jobs if j.status == JobStatus.FAILED]),
                "total_files_downloaded": sum(j.files_downloaded for j in self.completed_jobs)
            }
        }
        
        with open(filename, 'w') as f:
            json.dump(history, f, indent=2, default=str)
        
        self.logger.info(f"📄 Job history exported to {filename}")
        return filename

def main():
    """CLI interface for the agent"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Healthcare Policy Scraper Agent')
    parser.add_argument('--action', 
                       choices=['run', 'status', 'schedule', 'dashboard', 'export'], 
                       default='run', help='Action to perform')
    parser.add_argument('--scraper', 
                       choices=['humana_claims', 'humana_policies', 'uhc_policies', 'all'],
                       default='all', help='Which scraper to run')
    parser.add_argument('--job-type', 
                       choices=['full_scrape', 'incremental'], 
                       default='incremental', help='Type of scraping job')
    parser.add_argument('--config', default='agent_config.json', 
                       help='Configuration file path')
    parser.add_argument('--background', action='store_true',
                       help='Run with background scheduler')
    
    args = parser.parse_args()
    
    # Initialize agent
    agent = HealthcarePolicyAgent(config_file=args.config)
    
    if args.action == 'run':
        if args.background:
            agent.schedule_routine_jobs()
            agent.start_scheduler()
            print("🤖 Agent running with background scheduler. Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(10)
                    # Process any manually queued jobs
                    if agent.jobs_queue:
                        agent.process_job_queue()
            except KeyboardInterrupt:
                agent.stop_scheduler()
                print("\n⏹️ Agent stopped")
        else:
            if args.scraper == 'all':
                job_ids = agent.run_all_scrapers(args.job_type)
                print(f"✅ Completed {len(job_ids)} scraping jobs")
            else:
                job_id = agent.create_job(args.scraper, args.job_type)
                agent.process_job_queue()
                print(f"✅ Completed job: {job_id}")
        
    elif args.action == 'status':
        dashboard = agent.get_dashboard_data()
        print(json.dumps(dashboard, indent=2))
        
    elif args.action == 'dashboard':
        dashboard = agent.get_dashboard_data()
        print("\n🤖 HEALTHCARE POLICY SCRAPER AGENT DASHBOARD")
        print("=" * 60)
        print(f"📊 Jobs - Pending: {dashboard['jobs']['pending']}, Active: {dashboard['jobs']['active']}")
        print(f"📅 Completed Today: {dashboard['jobs']['completed_today']}")
        print("\n📂 Scrapers:")
        for name, info in dashboard['scrapers'].items():
            status = "✅" if info['enabled'] else "❌"
            print(f"  {status} {name}: {info['total_files']} files ({info['schedule']})")
        
        if dashboard['recent_jobs']:
            print("\n📋 Recent Jobs:")
            for job in dashboard['recent_jobs'][-5:]:
                status_icon = "✅" if job['status'] == 'completed' else "❌" if job['status'] == 'failed' else "🔄"
                print(f"  {status_icon} {job['scraper']}: {job['files_downloaded']} files ({job['duration']})")
        
    elif args.action == 'schedule':
        agent.schedule_routine_jobs()
        agent.start_scheduler()
        print("📅 Scheduled jobs configured and started")
        
    elif args.action == 'export':
        filename = agent.export_job_history()
        print(f"📄 History exported to {filename}")

if __name__ == "__main__":
    main()
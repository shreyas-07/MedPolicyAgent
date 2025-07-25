#!/usr/bin/env python3
"""
Healthcare Policies ChromaDB Loader
Loads all downloaded policy PDFs into ChromaDB for unified search
"""

import os
import json
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

# PDF processing
import PyPDF2
import fitz  # PyMuPDF (fallback)

# ChromaDB and embeddings
import chromadb
from sentence_transformers import SentenceTransformer

# Progress tracking
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('chroma_loader.log'),
        logging.StreamHandler()
    ]
)

class HealthcarePolicyIndexer:
    """Loads all healthcare policies into ChromaDB for unified search"""
    
    def __init__(self, 
                 chroma_db_path="./chroma_db",
                 collection_name="healthcare_policies",
                 embedding_model="sentence-transformers/all-MiniLM-L6-v2"):
        
        self.chroma_db_path = chroma_db_path
        self.collection_name = collection_name
        
        # Get script directory for consistent paths
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Setup logging
        self.logger = logging.getLogger("HealthcarePolicyIndexer")
        
        # Initialize ChromaDB
        self.setup_chromadb()
        
        # Initialize embedding model
        self.logger.info(f"🤖 Loading embedding model: {embedding_model}")
        self.embedding_model = SentenceTransformer(embedding_model)
        
        # Track processing stats
        self.stats = {
            "total_files_found": 0,
            "files_processed": 0,
            "files_skipped": 0,
            "chunks_created": 0,
            "errors": []
        }
        
        # Policy source configurations
        self.policy_sources = {
            "humana_claims": {
                "folder": "humana_policies/claims_payment_policies",
                "type": "claims_payment",
                "provider": "humana"
            },
            "humana_medical": {
                "folder": "humana_policies/medical_policies", 
                "type": "medical",
                "provider": "humana"
            },
            "humana_pharmacy": {
                "folder": "humana_policies/pharmacy_policies",
                "type": "pharmacy", 
                "provider": "humana"
            },
            "uhc_policies": {
                "folder": "uhc_policies/policies",
                "type": "medical_drug",
                "provider": "uhc"
            },
            "uhc_rpub": {
                "folder": "uhc_policies/rpub_updates",
                "type": "rpub_updates",
                "provider": "uhc"
            }
        }
        
        self.logger.info("🚀 Healthcare Policy Indexer initialized")
    
    def setup_chromadb(self):
        """Initialize ChromaDB client and collection"""
        try:
            # Create ChromaDB client
            self.chroma_client = chromadb.PersistentClient(path=self.chroma_db_path)
            
            # Create or get collection
            try:
                self.collection = self.chroma_client.get_collection(self.collection_name)
                existing_count = self.collection.count()
                self.logger.info(f"📚 Connected to existing collection: {existing_count} documents")
            except:
                self.collection = self.chroma_client.create_collection(
                    name=self.collection_name,
                    metadata={
                        "description": "Unified Healthcare Policy Documents",
                        "created_at": datetime.now().isoformat()
                    }
                )
                self.logger.info(f"🆕 Created new collection: {self.collection_name}")
                
        except Exception as e:
            self.logger.error(f"❌ ChromaDB setup failed: {e}")
            raise
    
    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from PDF using multiple methods"""
        text = ""
        
        # Method 1: PyPDF2 (fast, good for most PDFs)
        try:
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                for page_num, page in enumerate(reader.pages):
                    try:
                        page_text = page.extract_text()
                        text += f"\n--- Page {page_num + 1} ---\n{page_text}"
                    except:
                        continue
                        
            if len(text.strip()) > 100:  # If we got good text, return it
                return text.strip()
                
        except Exception as e:
            self.logger.warning(f"PyPDF2 failed for {pdf_path}: {e}")
        
        # Method 2: PyMuPDF (fallback, better OCR)
        try:
            with fitz.open(pdf_path) as doc:
                for page_num, page in enumerate(doc):
                    try:
                        page_text = page.get_text()
                        text += f"\n--- Page {page_num + 1} ---\n{page_text}"
                    except:
                        continue
                        
        except Exception as e:
            self.logger.warning(f"PyMuPDF failed for {pdf_path}: {e}")
        
        return text.strip()
    
    def chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """Split text into overlapping chunks for better embeddings"""
        if not text or len(text) < 50:
            return []
        
        # Split by sentences first for better chunk boundaries
        sentences = re.split(r'[.!?]+', text)
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            # If adding this sentence would exceed chunk size
            if len(current_chunk) + len(sentence) > chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                
                # Start new chunk with overlap
                words = current_chunk.split()
                if len(words) > overlap:
                    overlap_text = " ".join(words[-overlap:])
                    current_chunk = overlap_text + " " + sentence
                else:
                    current_chunk = sentence
            else:
                current_chunk += " " + sentence if current_chunk else sentence
        
        # Add final chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return [chunk for chunk in chunks if len(chunk) > 50]  # Filter very small chunks
    
    def extract_metadata_from_filename(self, filepath: str, source_config: Dict) -> Dict:
        """Extract metadata from filename and path"""
        filename = Path(filepath).name
        
        metadata = {
            "source_file": filename,
            "file_path": str(filepath),
            "provider": source_config["provider"],
            "policy_type": source_config["type"],
            "indexed_at": datetime.now().isoformat(),
            "file_size": os.path.getsize(filepath) if os.path.exists(filepath) else 0
        }
        
        # Extract additional info from filename
        filename_lower = filename.lower()
        
        # Plan types
        if "commercial" in filename_lower:
            metadata["plan_type"] = "commercial"
        elif "medicare" in filename_lower:
            metadata["plan_type"] = "medicare"
        elif "medicaid" in filename_lower:
            metadata["plan_type"] = "medicaid"
        
        # Extract dates if present
        date_patterns = [
            r'(\d{4}[-_]\d{2}[-_]\d{2})',  # YYYY-MM-DD or YYYY_MM_DD
            r'(\d{2}[-_]\d{2}[-_]\d{4})',  # MM-DD-YYYY or MM_DD_YYYY
            r'(\d{1,2}[-_]\d{1,2}[-_]\d{2,4})'  # M-D-YY or MM-DD-YYYY
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, filename)
            if match:
                metadata["extracted_date"] = match.group(1)
                break
        
        # Special handling for RPUB updates
        if source_config["type"] == "rpub_updates":
            # Extract month and year from RPUB filename
            rpub_match = re.search(r'RPUB[-_]([A-Za-z]+)[-_](\d{4})', filename)
            if rpub_match:
                metadata["rpub_month"] = rpub_match.group(1)
                metadata["rpub_year"] = rpub_match.group(2)
        
        return metadata
    
    def generate_document_id(self, filepath: str, chunk_index: int) -> str:
        """Generate unique document ID"""
        # Create hash from file path for consistency
        file_hash = hashlib.md5(str(filepath).encode()).hexdigest()[:8]
        return f"{file_hash}_{chunk_index}"
    
    def is_already_indexed(self, filepath: str) -> bool:
        """Check if document is already in ChromaDB"""
        try:
            # Generate ID for first chunk
            doc_id = self.generate_document_id(filepath, 0)
            existing = self.collection.get(ids=[doc_id])
            return len(existing["ids"]) > 0
        except:
            return False
    
    def index_pdf_file(self, filepath: str, source_config: Dict) -> int:
        """Index a single PDF file into ChromaDB"""
        
        # Check if already indexed
        if self.is_already_indexed(filepath):
            self.logger.debug(f"⏩ Already indexed: {Path(filepath).name}")
            self.stats["files_skipped"] += 1
            return 0
        
        try:
            # Extract text
            text = self.extract_text_from_pdf(filepath)
            
            if not text or len(text) < 100:
                self.logger.warning(f"⚠️ No text extracted from {Path(filepath).name}")
                self.stats["files_skipped"] += 1
                return 0
            
            # Create chunks
            chunks = self.chunk_text(text)
            
            if not chunks:
                self.logger.warning(f"⚠️ No chunks created from {Path(filepath).name}")
                self.stats["files_skipped"] += 1
                return 0
            
            # Extract metadata
            base_metadata = self.extract_metadata_from_filename(filepath, source_config)
            
            # Prepare data for ChromaDB
            documents = []
            metadatas = []
            ids = []
            
            for i, chunk in enumerate(chunks):
                # Create metadata for this chunk
                chunk_metadata = base_metadata.copy()
                chunk_metadata.update({
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "chunk_length": len(chunk)
                })
                
                documents.append(chunk)
                metadatas.append(chunk_metadata)
                ids.append(self.generate_document_id(filepath, i))
            
            # Generate embeddings
            embeddings = self.embedding_model.encode(documents).tolist()
            
            # Add to ChromaDB
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            
            self.stats["files_processed"] += 1
            self.stats["chunks_created"] += len(chunks)
            
            self.logger.debug(f"✅ Indexed {Path(filepath).name}: {len(chunks)} chunks")
            return len(chunks)
            
        except Exception as e:
            error_msg = f"Error indexing {Path(filepath).name}: {e}"
            self.logger.error(f"❌ {error_msg}")
            self.stats["errors"].append(error_msg)
            return 0
    
    def index_policy_source(self, source_name: str, source_config: Dict) -> int:
        """Index all PDFs from a specific policy source"""
        folder_path = os.path.join(self.script_dir, source_config["folder"])
        
        if not os.path.exists(folder_path):
            self.logger.warning(f"⚠️ Folder not found: {folder_path}")
            return 0
        
        # Find all PDF files
        pdf_files = list(Path(folder_path).glob("*.pdf"))
        
        if not pdf_files:
            self.logger.info(f"📁 No PDFs found in {source_config['folder']}")
            return 0
        
        self.logger.info(f"📄 Processing {len(pdf_files)} PDFs from {source_name}")
        
        total_chunks = 0
        
        # Process files with progress bar
        for pdf_file in tqdm(pdf_files, desc=f"Indexing {source_name}", leave=False):
            chunks_added = self.index_pdf_file(str(pdf_file), source_config)
            total_chunks += chunks_added
        
        self.logger.info(f"✅ {source_name}: {total_chunks} chunks indexed")
        return total_chunks
    
    def index_all_policies(self, sources: List[str] = None):
        """Index all policies from specified sources"""
        
        if sources is None:
            sources = list(self.policy_sources.keys())
        
        self.logger.info(f"🚀 Starting indexing for sources: {sources}")
        
        # Count total files first
        total_files = 0
        for source_name in sources:
            if source_name in self.policy_sources:
                source_config = self.policy_sources[source_name]
                folder_path = os.path.join(self.script_dir, source_config["folder"])
                if os.path.exists(folder_path):
                    pdf_count = len(list(Path(folder_path).glob("*.pdf")))
                    total_files += pdf_count
                    self.logger.info(f"📁 {source_name}: {pdf_count} PDFs")
        
        self.stats["total_files_found"] = total_files
        
        if total_files == 0:
            self.logger.warning("⚠️ No PDF files found to index")
            return
        
        # Process each source
        overall_progress = tqdm(sources, desc="Processing Sources")
        
        for source_name in overall_progress:
            if source_name not in self.policy_sources:
                self.logger.warning(f"⚠️ Unknown source: {source_name}")
                continue
            
            overall_progress.set_description(f"Processing {source_name}")
            source_config = self.policy_sources[source_name]
            
            self.index_policy_source(source_name, source_config)
        
        overall_progress.close()
        
        # Print final summary
        self.print_summary()
    
    def print_summary(self):
        """Print indexing summary"""
        print(f"\n{'='*60}")
        print("📊 INDEXING SUMMARY")
        print(f"{'='*60}")
        print(f"📁 Total files found: {self.stats['total_files_found']}")
        print(f"✅ Files processed: {self.stats['files_processed']}")
        print(f"⏩ Files skipped: {self.stats['files_skipped']}")
        print(f"📝 Chunks created: {self.stats['chunks_created']}")
        print(f"❌ Errors: {len(self.stats['errors'])}")
        
        if self.stats['errors']:
            print(f"\n⚠️ Error details (first 5):")
            for error in self.stats['errors'][:5]:
                print(f"   • {error}")
        
        # Collection stats
        try:
            total_docs = self.collection.count()
            print(f"\n📚 Total documents in ChromaDB: {total_docs}")
        except:
            pass
        
        print(f"\n🎉 Indexing complete!")
        print(f"💾 ChromaDB saved to: {self.chroma_db_path}")
    
    def search_policies(self, query: str, n_results: int = 5, provider: str = None, policy_type: str = None):
        """Search policies in ChromaDB"""
        
        # Build where clause for filtering
        where_clause = {}
        if provider:
            where_clause["provider"] = provider
        if policy_type:
            where_clause["policy_type"] = policy_type
        
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_clause if where_clause else None
        )
        
        print(f"\n🔍 Search: '{query}'")
        if provider or policy_type:
            filters = []
            if provider:
                filters.append(f"provider={provider}")
            if policy_type:
                filters.append(f"type={policy_type}")
            print(f"🏷️ Filters: {', '.join(filters)}")
        
        if not results['documents'][0]:
            print("❌ No results found")
            return
        
        print(f"\n📋 Found {len(results['documents'][0])} results:")
        print("-" * 80)
        
        for i, (doc, metadata, distance) in enumerate(zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        )):
            relevance = 1 - distance
            
            print(f"\n{i+1}. {metadata['source_file']}")
            print(f"   📂 Provider: {metadata['provider'].upper()}")
            print(f"   📋 Type: {metadata['policy_type']}")
            print(f"   📊 Relevance: {relevance:.3f}")
            print(f"   📄 Preview: {doc[:200]}...")
            
            if 'plan_type' in metadata:
                print(f"   🏥 Plan: {metadata['plan_type']}")
            if 'extracted_date' in metadata:
                print(f"   📅 Date: {metadata['extracted_date']}")
    
    def get_collection_stats(self):
        """Get detailed collection statistics"""
        try:
            total_count = self.collection.count()
            
            # Get sample of metadata to analyze
            sample_size = min(1000, total_count)
            if sample_size > 0:
                sample_data = self.collection.get(limit=sample_size)
                metadatas = sample_data['metadatas']
                
                # Count by provider
                provider_counts = {}
                type_counts = {}
                
                for meta in metadatas:
                    provider = meta.get('provider', 'unknown')
                    policy_type = meta.get('policy_type', 'unknown')
                    
                    provider_counts[provider] = provider_counts.get(provider, 0) + 1
                    type_counts[policy_type] = type_counts.get(policy_type, 0) + 1
                
                print(f"\n📊 COLLECTION STATISTICS")
                print(f"{'='*50}")
                print(f"📚 Total documents: {total_count}")
                print(f"📁 Sample analyzed: {sample_size}")
                
                print(f"\n📋 By Provider:")
                for provider, count in sorted(provider_counts.items()):
                    percentage = (count / sample_size) * 100
                    estimated_total = int((count / sample_size) * total_count)
                    print(f"   {provider.upper()}: {estimated_total} docs (~{percentage:.1f}%)")
                
                print(f"\n📂 By Policy Type:")
                for policy_type, count in sorted(type_counts.items()):
                    percentage = (count / sample_size) * 100
                    estimated_total = int((count / sample_size) * total_count)
                    print(f"   {policy_type}: {estimated_total} docs (~{percentage:.1f}%)")
                    
        except Exception as e:
            print(f"❌ Error getting stats: {e}")
    
    def export_index_metadata(self, filename: str = None):
        """Export indexing metadata to JSON"""
        if filename is None:
            filename = f"chroma_index_metadata_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            # Get collection info
            total_docs = self.collection.count()
            
            export_data = {
                "export_timestamp": datetime.now().isoformat(),
                "chroma_db_path": self.chroma_db_path,
                "collection_name": self.collection_name,
                "total_documents": total_docs,
                "indexing_stats": self.stats,
                "policy_sources": self.policy_sources
            }
            
            with open(filename, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            print(f"📄 Index metadata exported to {filename}")
            return filename
            
        except Exception as e:
            self.logger.error(f"❌ Export failed: {e}")

def main():
    """CLI interface for the indexer"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Healthcare Policy ChromaDB Indexer')
    parser.add_argument('--action', 
                       choices=['index', 'search', 'stats', 'export'], 
                       default='index', help='Action to perform')
    parser.add_argument('--sources', nargs='+',
                       choices=['humana_claims', 'humana_medical', 'humana_pharmacy', 'uhc_policies', 'uhc_rpub', 'all'],
                       default=['all'], help='Which sources to index')
    parser.add_argument('--query', type=str, help='Search query')
    parser.add_argument('--provider', choices=['humana', 'uhc'], help='Filter by provider')
    parser.add_argument('--policy-type', help='Filter by policy type')
    parser.add_argument('--chroma-path', default='./chroma_db', help='ChromaDB path')
    parser.add_argument('--collection', default='healthcare_policies', help='Collection name')
    
    args = parser.parse_args()
    
    # Initialize indexer
    indexer = HealthcarePolicyIndexer(
        chroma_db_path=args.chroma_path,
        collection_name=args.collection
    )
    
    if args.action == 'index':
        sources = None if 'all' in args.sources else args.sources
        indexer.index_all_policies(sources)
        
    elif args.action == 'search':
        if not args.query:
            print("❌ Search query required. Use --query 'your search'")
            return
        
        indexer.search_policies(
            query=args.query,
            provider=args.provider,
            policy_type=args.policy_type
        )
        
    elif args.action == 'stats':
        indexer.get_collection_stats()
        
    elif args.action == 'export':
        indexer.export_index_metadata()

if __name__ == "__main__":
    main()
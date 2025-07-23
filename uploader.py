#!/usr/bin/env python3

import os
import json
import time
import logging
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

class VectorStoreUploader:
    def __init__(self, articles_dir="./articles"):
        self.articles_dir = articles_dir
        self.vector_store_info_file = "./vector_store_info.json"

    def upload_files_to_openai(self, article_files=None):
        logger.info("=== Uploading Files to OpenAI ===")

        uploaded_files = {}

        # Get files to upload
        if article_files is None:
            # Upload all markdown files from directory
            md_files = list(Path(self.articles_dir).glob("*.md"))
            if not md_files:
                logger.info(f"No markdown files found in {self.articles_dir}")
                return {}
        else:
            # Upload specific files
            md_files = article_files

        logger.info(f"Found {len(md_files)} files to upload")

        # Upload each file
        for i, file_path in enumerate(md_files, 1):
            try:
                if isinstance(file_path, str):
                    file_path = Path(file_path)

                logger.info(f"[{i}/{len(md_files)}] Uploading: {file_path.name}")

                with open(file_path, 'rb') as f:
                    file_response = client.files.create(
                        file=f,
                        purpose='assistants'
                    )

                # Extract article ID from filename (assuming format: slug-{article_id}.md)
                filename_parts = file_path.stem.split('-')
                article_id = filename_parts[-1]  # Last part should be article ID

                uploaded_files[article_id] = file_response.id

                logger.info(f"    File ID: {file_response.id}")
                logger.info(f"    Size: {file_response.bytes} bytes")

                # Small delay to be respectful to API
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"    Error uploading {file_path.name}: {e}")

        logger.info(f"Successfully uploaded {len(uploaded_files)} files")
        return uploaded_files

    def upload_article_content(self, article_id, markdown_content):
        """Upload a single article's markdown content directly"""
        try:
            logger.info(f"Uploading article {article_id} content to OpenAI...")

            file_response = client.files.create(
                file=('article.md', markdown_content.encode('utf-8')),
                purpose='assistants'
            )

            logger.info(f"    Uploaded as file: {file_response.id}")
            return file_response.id

        except Exception as e:
            logger.error(f"Error uploading article {article_id}: {e}")
            return None

    def create_vector_store(self, name="OptiSigns Support Articles"):
        logger.info(f"=== Creating Vector Store: {name} ===")

        try:
            vector_store = client.vector_stores.create(
                name=name,
                expires_after={
                    "anchor": "last_active_at",
                    "days": 365  # Keep for 1 year
                }
            )

            logger.info(f"Vector Store created")
            logger.info(f"  ID: {vector_store.id}")
            logger.info(f"  Name: {vector_store.name}")
            logger.info(f"  Status: {vector_store.status}")

            return vector_store

        except Exception as e:
            logger.error(f"Error creating vector store: {e}")
            return None

    def attach_files_to_vector_store(self, vector_store_id, file_ids):
        logger.info(f"=== Attaching Files to Vector Store ===")

        if not file_ids:
            logger.info("No files to attach")
            return None

        try:
            # Convert dict to list if needed
            if isinstance(file_ids, dict):
                file_ids_list = list(file_ids.values())
            else:
                file_ids_list = file_ids

            # Batch attach all files at once
            vector_store_files = client.vector_stores.file_batches.create(
                vector_store_id=vector_store_id,
                file_ids=file_ids_list
            )

            logger.info(f"Batch attachment initiated")
            logger.info(f"  Batch ID: {vector_store_files.id}")
            logger.info(f"  Status: {vector_store_files.status}")
            logger.info(f"  Files in batch: {vector_store_files.file_counts.total}")

            # Wait for processing to complete
            logger.info("Waiting for files to be processed...")

            while vector_store_files.status in ['in_progress', 'cancelling']:
                time.sleep(2)
                vector_store_files = client.vector_stores.file_batches.retrieve(
                    vector_store_id=vector_store_id,
                    batch_id=vector_store_files.id
                )
                logger.info(f"  Status: {vector_store_files.status}")

            # Get final results
            if vector_store_files.status == 'completed':
                logger.info(f"All files processed successfully")
                logger.info(f"  Completed: {vector_store_files.file_counts.completed}")
                logger.info(f"  Failed: {vector_store_files.file_counts.failed}")

                return vector_store_files
            else:
                logger.error(f"Processing failed with status: {vector_store_files.status}")
                return None

        except Exception as e:
            logger.error(f"Error attaching files: {e}")
            return None

    def get_vector_store_stats(self, vector_store_id, uploaded_files):
        try:
            vector_store = client.vector_stores.retrieve(vector_store_id)

            logger.info(f"=== Vector Store Statistics ===")
            logger.info(f"Vector Store ID: {vector_store.id}")
            logger.info(f"Name: {vector_store.name}")
            logger.info(f"Status: {vector_store.status}")
            logger.info(f"File counts:")
            logger.info(f"  Total files: {vector_store.file_counts.total}")
            logger.info(f"  Completed: {vector_store.file_counts.completed}")
            logger.info(f"  Failed: {vector_store.file_counts.failed}")
            logger.info(f"  In progress: {vector_store.file_counts.in_progress}")
            logger.info(f"Usage bytes: {vector_store.usage_bytes:,}")

            # Estimate chunks based on usage
            avg_chars_per_chunk = 3200
            estimated_chunks = vector_store.usage_bytes // avg_chars_per_chunk if vector_store.usage_bytes > 0 else 0
            logger.info(f"Estimated chunks: ~{estimated_chunks} (assuming ~800 tokens per chunk)")

            return {
                'vector_store_id': vector_store.id,
                'total_files': vector_store.file_counts.total,
                'completed_files': vector_store.file_counts.completed,
                'failed_files': vector_store.file_counts.failed,
                'usage_bytes': vector_store.usage_bytes,
                'estimated_chunks': estimated_chunks
            }

        except Exception as e:
            logger.error(f"Error getting vector store stats: {e}")
            return None

    def save_vector_store_info(self, vector_store_id, stats=None):
        data = {
            'vector_store_id': vector_store_id,
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'last_updated': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        if stats:
            data.update(stats)

        with open(self.vector_store_info_file, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"Vector Store info saved to {self.vector_store_info_file}")

    def load_vector_store_info(self):
        if os.path.exists(self.vector_store_info_file):
            with open(self.vector_store_info_file, 'r') as f:
                return json.load(f)
        return None

    def upload_all_articles(self):
        logger.info("=== OpenAI Vector Store Upload Process ===")

        # Check for API key
        if not os.getenv('OPENAI_API_KEY'):
            logger.error("ERROR: OPENAI_API_KEY not found in environment variables!")
            logger.error("Please check your .env file or environment setup.")
            return

        # Debug: Check OpenAI library version
        import openai
        logger.info(f"OpenAI library version: {openai.__version__}")

        # Check if articles directory exists
        if not os.path.exists(self.articles_dir):
            logger.error(f"Articles directory '{self.articles_dir}' not found!")
            logger.error("Make sure you've run the scraper script first.")
            return

        try:
            # Step 1: Upload files to OpenAI
            uploaded_files = self.upload_files_to_openai()

            if not uploaded_files:
                logger.info("No files were uploaded. Exiting.")
                return

            # Step 2: Create Vector Store
            vector_store = self.create_vector_store()

            if not vector_store:
                logger.error("Failed to create vector store. Exiting.")
                return

            # Step 3: Attach files to Vector Store
            batch_result = self.attach_files_to_vector_store(vector_store.id, uploaded_files)

            if not batch_result:
                logger.error("Failed to attach files to vector store.")
                return

            # Step 4: Get final statistics
            stats = self.get_vector_store_stats(vector_store.id, uploaded_files)

            # Step 5: Save vector store info
            self.save_vector_store_info(vector_store.id, stats)

            # Summary
            logger.info("=" * 50)
            logger.info("UPLOAD SUMMARY")
            logger.info("=" * 50)
            logger.info(f"Files uploaded: {len(uploaded_files)}")
            logger.info(f"Files processed: {stats['completed_files'] if stats else 'Unknown'}")
            logger.info(f"Estimated chunks: ~{stats['estimated_chunks'] if stats else 'Unknown'}")
            logger.info(f"Vector Store ID: {vector_store.id}")
            logger.info(f"Total storage used: {stats['usage_bytes']:,} bytes" if stats else "")
            logger.info("=== Upload completed successfully ===")

            return {
                'vector_store_id': vector_store.id,
                'uploaded_files': uploaded_files,
                'stats': stats
            }

        except Exception as e:
            logger.error(f"Upload failed: {e}")
            raise e

    def delete_files_from_openai(self, file_ids):
        """Delete specific files from OpenAI storage"""
        logger.info(f"Deleting {len(file_ids)} files from OpenAI...")
        deleted_count = 0

        for file_id in file_ids:
            try:
                client.files.delete(file_id)
                deleted_count += 1
                logger.info(f"  Deleted file: {file_id}")
                time.sleep(0.2)  # Rate limiting
            except Exception as e:
                logger.error(f"  Failed to delete file {file_id}: {e}")

        logger.info(f"Successfully deleted {deleted_count} files")
        return deleted_count

    def remove_files_from_vector_store(self, vector_store_id, file_ids):
        """Remove specific files from vector store"""
        logger.info(f"Removing {len(file_ids)} files from vector store...")
        removed_count = 0

        for file_id in file_ids:
            try:
                client.vector_stores.files.delete(
                    vector_store_id=vector_store_id,
                    file_id=file_id
                )
                removed_count += 1
                logger.info(f"  Removed file from vector store: {file_id}")
                time.sleep(0.2)  # Rate limiting
            except Exception as e:
                logger.error(f"  Failed to remove file {file_id} from vector store: {e}")

        logger.info(f"Successfully removed {removed_count} files from vector store")
        return removed_count

def main():
    uploader = VectorStoreUploader()
    result = uploader.upload_all_articles()

    if result:
        logger.info(f"Upload complete. Vector Store ID: {result['vector_store_id']}")
    else:
        logger.error("Upload failed.")

if __name__ == "__main__":
    main()
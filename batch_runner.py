#!/usr/bin/env python3

import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from scraper import ZendeskScraper
from uploader import VectorStoreUploader

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BatchRunner:
    def __init__(self):
        self.last_run_file = "./last_run.txt"
        self.file_mapping_file = "./file_mapping.json"
        self.articles_dir = "./articles"

        # Initialize modules
        self.scraper = ZendeskScraper()
        self.uploader = VectorStoreUploader()

        # Load persistent state
        self.last_run_timestamp = self.load_last_run_timestamp()
        self.file_mapping = self.load_file_mapping()
        self.vector_store_id = self.load_vector_store_id()

    def load_last_run_timestamp(self):
        """Load the timestamp of the last successful run"""
        if os.path.exists(self.last_run_file):
            with open(self.last_run_file, 'r') as f:
                return f.read().strip()
        return None

    def save_last_run_timestamp(self, timestamp):
        """Save the timestamp of the current run"""
        with open(self.last_run_file, 'w') as f:
            f.write(timestamp)
        logger.info(f"Saved last run timestamp: {timestamp}")

    def load_file_mapping(self):
        """Load the article_id -> file_id mapping"""
        if os.path.exists(self.file_mapping_file):
            with open(self.file_mapping_file, 'r') as f:
                return json.load(f)
        return {}

    def save_file_mapping(self):
        """Save the article_id -> file_id mapping"""
        with open(self.file_mapping_file, 'w') as f:
            json.dump(self.file_mapping, f, indent=2)
        logger.info("Saved file mapping")

    def load_vector_store_id(self):
        """Load vector store ID from uploader's info file"""
        vector_store_info = self.uploader.load_vector_store_info()
        if vector_store_info:
            return vector_store_info.get('vector_store_id')
        return None

    def is_first_run(self):
        """Check if this is the first run (no state files exist)"""
        return (not os.path.exists(self.last_run_file) or
                not os.path.exists(self.file_mapping_file) or
                not self.file_mapping)

    def detect_changes(self, articles):
        """Detect new, updated, deleted, and unchanged articles"""
        logger.info("=== Detecting Article Changes ===")

        changes = {
            'new': [],
            'updated': [],
            'deleted': [],
            'unchanged': []
        }

        # Get current article IDs
        current_article_ids = {str(article['id']) for article in articles}
        tracked_article_ids = set(self.file_mapping.keys())

        # Find deleted articles (in mapping but not in current articles)
        deleted_ids = tracked_article_ids - current_article_ids
        changes['deleted'] = list(deleted_ids)

        # Categorize current articles
        for article in articles:
            article_id = str(article['id'])
            article_updated_at = article.get('updated_at')

            if article_id not in self.file_mapping:
                # New article
                changes['new'].append(article)
            elif self.last_run_timestamp and article_updated_at > self.last_run_timestamp:
                # Updated article
                changes['updated'].append(article)
            else:
                # Unchanged article
                changes['unchanged'].append(article)

        # Log results
        logger.info(f"Change detection results:")
        logger.info(f"  New: {len(changes['new'])} articles")
        logger.info(f"  Updated: {len(changes['updated'])} articles")
        logger.info(f"  Deleted: {len(changes['deleted'])} articles")
        logger.info(f"  Unchanged: {len(changes['unchanged'])} articles")

        return changes

    def process_new_articles(self, new_articles):
        """Handle new articles: scrape -> save -> batch upload -> batch add to vector store"""
        logger.info(f"=== Processing {len(new_articles)} New Articles ===")

        # Step 1: Process all articles to markdown files
        logger.info("Step 1: Processing articles to markdown files...")
        successfully_saved = []
        failed_articles = []

        for article in new_articles:
            article_id = str(article['id'])
            article_title = article['title']

            logger.info(f"Processing new article {article_id}: {article_title}")

            try:
                # Fetch and save article
                article_data = self.scraper.fetch_article_content(article['id'])
                if not article_data:
                    raise Exception("Failed to fetch article content")

                saved_file = self.scraper.save_article_as_markdown(article_data)
                successfully_saved.append({
                    'article_id': article_id,
                    'file_path': saved_file,
                    'title': article_title
                })
                logger.info(f"  Saved: {os.path.basename(saved_file)}")

            except Exception as e:
                logger.error(f"  Failed to process article {article_id}: {e}")
                failed_articles.append({
                    'id': article_id,
                    'title': article_title,
                    'error': str(e)
                })

        if not successfully_saved:
            logger.info("No articles were successfully saved")
            return {}, failed_articles

        # Step 2: Batch upload all files to OpenAI
        logger.info(f"Step 2: Batch uploading {len(successfully_saved)} files to OpenAI...")
        file_paths = [item['file_path'] for item in successfully_saved]

        try:
            uploaded_files = self.uploader.upload_files_to_openai(file_paths)
            logger.info(f"  Successfully uploaded {len(uploaded_files)} files")
            time.sleep(1)  # Single delay for entire batch

        except Exception as e:
            logger.error(f"  Batch upload failed: {e}")
            # All articles fail if batch upload fails
            for item in successfully_saved:
                failed_articles.append({
                    'id': item['article_id'],
                    'title': item['title'],
                    'error': f'Batch upload failed: {e}'
                })
            return {}, failed_articles

        # Step 3: Ensure vector store exists
        if not self.vector_store_id:
            logger.info("Step 3: Creating vector store...")
            vector_store = self.uploader.create_vector_store()
            if not vector_store:
                logger.error("Failed to create vector store")
                return {}, failed_articles
            self.vector_store_id = vector_store.id
            self.uploader.save_vector_store_info(self.vector_store_id)

        # Step 4: Batch attach all files to vector store
        logger.info(f"Step 4: Batch attaching {len(uploaded_files)} files to vector store...")
        file_ids = list(uploaded_files.values())

        try:
            batch_result = self.uploader.attach_files_to_vector_store(
                self.vector_store_id, file_ids
            )
            if not batch_result:
                raise Exception("Failed to attach files to vector store")

            logger.info(f"  Successfully attached {len(file_ids)} files to vector store")
            time.sleep(1)  # Single delay for entire batch

        except Exception as e:
            logger.error(f"  Batch attach failed: {e}")
            # All articles fail if batch attach fails
            for item in successfully_saved:
                failed_articles.append({
                    'id': item['article_id'],
                    'title': item['title'],
                    'error': f'Batch attach failed: {e}'
                })
            return {}, failed_articles

        logger.info(f"New articles processing complete: {len(uploaded_files)} success, {len(failed_articles)} failed")
        return uploaded_files, failed_articles

    def process_updated_articles(self, updated_articles):
        """Handle updated articles: scrape -> overwrite -> batch delete old -> batch upload new -> batch add to vector store"""
        logger.info(f"=== Processing {len(updated_articles)} Updated Articles ===")

        # Step 1: Process all articles to markdown files and collect old file IDs
        logger.info("Step 1: Processing articles to markdown files...")
        successfully_saved = []
        old_file_ids = []
        failed_articles = []

        for article in updated_articles:
            article_id = str(article['id'])
            article_title = article['title']
            old_file_id = self.file_mapping.get(article_id)

            logger.info(f"Processing updated article {article_id}: {article_title}")

            if not old_file_id:
                logger.error(f"  No old file_id found for article {article_id}")
                failed_articles.append({
                    'id': article_id,
                    'title': article_title,
                    'error': 'No old file_id in mapping'
                })
                continue

            try:
                # Fetch and overwrite article
                article_data = self.scraper.fetch_article_content(article['id'])
                if not article_data:
                    raise Exception("Failed to fetch article content")

                saved_file = self.scraper.save_article_as_markdown(article_data)
                successfully_saved.append({
                    'article_id': article_id,
                    'file_path': saved_file,
                    'title': article_title,
                    'old_file_id': old_file_id
                })
                old_file_ids.append(old_file_id)
                logger.info(f"  Overwrote: {os.path.basename(saved_file)}")

            except Exception as e:
                logger.error(f"  Failed to process article {article_id}: {e}")
                failed_articles.append({
                    'id': article_id,
                    'title': article_title,
                    'error': str(e)
                })

        if not successfully_saved:
            logger.info("No articles were successfully saved")
            return {}, failed_articles

        # Step 2: Batch remove old files from vector store
        logger.info(f"Step 2: Batch removing {len(old_file_ids)} old files from vector store...")
        try:
            self.uploader.remove_files_from_vector_store(self.vector_store_id, old_file_ids)
            logger.info(f"  Successfully removed {len(old_file_ids)} files from vector store")
            time.sleep(1)  # Single delay for entire batch

        except Exception as e:
            logger.error(f"  Batch remove from vector store failed: {e}")
            # Continue anyway - we'll still try to clean up

        # Step 3: Batch delete old files from OpenAI storage
        logger.info(f"Step 3: Batch deleting {len(old_file_ids)} old files from OpenAI...")
        try:
            self.uploader.delete_files_from_openai(old_file_ids)
            logger.info(f"  Successfully deleted {len(old_file_ids)} files from OpenAI")
            time.sleep(1)  # Single delay for entire batch

        except Exception as e:
            logger.error(f"  Batch delete from OpenAI failed: {e}")
            # Continue anyway - we'll still upload new versions

        # Step 4: Batch upload all new versions to OpenAI
        logger.info(f"Step 4: Batch uploading {len(successfully_saved)} new files to OpenAI...")
        file_paths = [item['file_path'] for item in successfully_saved]

        try:
            uploaded_files = self.uploader.upload_files_to_openai(file_paths)
            logger.info(f"  Successfully uploaded {len(uploaded_files)} files")
            time.sleep(1)  # Single delay for entire batch

        except Exception as e:
            logger.error(f"  Batch upload failed: {e}")
            # All articles fail if batch upload fails
            for item in successfully_saved:
                failed_articles.append({
                    'id': item['article_id'],
                    'title': item['title'],
                    'error': f'Batch upload failed: {e}'
                })
            return {}, failed_articles

        # Step 5: Batch attach all new files to vector store
        logger.info(f"Step 5: Batch attaching {len(uploaded_files)} new files to vector store...")
        file_ids = list(uploaded_files.values())

        try:
            batch_result = self.uploader.attach_files_to_vector_store(
                self.vector_store_id, file_ids
            )
            if not batch_result:
                raise Exception("Failed to attach files to vector store")

            logger.info(f"  Successfully attached {len(file_ids)} files to vector store")
            time.sleep(1)  # Single delay for entire batch

        except Exception as e:
            logger.error(f"  Batch attach failed: {e}")
            # All articles fail if batch attach fails
            for item in successfully_saved:
                failed_articles.append({
                    'id': item['article_id'],
                    'title': item['title'],
                    'error': f'Batch attach failed: {e}'
                })
            return {}, failed_articles

        logger.info(f"Updated articles processing complete: {len(uploaded_files)} success, {len(failed_articles)} failed")
        return uploaded_files, failed_articles

    def process_deleted_articles(self, deleted_article_ids):
        """Handle deleted articles: batch delete .md -> batch remove from vector store -> batch delete from OpenAI"""
        logger.info(f"=== Processing {len(deleted_article_ids)} Deleted Articles ===")

        # Step 1: Collect file info and delete .md files
        logger.info("Step 1: Deleting .md files from disk...")
        file_ids_to_remove = []
        successfully_deleted_files = []
        failed_articles = []

        for article_id in deleted_article_ids:
            file_id = self.file_mapping.get(article_id)

            logger.info(f"Processing deleted article {article_id}")

            if not file_id:
                logger.warning(f"  No file_id found for article {article_id}")
                continue

            try:
                # Find and delete .md file from disk
                articles_path = Path(self.articles_dir)
                md_files = list(articles_path.glob(f"*-{article_id}.md"))

                for md_file in md_files:
                    md_file.unlink()
                    logger.info(f"  Deleted file: {md_file.name}")

                file_ids_to_remove.append(file_id)
                successfully_deleted_files.append(article_id)

            except Exception as e:
                logger.error(f"  Failed to delete files for article {article_id}: {e}")
                failed_articles.append({
                    'id': article_id,
                    'error': str(e)
                })

        if not file_ids_to_remove:
            logger.info("No files to remove from OpenAI/vector store")
            return successfully_deleted_files, failed_articles

        # Step 2: Batch remove from vector store
        logger.info(f"Step 2: Batch removing {len(file_ids_to_remove)} files from vector store...")
        try:
            self.uploader.remove_files_from_vector_store(self.vector_store_id, file_ids_to_remove)
            logger.info(f"  Successfully removed {len(file_ids_to_remove)} files from vector store")
            time.sleep(1)  # Single delay for entire batch

        except Exception as e:
            logger.error(f"  Batch remove from vector store failed: {e}")
            # Continue anyway - we'll still try to delete from OpenAI

        # Step 3: Batch delete from OpenAI storage
        logger.info(f"Step 3: Batch deleting {len(file_ids_to_remove)} files from OpenAI...")
        try:
            self.uploader.delete_files_from_openai(file_ids_to_remove)
            logger.info(f"  Successfully deleted {len(file_ids_to_remove)} files from OpenAI")
            time.sleep(1)  # Single delay for entire batch

        except Exception as e:
            logger.error(f"  Batch delete from OpenAI failed: {e}")
            # Continue anyway - articles are still considered successfully processed

        logger.info(f"Deleted articles processing complete: {len(successfully_deleted_files)} success, {len(failed_articles)} failed")
        return successfully_deleted_files, failed_articles

    def run_full_sync(self, max_articles=40):
        """Run complete sync (first-time setup)"""
        logger.info("=== OptiBot Full Sync Started ===")

        try:
            # Step 1: Use existing scraper to get all articles
            logger.info("Step 1: Scraping all articles...")
            successful_articles = self.scraper.scrape_all_articles(max_articles)

            if not successful_articles:
                logger.error("No articles were scraped. Exiting.")
                return False

            # Step 2: Use existing uploader to create vector store
            logger.info("Step 2: Uploading to vector store...")
            upload_result = self.uploader.upload_all_articles()

            if not upload_result:
                logger.error("Upload failed. Exiting.")
                return False

            # Step 3: Create file mapping from successful articles
            logger.info("Step 3: Creating file mapping...")
            self.file_mapping = upload_result['uploaded_files']
            self.save_file_mapping()

            # Step 4: Save vector store ID
            self.vector_store_id = upload_result['vector_store_id']

            # Step 5: Save timestamp
            current_timestamp = datetime.now().isoformat()
            self.save_last_run_timestamp(current_timestamp)

            logger.info("=" * 60)
            logger.info("FULL SYNC SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Articles processed: {len(successful_articles)}")
            logger.info(f"Files uploaded: {len(self.file_mapping)}")
            logger.info(f"Vector store ID: {self.vector_store_id}")
            logger.info("=== Full sync completed successfully ===")

            return True

        except Exception as e:
            logger.error(f"Full sync failed with error: {e}")
            return False

    def run_delta_sync(self, max_articles=40):
        """Run incremental sync (delta changes only)"""
        logger.info("=== OptiBot Delta Sync Started ===")

        # Check if this is first run
        if self.is_first_run():
            logger.info("First run detected - performing full sync...")
            return self.run_full_sync(max_articles)

        logger.info(f"Last successful run: {self.last_run_timestamp}")

        try:
            # Step 1: Fetch current articles from Zendesk
            logger.info("Step 1: Fetching articles from Zendesk...")
            articles = self.scraper.fetch_articles_list(max_articles)

            if not articles:
                logger.error("Failed to fetch articles from Zendesk")
                return False

            # Step 2: Detect changes
            logger.info("Step 2: Detecting changes...")
            changes = self.detect_changes(articles)

            # Check if any changes exist
            total_changes = len(changes['new']) + len(changes['updated']) + len(changes['deleted'])
            if total_changes == 0:
                logger.info("No changes detected - sync completed successfully")
                return True

            # Initialize counters for logging
            added_count = updated_count = deleted_count = 0

            # Step 3: Process new articles
            if changes['new']:
                logger.info("Step 3: Processing new articles...")
                new_processed, new_failed = self.process_new_articles(changes['new'])
                added_count = len(new_processed)

                # Update file mapping with new articles
                self.file_mapping.update(new_processed)

            # Step 4: Process updated articles
            if changes['updated']:
                logger.info("Step 4: Processing updated articles...")
                updated_processed, updated_failed = self.process_updated_articles(changes['updated'])
                updated_count = len(updated_processed)

                # Update file mapping with new file IDs
                self.file_mapping.update(updated_processed)

            # Step 5: Process deleted articles
            if changes['deleted']:
                logger.info("Step 5: Processing deleted articles...")
                deleted_processed, deleted_failed = self.process_deleted_articles(changes['deleted'])
                deleted_count = len(deleted_processed)

                # Remove deleted articles from mapping
                for article_id in deleted_processed:
                    if article_id in self.file_mapping:
                        del self.file_mapping[article_id]

            # Step 6: Save updated state
            logger.info("Step 6: Saving updated state...")
            self.save_file_mapping()

            current_timestamp = datetime.now().isoformat()
            self.save_last_run_timestamp(current_timestamp)

            # Final summary
            logger.info("=" * 60)
            logger.info("DELTA SYNC SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Added: {added_count} articles")
            logger.info(f"Updated: {updated_count} articles")
            logger.info(f"Deleted: {deleted_count} articles")
            logger.info(f"Skipped: {len(changes['unchanged'])} articles (unchanged)")
            logger.info(f"Total files processed: {added_count + updated_count}")
            logger.info(f"Total files removed: {deleted_count}")
            logger.info(f"Vector store ID: {self.vector_store_id}")
            logger.info("=== Delta sync completed successfully ===")

            return True

        except Exception as e:
            logger.error(f"Delta sync failed with error: {e}")
            return False

def main():
    import argparse

    parser = argparse.ArgumentParser(description='OptiBot Batch Runner')
    parser.add_argument('--force-full', action='store_true',
                        help='Force full sync (ignores existing state)')

    args = parser.parse_args()

    runner = BatchRunner()

    # Always process 40 articles
    max_articles = 40

    # Always run delta sync - it auto-detects first run
    if args.force_full:
        success = runner.run_full_sync(max_articles)
    else:
        success = runner.run_delta_sync(max_articles)

    if success:
        logger.info("Batch run completed successfully")
        exit(0)
    else:
        logger.error("Batch run failed")
        exit(1)

if __name__ == "__main__":
    main()
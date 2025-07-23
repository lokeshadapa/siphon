#!/usr/bin/env python3

import requests
import html2text
import re
import os
import html
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ZendeskScraper:
    def __init__(self, base_url="https://support.optisigns.com/api/v2/help_center"):
        self.base_url = base_url
        self.output_dir = "./articles"

    def fetch_articles_list(self, max_articles=40):
        """Fetch list of articles from Zendesk API"""
        logger.info("Fetching articles list from Zendesk...")
        articles = []
        page = 1

        while len(articles) < max_articles:
            url = f"{self.base_url}/articles.json?page={page}"

            try:
                logger.info(f"  Fetching page {page}...")
                response = requests.get(url)
                response.raise_for_status()
                data = response.json()

                page_articles = data.get('articles', [])
                if not page_articles:
                    logger.info(f"  No more articles found on page {page}")
                    break

                articles.extend(page_articles)
                logger.info(f"  Got {len(page_articles)} articles from page {page}")
                page += 1

            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching articles from page {page}: {e}")
                break

        final_articles = articles[:max_articles]
        logger.info(f"Selected {len(final_articles)} articles to process")
        return final_articles

    def fetch_article_content(self, article_id):
        """Fetch full content of a specific article"""
        url = f"{self.base_url}/articles/{article_id}.json"

        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()['article']
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching article {article_id}: {e}")
            return None

    def clean_html_content(self, html_content):
        """Clean HTML content while preserving code blocks"""
        # Store code blocks temporarily to protect them
        code_blocks = {}
        code_counter = 0

        # Extract and store <pre> blocks
        def store_pre_block(match):
            nonlocal code_counter
            placeholder = f"PRESERVED_PRE_BLOCK_{code_counter}"
            code_blocks[placeholder] = match.group(0)
            code_counter += 1
            return placeholder

        # Extract and store <code> blocks
        def store_code_block(match):
            nonlocal code_counter
            placeholder = f"PRESERVED_CODE_BLOCK_{code_counter}"
            code_blocks[placeholder] = match.group(0)
            code_counter += 1
            return placeholder

        # Temporarily replace code blocks with placeholders
        html_content = re.sub(r'<pre[^>]*>.*?</pre>', store_pre_block, html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<code[^>]*>.*?</code>', store_code_block, html_content, flags=re.DOTALL | re.IGNORECASE)

        # Remove unwanted elements (nav/ads)
        patterns_to_remove = [
            r'<nav[^>]*>.*?</nav>',
            r'<div[^>]*class="[^"]*ad[^"]*"[^>]*>.*?</div>',
            r'<div[^>]*class="[^"]*nav[^"]*"[^>]*>.*?</div>',
            r'<aside[^>]*>.*?</aside>',
            r'<footer[^>]*>.*?</footer>',
            r'<header[^>]*>.*?</header>'
        ]

        for pattern in patterns_to_remove:
            html_content = re.sub(pattern, '', html_content, flags=re.DOTALL | re.IGNORECASE)

        # Fix list styling issues (but avoid code blocks)
        html_content = re.sub(r'\s*style="[^"]*list-style-type:\s*none[^"]*"', '', html_content)
        html_content = re.sub(r'<li\s+style="[^"]*"([^>]*)>', r'<li\1>', html_content)

        # Fix nested list structures
        patterns_to_fix = [
            r'<ol[^>]*>\s*<li[^>]*>\s*(<ul[^>]*>.*?</ul>)\s*</li>\s*</ol>',
            r'<ul[^>]*>\s*<li[^>]*>\s*(<ul[^>]*>.*?</ul>)\s*</li>\s*</ul>',
            r'<ol[^>]*>\s*<li[^>]*>\s*(<ol[^>]*>.*?</ol>)\s*</li>\s*</ol>',
            r'<li[^>]*>\s*(<[uo]l[^>]*>.*?</[uo]l>)\s*</li>'
        ]

        for _ in range(3):
            for pattern in patterns_to_fix:
                html_content = re.sub(pattern, r'\1', html_content, flags=re.DOTALL)

        # Restore code blocks
        for placeholder, original_code in code_blocks.items():
            html_content = html_content.replace(placeholder, original_code)

        return html_content

    def fix_relative_links(self, html_content, base_url="https://support.optisigns.com"):
        """Convert relative URLs to absolute URLs"""
        html_content = re.sub(r'href="(/[^"]*)"', f'href="{base_url}\\1"', html_content)
        html_content = re.sub(r'src="(/[^"]*)"', f'src="{base_url}\\1"', html_content)
        return html_content

    def html_to_markdown(self, html_content):
        """Convert HTML to Markdown while preserving code blocks and headings"""
        processed_html = html_content

        # Remove problematic CSS classes (but preserve code block classes)
        processed_html = re.sub(r'class="[^"]*wysiwyg-indent[^"]*"', '', processed_html)

        # Handle HTML entities
        processed_html = html.unescape(processed_html)

        # Remove empty paragraphs
        processed_html = re.sub(r'<p>\s*</p>', '', processed_html)
        processed_html = re.sub(r'<p>\s*&nbsp;\s*</p>', '', processed_html)

        # Configure html2text to preserve code blocks
        h = html2text.HTML2Text()
        h.ignore_links = False  # Preserve links
        h.ignore_images = False  # Keep images for now (will remove later)
        h.ignore_emphasis = False  # Keep bold/italic
        h.body_width = 0  # Don't wrap lines
        h.unicode_snob = True
        h.escape_snob = False
        h.use_automatic_links = True
        h.ignore_tables = False
        h.single_line_break = True
        h.default_image_alt = ""
        # CRITICAL: Don't ignore code blocks
        h.bypass_tables = False
        h.ignore_div = False

        markdown = h.handle(processed_html)

        # Clean up excessive blank lines
        markdown = re.sub(r'\n{3,}', '\n\n', markdown)

        # Fix escaped characters
        markdown = re.sub(r'\\([&.])', r'\1', markdown)

        # DON'T run the code block intelligence here - trust html2text for code blocks
        # The issue was that is_likely_code was removing legitimate code blocks

        return markdown

    def remove_images(self, markdown_content):
        """Remove all image references"""
        markdown_content = re.sub(r'!\[([^\]]*)\]\([^)]*\)', '', markdown_content)
        return markdown_content

    def remove_promotional_content(self, markdown_content):
        """Remove promotional sections"""
        patterns_to_remove = [
            r'### That\'s all!.*?support@optisigns\.com.*?\)',
            r'OptiSigns is the leader in.*?support@optisigns\.com.*?\)',
            r'If you have any additional questions.*?support@optisigns\.com.*?\)',
            r'feel free to reach out.*?support@optisigns\.com.*?\)'
        ]

        for pattern in patterns_to_remove:
            markdown_content = re.sub(pattern, '', markdown_content, flags=re.DOTALL | re.IGNORECASE)

        return markdown_content

    def remove_navigation_elements(self, markdown_content):
        """Remove table of contents"""
        lines = markdown_content.split('\n')
        cleaned_lines = []
        in_early_section = True
        bullet_list_count = 0
        in_code_block = False

        for i, line in enumerate(lines):
            # Track if we're in a code block
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                cleaned_lines.append(line)
                continue

            # Don't process lines inside code blocks
            if in_code_block:
                cleaned_lines.append(line)
                continue

            # Stop considering TOC removal after substantial content
            if in_early_section and i > 20:
                in_early_section = False

            # Count bullet lists in early section
            if in_early_section and re.match(r'^\s*[\*\-\+]\s+', line.strip()):
                bullet_list_count += 1
                if bullet_list_count > 8:  # Skip long TOCs
                    continue
            else:
                bullet_list_count = 0

            cleaned_lines.append(line)

        return '\n'.join(cleaned_lines)

    def remove_decorative_separators(self, markdown_content):
        """Remove decorative separators while preserving code blocks"""
        lines = markdown_content.split('\n')
        cleaned_lines = []
        in_code_block = False

        for line in lines:
            # Track code blocks
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                cleaned_lines.append(line)
                continue

            # Don't process lines inside code blocks
            if in_code_block:
                cleaned_lines.append(line)
                continue

            # Remove decorative separators (only outside code blocks)
            if re.match(r'^\s*[\*\-=]{3,}\s*$', line):
                # Skip this line
                continue

            cleaned_lines.append(line)

        # Clean up NOTE blocks
        content = '\n'.join(cleaned_lines)
        content = re.sub(r'\*\*NOTE\*\*\s*\n\s*---\s*\n', '**NOTE:** ', content)

        return content

    def remove_file_references(self, markdown_content):
        """Remove technical file references"""
        file_patterns = [
            r'!\[[^]]*firefox_[^]]*\]\([^)]*\)',
            r'!\[[^]]*\.(jpg|png|gif|jpeg)\]\([^)]*\)',
            r'\[[\w\d_]+\.(jpg|png|gif|jpeg)\]',
        ]

        for pattern in file_patterns:
            markdown_content = re.sub(pattern, '', markdown_content, flags=re.IGNORECASE)

        return markdown_content

    def remove_excessive_whitespace(self, markdown_content):
        """Clean up spacing while preserving code block formatting"""
        lines = markdown_content.split('\n')
        cleaned_lines = []
        in_code_block = False
        blank_line_count = 0

        for line in lines:
            # Track code blocks
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                cleaned_lines.append(line)
                blank_line_count = 0
                continue

            # Inside code blocks, preserve all formatting
            if in_code_block:
                cleaned_lines.append(line)
                continue

            # Outside code blocks, manage whitespace
            if line.strip() == '':
                blank_line_count += 1
                if blank_line_count <= 2:  # Max 2 consecutive blank lines
                    cleaned_lines.append(line)
            else:
                blank_line_count = 0
                # Remove trailing spaces from non-code lines
                cleaned_lines.append(line.rstrip())

        return '\n'.join(cleaned_lines).strip()

    def create_clean_metadata_header(self, article_data):
        """Create minimal metadata header"""
        title = article_data['title']
        article_id = article_data['id']
        url = article_data.get('html_url', 'Unknown')

        return f"""# {title}

**Article ID:** {article_id}  
**Article URL:** {url}

---

"""

    def clean_markdown_for_chatbot(self, markdown_content):
        """Master cleaning function that preserves code blocks"""
        markdown_content = self.remove_images(markdown_content)
        markdown_content = self.remove_promotional_content(markdown_content)
        markdown_content = self.remove_navigation_elements(markdown_content)
        markdown_content = self.remove_decorative_separators(markdown_content)
        markdown_content = self.remove_file_references(markdown_content)
        markdown_content = self.remove_excessive_whitespace(markdown_content)

        return markdown_content

    def process_article_to_markdown(self, article_data):
        """Complete processing pipeline"""
        html_content = article_data['body']

        # Step 1: Clean HTML while preserving code blocks
        cleaned_html = self.clean_html_content(html_content)

        # Step 2: Fix relative links
        fixed_html = self.fix_relative_links(cleaned_html)

        # Step 3: Convert to Markdown (preserves code blocks and headings)
        markdown_content = self.html_to_markdown(fixed_html)

        # Step 4: Apply chatbot optimizations while preserving code blocks
        cleaned_markdown = self.clean_markdown_for_chatbot(markdown_content)

        # Step 5: Add metadata header
        metadata = self.create_clean_metadata_header(article_data)

        return metadata + cleaned_markdown

    def create_slug(self, title):
        """Create filename slug"""
        slug = re.sub(r'[^\w\s-]', '', title.lower())
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug.strip('-')

    def save_article_as_markdown(self, article_data):
        """Save processed article as markdown file"""
        os.makedirs(self.output_dir, exist_ok=True)

        title = article_data['title']
        article_id = article_data['id']

        # Process through complete pipeline
        markdown_content = self.process_article_to_markdown(article_data)

        # Create unique filename
        slug = self.create_slug(title)
        filename = f"{slug}-{article_id}.md"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        return filepath

    def scrape_all_articles(self, max_articles=40):
        """Main scraping orchestrator"""
        logger.info("=== Starting Zendesk Article Scraping ===")

        articles_list = self.fetch_articles_list(max_articles)

        if not articles_list:
            logger.info("No articles found. Exiting.")
            return []

        logger.info(f"Starting to process {len(articles_list)} articles...")
        logger.info("=" * 50)

        successful_articles = []
        failed_articles = []

        for i, article_summary in enumerate(articles_list, 1):
            article_id = article_summary['id']
            article_title = article_summary['title']

            logger.info(f"\n[{i}/{len(articles_list)}] Processing: {article_title}")
            logger.info(f"    Article ID: {article_id}")

            article_data = self.fetch_article_content(article_id)

            if not article_data:
                failed_articles.append({
                    'id': article_id,
                    'title': article_title,
                    'error': 'Failed to fetch article data'
                })
                logger.error(f"    Failed to fetch article data")
                continue

            try:
                saved_file = self.save_article_as_markdown(article_data)
                successful_articles.append({
                    'id': article_id,
                    'title': article_title,
                    'file': saved_file,
                    'data': article_data
                })
                logger.info(f"    Saved: {os.path.basename(saved_file)}")

            except Exception as e:
                failed_articles.append({
                    'id': article_id,
                    'title': article_title,
                    'error': str(e)
                })
                logger.error(f"    Error saving article: {e}")

            # Rate limiting
            if i < len(articles_list):
                time.sleep(1)

        # Summary
        logger.info("\n" + "=" * 50)
        logger.info("SCRAPING SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Successfully processed: {len(successful_articles)} articles")
        logger.info(f"Failed to process: {len(failed_articles)} articles")

        if successful_articles:
            logger.info(f"\nArticles saved to: {self.output_dir}/")

        if failed_articles:
            logger.info("\nFailed articles:")
            for failed in failed_articles:
                logger.info(f"  - {failed['title']} (ID: {failed['id']}) - {failed['error']}")

        logger.info("=== Scraping completed ===")

        return successful_articles

def main():
    """Main entry point"""
    scraper = ZendeskScraper()
    articles = scraper.scrape_all_articles(max_articles=40)
    logger.info(f"Scraping complete. {len(articles)} articles processed.")

if __name__ == "__main__":
    main()
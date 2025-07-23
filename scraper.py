#!/usr/bin/env python3

import requests
import html2text
import re
import os
import html
import time
import json
import logging
from pathlib import Path
from datetime import datetime

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
        """Clean HTML content by removing unwanted elements and fixing structural issues"""
        # Remove navigation elements, ads, and unwanted content
        patterns_to_remove = [
            r'<nav[^>]*>.*?</nav>',
            r'<div[^>]*class="[^"]*ad[^"]*"[^>]*>.*?</div>',
            r'<div[^>]*class="[^"]*nav[^"]*"[^>]*>.*?</div>',
            r'<aside[^>]*>.*?</aside>',
            r'<footer[^>]*>.*?</footer>',
            r'<header[^>]*>.*?</header>'
        ]

        cleaned_html = html_content
        for pattern in patterns_to_remove:
            cleaned_html = re.sub(pattern, '', cleaned_html, flags=re.DOTALL | re.IGNORECASE)

        # Fix problematic list styling that confuses markdown conversion
        cleaned_html = re.sub(r'\s*style="[^"]*list-style-type:\s*none[^"]*"', '', cleaned_html)
        cleaned_html = re.sub(r'<li\s+style="[^"]*"([^>]*)>', r'<li\1>', cleaned_html)

        # Fix nested list structures that create formatting issues
        patterns_to_fix = [
            r'<ol[^>]*>\s*<li[^>]*>\s*(<ul[^>]*>.*?</ul>)\s*</li>\s*</ol>',
            r'<ul[^>]*>\s*<li[^>]*>\s*(<ul[^>]*>.*?</ul>)\s*</li>\s*</ul>',
            r'<ol[^>]*>\s*<li[^>]*>\s*(<ol[^>]*>.*?</ol>)\s*</li>\s*</ol>',
            r'<li[^>]*>\s*(<[uo]l[^>]*>.*?</[uo]l>)\s*</li>'
        ]

        # Apply fixes multiple times to handle deeply nested structures
        for _ in range(3):
            for pattern in patterns_to_fix:
                cleaned_html = re.sub(pattern, r'\1', cleaned_html, flags=re.DOTALL)

        return cleaned_html

    def fix_relative_links(self, html_content, base_url="https://support.optisigns.com"):
        """Convert relative URLs to absolute URLs"""
        # Fix relative href attributes (links)
        html_content = re.sub(r'href="(/[^"]*)"', f'href="{base_url}\\1"', html_content)

        # Fix relative src attributes (images, etc.)
        html_content = re.sub(r'src="(/[^"]*)"', f'src="{base_url}\\1"', html_content)

        return html_content

    def is_likely_code(self, content):
        """Determine if content is likely to be actual code vs regular text"""
        code_indicators = [
            r'[{}()\[\];]',  # Programming symbols
            r'^\s*(function|class|def|var|let|const|import|export)',  # Programming keywords
            r'[=<>!]{2,}',  # Comparison operators
            r'^\s*[a-zA-Z_][a-zA-Z0-9_]*\s*[:=]',  # Variable assignments
            r'^\s*[#//]',  # Comment markers
            r'<[^>]+>',  # HTML/XML tags
            r'^\s*\$'  # Shell command indicators
        ]

        for pattern in code_indicators:
            if re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
                return True

        # If content is mostly sentences with periods, probably not code
        sentences = content.count('.')
        words = len(content.split())
        if words > 10 and sentences > 2:
            return False

        # If content has typical list formatting, probably not code
        if re.search(r'^\s*[\*\-\+]\s+', content, re.MULTILINE):
            return False

        return False

    def html_to_markdown(self, html_content):
        """Convert HTML to clean Markdown while preserving code blocks and headings"""
        processed_html = html_content

        # Remove problematic CSS classes that might trigger code formatting
        processed_html = re.sub(r'class="[^"]*wysiwyg-indent[^"]*"', '', processed_html)

        # Handle HTML entities properly before conversion
        processed_html = html.unescape(processed_html)

        # Remove empty paragraphs and extra whitespace
        processed_html = re.sub(r'<p>\s*</p>', '', processed_html)
        processed_html = re.sub(r'<p>\s*&nbsp;\s*</p>', '', processed_html)

        # Configure html2text for clean output
        h = html2text.HTML2Text()
        h.ignore_links = False  # Preserve links
        h.ignore_images = False  # Keep images for now (will remove later)
        h.ignore_emphasis = False  # Keep bold/italic formatting
        h.body_width = 0  # Don't wrap lines
        h.unicode_snob = True
        h.escape_snob = False  # Don't escape special characters
        h.use_automatic_links = True
        h.ignore_tables = False  # Preserve tables
        h.single_line_break = True  # Use single line breaks
        h.default_image_alt = ""  # Don't add default alt text

        markdown = h.handle(processed_html)

        # Remove excessive blank lines
        markdown = re.sub(r'\n{3,}', '\n\n', markdown)

        # Fix escaped characters that shouldn't be escaped
        markdown = re.sub(r'\\([&.])', r'\1', markdown)

        # Fix any remaining code block issues using intelligent detection
        lines = markdown.split('\n')
        cleaned_lines = []
        in_code_block = False
        code_block_content = []

        for line in lines:
            if line.strip() == '```' or line.startswith('```'):
                if in_code_block:
                    # End of code block - check if it contains actual code
                    content = '\n'.join(code_block_content)
                    if self.is_likely_code(content):
                        # Keep as code block
                        cleaned_lines.extend(['```'] + code_block_content + ['```'])
                    else:
                        # Convert back to regular text (was false positive)
                        cleaned_lines.extend(code_block_content)
                    code_block_content = []
                    in_code_block = False
                else:
                    # Start of code block
                    in_code_block = True
            elif in_code_block:
                code_block_content.append(line)
            else:
                cleaned_lines.append(line)

        return '\n'.join(cleaned_lines)

    def remove_images(self, markdown_content):
        """Remove all image references ![alt](url) - images are useless for text-based AI"""
        markdown_content = re.sub(r'!\[([^\]]*)\]\([^)]*\)', '', markdown_content)
        return markdown_content

    def remove_promotional_content(self, markdown_content):
        """Remove 'That's all!' sections, company promotion and generic contact info"""
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
        """Remove table of contents bullet lists at document start - AI doesn't need structural navigation aids"""
        lines = markdown_content.split('\n')
        cleaned_lines = []
        in_early_section = True
        bullet_list_count = 0

        for i, line in enumerate(lines):
            # Stop considering TOC removal after we've seen substantial content
            if in_early_section and i > 20:
                in_early_section = False

            # If we're in early section and see bullet points, count them
            if in_early_section and re.match(r'^\s*[\*\-\+]\s+', line.strip()):
                bullet_list_count += 1
                # Skip long bullet lists at the beginning (likely TOCs)
                if bullet_list_count > 8:  # Skip if more than 8 bullets (likely TOC)
                    continue
            else:
                bullet_list_count = 0

            cleaned_lines.append(line)

        return '\n'.join(cleaned_lines)

    def remove_decorative_separators(self, markdown_content):
        """Clean up * * *, ---, and excessive formatting. Simplify NOTE blocks"""
        separators_to_remove = [
            r'\n\s*\*\s*\*\s*\*\s*\n',  # * * *
            r'\n\s*-{3,}\s*\n',         # --- (3 or more dashes)
            r'\n\s*={3,}\s*\n',         # === (3 or more equals)
            r'\*{4,}',                   # **** (4 or more asterisks)
        ]

        for pattern in separators_to_remove:
            markdown_content = re.sub(pattern, '\n\n', markdown_content)

        # Clean up NOTE blocks with excessive formatting to simple **NOTE:**
        markdown_content = re.sub(r'\*\*NOTE\*\*\s*\n\s*---\s*\n', '**NOTE:** ', markdown_content)

        return markdown_content

    def remove_file_references(self, markdown_content):
        """Remove technical screenshot filenames and firefox_xyz.jpg type references"""
        file_patterns = [
            r'!\[[^]]*firefox_[^]]*\]\([^)]*\)',  # Firefox screenshot references
            r'!\[[^]]*\.(jpg|png|gif|jpeg)\]\([^)]*\)',  # Image file references with extensions
            r'\[[\w\d_]+\.(jpg|png|gif|jpeg)\]',  # File name references in brackets
        ]

        for pattern in file_patterns:
            markdown_content = re.sub(pattern, '', markdown_content, flags=re.IGNORECASE)

        return markdown_content

    def remove_excessive_whitespace(self, markdown_content):
        """Clean up spacing and formatting. Limit to max 3 consecutive line breaks"""
        # Remove excessive blank lines (max 3 line breaks)
        markdown_content = re.sub(r'\n{4,}', '\n\n\n', markdown_content)

        # Remove trailing spaces at end of lines
        markdown_content = re.sub(r'[ \t]+\n', '\n', markdown_content)

        # Remove leading spaces on lines (except for code indentation)
        markdown_content = re.sub(r'\n[ \t]+', '\n', markdown_content)

        return markdown_content.strip()

    def create_clean_metadata_header(self, article_data):
        """Create minimal metadata header with only Article ID and URL for citations"""
        title = article_data['title']
        article_id = article_data['id']
        url = article_data.get('html_url', 'Unknown')

        return f"""# {title}

**Article ID:** {article_id}  
**Article URL:** {url}

---

"""

    def clean_markdown_for_chatbot(self, markdown_content):
        """Master function that applies all cleaning steps for chatbot optimization"""
        # Apply all cleaning functions in the optimal sequence
        markdown_content = self.remove_images(markdown_content)
        markdown_content = self.remove_promotional_content(markdown_content)
        markdown_content = self.remove_navigation_elements(markdown_content)
        markdown_content = self.remove_decorative_separators(markdown_content)
        markdown_content = self.remove_file_references(markdown_content)
        markdown_content = self.remove_excessive_whitespace(markdown_content)

        return markdown_content

    def process_article_to_markdown(self, article_data):
        """Complete processing pipeline: HTML → Clean HTML → Markdown → Chatbot-optimized Markdown"""
        # Extract HTML content
        html_content = article_data['body']

        # Step 1: Clean HTML (remove nav/ads, fix HTML issues)
        cleaned_html = self.clean_html_content(html_content)

        # Step 2: Fix relative links to absolute URLs
        fixed_html = self.fix_relative_links(cleaned_html)

        # Step 3: Convert HTML to Markdown (preserves headings and code blocks)
        markdown_content = self.html_to_markdown(fixed_html)

        # Step 4: Apply chatbot-specific optimizations
        cleaned_markdown = self.clean_markdown_for_chatbot(markdown_content)

        # Step 5: Add clean metadata header for citations
        metadata = self.create_clean_metadata_header(article_data)

        return metadata + cleaned_markdown

    def create_slug(self, title):
        """Create a clean filename slug from article title"""
        slug = re.sub(r'[^\w\s-]', '', title.lower())
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug.strip('-')

    def save_article_as_markdown(self, article_data):
        """Save processed article as markdown file"""
        os.makedirs(self.output_dir, exist_ok=True)

        title = article_data['title']
        article_id = article_data['id']

        # Process article through complete pipeline
        markdown_content = self.process_article_to_markdown(article_data)

        # Create filename with article ID to ensure uniqueness
        slug = self.create_slug(title)
        filename = f"{slug}-{article_id}.md"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        return filepath

    def scrape_all_articles(self, max_articles=40):
        """Main scraping function - orchestrates the complete scraping process"""
        logger.info("=== Starting Zendesk Article Scraping ===")

        # Fetch list of articles
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

            # Fetch full article data
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
                # Save as markdown using complete processing pipeline
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

            # Rate limiting - wait 1 second between requests to be respectful
            if i < len(articles_list):
                time.sleep(1)

        # Print comprehensive summary
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
    """Main entry point when script is run standalone"""
    scraper = ZendeskScraper()
    articles = scraper.scrape_all_articles(max_articles=40)
    logger.info(f"Scraping complete. {len(articles)} articles processed.")

if __name__ == "__main__":
    main()
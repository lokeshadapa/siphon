#!/usr/bin/env python3

import os
import sys
import logging
from datetime import datetime
from batch_runner import BatchRunner

def setup_logging():
    """Setup logging to both console and file"""
    # Create logs directory if it doesn't exist
    log_dir = "./logs"
    os.makedirs(log_dir, exist_ok=True)

    # Create log filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"batch_run_{timestamp}.log")

    # Configure logging format
    log_format = '%(asctime)s - %(levelname)s - %(message)s'

    # Setup root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            # Console handler (for Docker logs)
            logging.StreamHandler(sys.stdout),
            # File handler (for persistent logs)
            logging.FileHandler(log_file, encoding='utf-8')
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - log file: {log_file}")
    return logger

def validate_environment():
    """Validate required environment variables"""
    logger = logging.getLogger(__name__)

    # Check for OpenAI API key
    openai_key = os.getenv('OPENAI_API_KEY')
    if not openai_key:
        logger.error("ERROR: OPENAI_API_KEY environment variable not found!")
        logger.error("Please set the environment variable: OPENAI_API_KEY=sk-...")
        return False

    # Validate key format (basic check)
    if not openai_key.startswith('sk-'):
        logger.error("ERROR: OPENAI_API_KEY appears to be invalid (should start with 'sk-')")
        return False

    logger.info("Environment validation passed")
    return True

def main():
    """Main entry point for Docker container"""
    # Setup logging first
    logger = setup_logging()

    logger.info("=" * 60)
    logger.info("OPTIBOT DAILY SYNC STARTING")
    logger.info("=" * 60)
    logger.info(f"Start time: {datetime.now().isoformat()}")

    try:
        # Validate environment
        if not validate_environment():
            logger.error("Environment validation failed")
            sys.exit(1)

        # Initialize batch runner
        logger.info("Initializing batch runner...")
        runner = BatchRunner()

        # Run delta sync (auto-detects first run vs incremental)
        logger.info("Starting delta sync...")
        success = runner.run_delta_sync(max_articles=40)

        # Log final result
        end_time = datetime.now()
        logger.info("=" * 60)

        if success:
            logger.info("OPTIBOT DAILY SYNC COMPLETED SUCCESSFULLY")
            logger.info(f"End time: {end_time.isoformat()}")
            logger.info("Container exiting with code 0")
            sys.exit(0)
        else:
            logger.error("OPTIBOT DAILY SYNC FAILED")
            logger.error(f"End time: {end_time.isoformat()}")
            logger.error("Container exiting with code 1")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Sync interrupted by user")
        sys.exit(1)

    except Exception as e:
        logger.error(f"Unexpected error occurred: {e}")
        logger.error("Container exiting with code 1")
        sys.exit(1)

if __name__ == "__main__":
    main()
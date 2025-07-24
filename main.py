#!/usr/bin/env python3

import os
import sys
import logging
from datetime import datetime
from batch_runner import BatchRunner

def setup_logging():
    """Setup logging to both console and file with persistent storage"""
    # Use persistent volume path if available, otherwise local
    if os.path.exists('/app/state'):
        # DigitalOcean persistent volume
        log_dir = "/app/state/logs"
        state_dir = "/app/state"
    else:
        # Local development
        log_dir = "./logs"
        state_dir = "."

    # Create logs directory if it doesn't exist
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
            # Console handler (for DigitalOcean logs)
            logging.StreamHandler(sys.stdout),
            # File handler (for persistent logs)
            logging.FileHandler(log_file, encoding='utf-8')
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - log file: {log_file}")
    logger.info(f"State directory: {state_dir}")

    # Set environment variable for BatchRunner to use persistent paths
    os.environ['SIPHON_STATE_DIR'] = state_dir

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
    logger.info(f"Using OpenAI API key: sk-...{openai_key[-4:]}")  # Show last 4 chars only
    return True

def main():
    """Main entry point for Docker container"""
    # Setup logging first
    logger = setup_logging()

    logger.info("=" * 60)
    logger.info("OPTIBOT DAILY SYNC STARTING")
    logger.info("=" * 60)
    logger.info(f"Start time: {datetime.now().isoformat()}")
    logger.info(f"Running on: DigitalOcean" if os.path.exists('/app/state') else "Local environment")

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
        duration = end_time - datetime.fromisoformat(logger.handlers[1].baseFilename.split('_')[2].split('.')[0] + 'T' + logger.handlers[1].baseFilename.split('_')[3].split('.')[0])

        logger.info("=" * 60)

        if success:
            logger.info("OPTIBOT DAILY SYNC COMPLETED SUCCESSFULLY")
            logger.info(f"End time: {end_time.isoformat()}")
            logger.info("Container exiting with code 0")

            # Log persistent file locations for reference
            if os.path.exists('/app/state'):
                logger.info("Persistent files saved to:")
                logger.info("  - State: /app/state/file_mapping.json")
                logger.info("  - Timestamp: /app/state/last_run.txt")
                logger.info("  - Articles: /app/state/articles/")
                logger.info("  - Logs: /app/state/logs/")

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
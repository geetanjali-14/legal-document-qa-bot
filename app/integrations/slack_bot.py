"""
CLI entry point to launch the Legal QA Slack Bot in Socket Mode.
Usage:
    python -m app.integrations.slack_bot
"""
import sys
from app.core.config import settings
from app.core.logging import logger
from app.integrations.slack_adapter import SlackAdapter


def main():
    logger.info("Initializing Slack Integration for Legal QA Chatbot...")
    if not settings.SLACK_BOT_TOKEN or not settings.SLACK_APP_TOKEN:
        logger.error(
            "Slack tokens not configured. Please ensure SLACK_BOT_TOKEN and SLACK_APP_TOKEN are set in your environment or .env."
        )
        sys.exit(1)

    try:
        adapter = SlackAdapter()
        logger.info(f"Connecting to Legal QA REST API at: {settings.LEGAL_QA_API_BASE_URL}")
        adapter.start_socket_mode()
    except KeyboardInterrupt:
        logger.info("Slack Bot shut down cleanly by user.")
    except Exception as e:
        logger.error(f"Fatal error running Slack Bot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()


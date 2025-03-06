#!/usr/bin/env python3
"""
BugNinja v2 - Simplified AI-Driven Web Testing Tool
CLI entry point
"""

import os
import sys
import asyncio
import argparse
import dotenv

from bugninja_v2.bugninja import BugNinja


async def main():
    """Main entry point for the web testing tool."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="AI-driven web testing tool")
    parser.add_argument("--url", required=True, help="Starting URL for testing")
    parser.add_argument(
        "--goal", required=True, help="Testing goal (e.g., 'Sign up for a new account')"
    )
    parser.add_argument(
        "--max-steps", type=int, default=10, help="Maximum number of steps to take"
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory to save screenshots and videos",
    )
    parser.add_argument(
        "--headless", action="store_true", help="Run browser in headless mode"
    )
    parser.add_argument(
        "--video-quality",
        choices=["low", "medium", "high"],
        default="medium",
        help="Quality of video recording (low/medium/high)",
    )
    parser.add_argument(
        "--goal-confidence",
        type=float,
        default=0.8,
        help="Confidence threshold for goal detection (0.0-1.0, default: 0.8)",
    )
    args = parser.parse_args()

    # Validate confidence threshold
    if args.goal_confidence < 0.0 or args.goal_confidence > 1.0:
        print("⚠️ Goal confidence threshold must be between 0.0 and 1.0")
        return 1

    # Load environment variables from .env file if it exists
    dotenv.load_dotenv()

    # Check for OpenAI credentials
    if not os.getenv("AZURE_OPENAI_ENDPOINT") or not os.getenv("AZURE_OPENAI_API_KEY"):
        print(
            "⚠️ Azure OpenAI credentials not found in environment variables or .env file"
        )
        print("Please set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY")
        return 1

    # Initialize the web tester
    tester = BugNinja(
        headless=args.headless,
        output_dir=args.output_dir,
        video_quality=args.video_quality,
        goal_confidence=args.goal_confidence,
    )

    try:
        # Start the browser
        await tester.start()

        # Run the test
        success = await tester.run_test(args.url, args.goal, args.max_steps)

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n👋 User interrupted. Exiting...")
        return 130
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        # Close the browser
        await tester.stop()


def main_cli():
    """Entry point for the CLI."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

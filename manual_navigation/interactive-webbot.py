#!/usr/bin/env python3
"""
Interactive Web Bot - Navigate websites by selecting elements interactively.
"""

import os
import sys
import asyncio
import argparse
from typing import List, Dict, Any, Optional

from web_analyzer import WebAnalyzer
from element_selector import display_top_elements, get_user_selection


async def main():
    """Main interactive navigation loop."""
    parser = argparse.ArgumentParser(
        description="Interactive web navigation bot. Analyze a webpage, select elements, and navigate."
    )
    parser.add_argument("url", help="Starting URL to navigate to")
    parser.add_argument(
        "--visible",
        "-V",
        action="store_false",
        dest="headless",
        help="Run in visible mode (show browser UI)",
        default=True,
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default="./screenshots",
        help="Directory to save screenshots",
    )
    parser.add_argument(
        "--count", "-c", type=int, default=10, help="Number of top elements to display"
    )
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    # Initialize the web analyzer
    analyzer = WebAnalyzer(headless=args.headless)

    try:
        # Start the browser
        await analyzer.start()

        # Initial URL
        current_url = args.url
        exit_requested = False

        # Main interaction loop
        while not exit_requested:
            # Navigate to the current URL and analyze the page
            print(f"\n🌐 Navigating to: {current_url}")
            success = await analyzer.navigate_and_analyze(current_url)

            if not success:
                print(f"⚠️ Failed to navigate to {current_url}")
                break

            # Save the current screenshot
            screenshot_path = os.path.join(
                args.output_dir, f"screenshot_{len(os.listdir(args.output_dir))}.png"
            )
            await analyzer.take_screenshot(screenshot_path)
            print(f"📸 Screenshot saved to {screenshot_path}")

            # Get elements and display top options
            elements = analyzer.get_actionable_elements()
            if not elements:
                print("⚠️ No actionable elements found on this page")
                break

            # Display top elements sorted by hierarchy level
            display_top_elements(elements, args.count)

            # Get user selection
            selection = get_user_selection(elements[: args.count])

            if selection == "exit":
                exit_requested = True
                print("👋 Exiting...")
                continue
            elif selection == "back":
                # Try to go back in history
                await analyzer.go_back()
                current_url = analyzer.get_current_url()
                continue
            elif selection == "url":
                # Allow user to enter a new URL
                new_url = input("Enter new URL: ")
                if new_url.strip():
                    current_url = new_url
                continue
            elif selection == "reload":
                # Reload the current page
                continue

            # Otherwise, it's an element index - perform the action
            element_index = int(selection)
            selected_element = elements[element_index]

            # Perform action on the selected element
            print(f"🖱️ Clicking: {selected_element.text or selected_element.selector}")
            action_result = await analyzer.interact_with_element(selected_element)

            if action_result:
                # Check if URL changed after interaction
                new_url = analyzer.get_current_url()
                if new_url != current_url:
                    print(f"📍 URL changed to: {new_url}")
                    current_url = new_url
            else:
                print("⚠️ Failed to interact with element")

    except KeyboardInterrupt:
        print("\n👋 User interrupted. Exiting...")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        # Close the browser
        await analyzer.stop()
        print("🔒 Browser closed")


if __name__ == "__main__":
    asyncio.run(main())

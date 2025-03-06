#!/usr/bin/env python3
"""
Automated Web Navigator - Navigate websites automatically using Azure OpenAI to make decisions.
"""

import os
import sys
import asyncio
import argparse
import json
import base64
from typing import List, Dict, Any, Optional
import requests
from dataclasses import asdict
from dotenv import load_dotenv
from openai import AzureOpenAI

from web_analyzer import WebAnalyzer, ActionableElement
from element_selector import display_top_elements, get_user_selection

# Load environment variables from .env file
load_dotenv()


async def ask_azure_openai(
    screenshot_path: str, elements: List[ActionableElement], goal: str
) -> int:
    """
    Ask Azure OpenAI which element to interact with based on the goal.

    Args:
        screenshot_path (str): Path to the screenshot of the current page
        elements (List[ActionableElement]): List of actionable elements
        goal (str): The goal of the navigation

    Returns:
        int: Index of the element to interact with
    """
    # Convert elements to dict for JSON serialization
    elements_dict = []
    for i, elem in enumerate(elements):
        elem_dict = asdict(elem)
        elem_dict["index"] = i  # Add index for reference
        elements_dict.append(elem_dict)

    # Encode screenshot as base64
    with open(screenshot_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode("utf-8")

    # Initialize the Azure OpenAI client
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2024-05-01-preview",
    )

    # Format the prompt for the AI
    prompt = f"""
You are an AI web navigator. Your task is to help navigate a website to achieve a specific goal.

GOAL: {goal}

Based on the screenshot and the actionable elements provided, select the most appropriate element to interact with next.
You must respond with ONLY the index of the chosen element as a valid JSON object with a single field 'selected_element_index'.
For example: {{"selected_element_index": 2}}

Choose the element that best helps achieve the goal. Consider:
1. Elements with lower hierarchy levels are more important
2. Text that matches keywords related to the goal
3. Element types (buttons, links, inputs) that would move toward the goal
    """

    # Get the deployment name from .env or use a default
    deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini")

    try:
        # Call the Azure OpenAI API
        response = client.chat.completions.create(
            model=deployment_name,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "You are a web navigation assistant that helps users navigate websites. You will be given a screenshot of a webpage and a list of actionable elements. Your task is to select the most appropriate element to interact with based on the user's goal.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            },
                        },
                        {
                            "type": "text",
                            "text": f"Actionable Elements: {json.dumps(elements_dict, indent=2)}",
                        },
                    ],
                },
            ],
        )

        # Parse the response
        content = response.choices[0].message.content
        selection = json.loads(content)
        selected_index = selection.get("selected_element_index", 0)

        # Ensure it's within range
        if selected_index < 0 or selected_index >= len(elements):
            print(f"⚠️ AI selected invalid index {selected_index}, defaulting to 0")
            selected_index = 0

        return selected_index
    except Exception as e:
        print(f"Error calling Azure OpenAI API: {e}")
        return 0  # Default to first element if API fails


async def main():
    """Main automated navigation loop with improved handling for complex scenarios."""
    parser = argparse.ArgumentParser(
        description="Automated web navigation bot using Azure OpenAI for decision making."
    )
    parser.add_argument("url", help="Starting URL to navigate to")
    parser.add_argument("goal", help="Goal to achieve in the navigation")
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
        "--max-steps",
        "-m",
        type=int,
        default=10,  # Increased from 5 to allow for more steps
        help="Maximum number of steps to take",
    )
    parser.add_argument(
        "--retry-limit",
        "-r",
        type=int,
        default=3,
        help="Maximum number of retries for the same element",
    )
    args = parser.parse_args()

    # Check for required environment variables
    if not os.getenv("AZURE_OPENAI_ENDPOINT") or not os.getenv("AZURE_OPENAI_API_KEY"):
        print("⚠️ Azure OpenAI credentials not found in .env file.")
        print(
            "Please create a .env file with AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY."
        )
        return

    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    # Initialize the web analyzer
    analyzer = WebAnalyzer(headless=args.headless)

    try:
        # Start the browser
        await analyzer.start()

        # Set the current goal for better decision making
        analyzer.set_current_goal(args.goal)

        # Initial URL
        current_url = args.url
        goal = args.goal
        exit_requested = False
        steps_taken = 0
        retries = 0
        max_retries = args.retry_limit

        # Track previously clicked elements to detect loops
        previously_clicked = []

        print(f"🎯 Goal: {goal}")
        print(f"🔄 Maximum steps: {args.max_steps}")

        # Main automation loop
        while not exit_requested and steps_taken < args.max_steps:
            # Navigate to the current URL and analyze the page
            print(f"\n🌐 Step {steps_taken + 1}: Navigating to {current_url}")
            success = await analyzer.navigate_and_analyze(current_url)

            if not success:
                print(f"⚠️ Failed to navigate to {current_url}")
                break

            # Save the current screenshot
            screenshot_path = os.path.join(
                args.output_dir, f"screenshot_{steps_taken}.png"
            )
            await analyzer.take_screenshot(screenshot_path)
            print(f"📸 Screenshot saved to {screenshot_path}")

            # Get elements
            elements = analyzer.get_actionable_elements()
            if not elements:
                print("⚠️ No actionable elements found on this page")
                break

            # Ask Azure OpenAI which element to interact with
            print("🧠 Asking Azure OpenAI to choose the next action...")
            selected_index = await ask_azure_openai(screenshot_path, elements, goal)
            selected_element = elements[selected_index]

            # Print the AI's selection
            print(f"🤖 AI selected element {selected_index}:")
            print(f"  Type: {selected_element.element_type}")
            print(f"  Text: {selected_element.text or selected_element.selector}")
            print(f"  Hierarchy Level: {selected_element.hierarchy_level}")

            # Check if we're in a loop
            element_identifier = f"{selected_element.element_type}:{selected_element.text or selected_element.selector}"
            current_state = f"{analyzer.page.url}:{element_identifier}"

            if current_state in previously_clicked[-3:]:
                retries += 1
                print(f"⚠️ Possible navigation loop detected ({retries}/{max_retries})")

                if retries >= max_retries:
                    print(
                        "🔄 Too many retries on the same element. Trying a different approach..."
                    )

                    # Try the second-best option instead
                    if len(elements) > 1:
                        # Get the next best element by excluding the current one
                        alternative_elements = [
                            e for i, e in enumerate(elements) if i != selected_index
                        ]
                        alternative_index = 0  # Take the next best element
                        selected_element = alternative_elements[alternative_index]
                        print(f"🔄 Switching to alternative element:")
                        print(f"  Type: {selected_element.element_type}")
                        print(
                            f"  Text: {selected_element.text or selected_element.selector}"
                        )

                    retries = 0  # Reset retries
            else:
                retries = 0  # Reset retries if we're not in a loop

            # Track this click to detect loops
            previously_clicked.append(current_state)

            # Store current URL to detect changes
            before_url = analyzer.get_current_url()

            # Interact with the selected element
            print(f"🖱️ Clicking: {selected_element.text or selected_element.selector}")
            action_result = await analyzer.interact_with_element(selected_element)

            if action_result:
                # Check if URL changed after interaction
                new_url = analyzer.get_current_url()
                if new_url != before_url:
                    print(f"📍 URL changed to: {new_url}")
                    current_url = new_url

                    # Success detection - check if goal achieved based on URL or page content
                    if "google" in goal.lower() and "google" in new_url.lower():
                        print("🎉 Google authentication page detected!")
                    elif "login" in goal.lower() and any(
                        x in new_url.lower()
                        for x in ["account", "profile", "dashboard"]
                    ):
                        print("🎉 Possible successful login detected!")
            else:
                print("⚠️ Failed to interact with element")

            # Increment steps counter
            steps_taken += 1

            # Brief pause to let the page settle
            await asyncio.sleep(2)

            # Check if we need to handle any overlays that might have appeared
            await analyzer._handle_common_overlays()

        if steps_taken >= args.max_steps:
            print(f"\n🛑 Reached maximum steps limit ({args.max_steps})")

        print(f"\n✅ Navigation complete. Took {steps_taken} steps.")
        print(f"📍 Final URL: {analyzer.get_current_url()}")

        # Take a final screenshot
        final_screenshot = os.path.join(args.output_dir, "final_screenshot.png")
        await analyzer.take_screenshot(final_screenshot)
        print(f"📸 Final screenshot saved to {final_screenshot}")

    except KeyboardInterrupt:
        print("\n👋 User interrupted. Exiting...")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Close the browser
        await analyzer.stop()
        print("🔒 Browser closed")


async def ask_azure_openai(
    screenshot_path: str, elements: List[ActionableElement], goal: str
) -> int:
    """
    Ask Azure OpenAI which element to interact with based on the goal.

    Improved prompt to better handle navigation challenges.

    Args:
        screenshot_path (str): Path to the screenshot of the current page
        elements (List[ActionableElement]): List of actionable elements
        goal (str): The goal of the navigation

    Returns:
        int: Index of the element to interact with
    """
    # Convert elements to dict for JSON serialization
    elements_dict = []
    for i, elem in enumerate(elements):
        elem_dict = asdict(elem)
        elem_dict["index"] = i  # Add index for reference
        elements_dict.append(elem_dict)

    # Encode screenshot as base64
    with open(screenshot_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode("utf-8")

    # Initialize the Azure OpenAI client
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2024-05-01-preview",
    )

    # Format the prompt for the AI with improved guidance
    prompt = f"""
You are an AI web navigator. Your task is to help navigate a website to achieve a specific goal.

GOAL: {goal}

Based on the screenshot and the actionable elements provided, select the most appropriate element to interact with next.
You must respond with ONLY the index of the chosen element as a valid JSON object with a single field 'selected_element_index'.
For example: {{"selected_element_index": 2}}

Choose the element that best helps achieve the goal. Consider:
1. Elements with lower hierarchy levels are more important
2. Text that matches keywords related to the goal
3. Element types (buttons, links, inputs) that would move toward the goal

CURRENT SITUATION:
1. If you see login options like "Sign in with Google", "Continue with Google", select that if the goal involves Google authentication
2. If you see cookie consent banners, popups, or overlays, prioritize handling those first
3. Look for elements that match the goal keywords (login, sign in, etc.)
4. Choose a different element if you see that the same element has been chosen before without progress
    """

    # Get the deployment name from .env or use a default
    deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini")

    try:
        # Call the Azure OpenAI API
        response = client.chat.completions.create(
            model=deployment_name,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "You are a web navigation assistant that helps users navigate websites. Your task is to select the most appropriate element to interact with to achieve the user's goal. Be especially aware of login flows, authentication buttons, cookie banners, and popups.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            },
                        },
                        {
                            "type": "text",
                            "text": f"Actionable Elements: {json.dumps(elements_dict, indent=2)}",
                        },
                    ],
                },
            ],
        )

        # Parse the response
        content = response.choices[0].message.content
        selection = json.loads(content)
        selected_index = selection.get("selected_element_index", 0)

        # Ensure it's within range
        if selected_index < 0 or selected_index >= len(elements):
            print(f"⚠️ AI selected invalid index {selected_index}, defaulting to 0")
            selected_index = 0

        return selected_index
    except Exception as e:
        print(f"Error calling Azure OpenAI API: {e}")
        return 0  # Default to first element if API fails


if __name__ == "__main__":
    asyncio.run(main())
